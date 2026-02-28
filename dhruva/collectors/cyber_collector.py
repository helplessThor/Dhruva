"""Dhruva — Cyber Threat Collector (ThreatFox API).

Uses the abuse.ch ThreatFox API to surface real, live threat intelligence:
active malware campaigns, C2 infrastructure, botnets — all with real geo attribution.

API key is loaded from credentials.json -> "threatfox_api_key".

Geolocates IOCs (IPs) using the free ip-api.com batch endpoint.
"""

import logging
from datetime import datetime, timezone
import httpx

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

THREATFOX_API_URL = "https://threatfox-api.abuse.ch/api/v1/"
IP_API_BATCH_URL  = "http://ip-api.com/batch"

# Severity mappings based on ThreatFox tags or malware names
_ATTACK_KEYWORDS = {
    "ransomware": 5, "apt": 5, "cobalt strike": 5, "cobalt_strike": 5,
    "botnet": 3, "c2": 4, "c&c": 4, "command and control": 4,
    "trojan": 3, "stealer": 4, "phishing": 2, "malware": 3, "miner": 2
}

class CyberCollector(BaseCollector):
    """Fetches live threat intelligence IOCs from ThreatFox.
    
    Filters for IP-based IOCs (ip:port, ipv4) to ensure they can be mapped
    to a physical location on the globe. Batches the IPs to ip-api.com to
    resolve their lat/lon coordinates natively.
    """

    def __init__(self, interval: int = 120):
        # 2 minutes interval is reasonable. ThreatFox updates frequently.
        super().__init__(name="cyber", interval=interval)
        self._seen_ids: set[str] = set()
        self._active_events: dict[str, dict] = {}

    def _get_api_key(self) -> str:
        try:
            from backend.config import settings
            return getattr(settings, "threatfox_api_key", "") or ""
        except Exception:
            return ""

    @staticmethod
    def _pulse_severity(malware: str, threat_type: str, tags: list[str]) -> int:
        """Derive severity 1-5 from malware name and tags."""
        combined = f"{malware} {threat_type} {' '.join(tags)}".lower()
        base = 2
        for kw, sev in _ATTACK_KEYWORDS.items():
            if kw in combined:
                base = max(base, sev)
        return min(base, 5)

    async def _geocode_ips(self, ips: list[str]) -> dict[str, dict]:
        """Batch geocode a list of IPs using ip-api.com."""
        if not ips:
            return {}
            
        # ip-api allows up to 100 IPs per batch.
        # Ensure we only take unique IPs and limit to 100.
        unique_ips = list(set(ips))[:100]
        
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            
        try:
            resp = await self._http_client.post(
                IP_API_BATCH_URL, 
                json=unique_ips,
                timeout=15.0
            )
            resp.raise_for_status()
            results = resp.json()
            
            geo_map = {}
            for r in results:
                if r.get("status") == "success":
                    geo_map[r["query"]] = {
                        "lat": r.get("lat"),
                        "lon": r.get("lon"),
                        "country": r.get("country", "Unknown"),
                        "city": r.get("city", "Unknown")
                    }
            return geo_map
        except Exception as e:
            logger.error("[cyber] IP geocoding failed: %s", e)
            return {}

    async def collect(self) -> list[dict]:
        """Fetch latest IOCs from ThreatFox."""
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("[cyber] Cannot collect: ThreatFox API key missing.")
            return []

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)

        headers = {"Auth-Key": api_key}
        payload = {"query": "get_iocs", "days": 1}

        try:
            resp = await self._http_client.post(
                THREATFOX_API_URL, headers=headers, json=payload, timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("[cyber] ThreatFox API request failed: %s", e)
            return []

        if data.get("query_status") != "ok":
            logger.warning("[cyber] ThreatFox returned status: %s", data.get("query_status"))
            return []

        iocs_data = data.get("data", [])
        if not iocs_data:
            logger.debug("[cyber] ThreatFox returned no new IOCs")
            return []

        # Filter for IP IOCs we haven't seen yet
        ip_iocs = []
        ips_to_geocode = []
        for ioc in iocs_data:
            ioc_id = str(ioc.get("id", ""))
            if not ioc_id or ioc_id in self._seen_ids:
                continue
                
            ioc_type = ioc.get("ioc_type", "")
            if ioc_type in ("ip:port", "ipv4"):
                # Extract clean IP
                raw_ioc = ioc.get("ioc", "")
                clean_ip = raw_ioc.split(":")[0] if ":" in raw_ioc else raw_ioc
                iocs_data_item = ioc.copy()
                iocs_data_item["_clean_ip"] = clean_ip
                
                ip_iocs.append(iocs_data_item)
                ips_to_geocode.append(clean_ip)

        if not ip_iocs:
            return []
            
        # Geocode the IPs (limit to 100 per cycle to respect priority limits)
        geo_map = await self._geocode_ips(ips_to_geocode[:100])
        
        events = []
        for ioc in ip_iocs[:100]:
            clean_ip = ioc["_clean_ip"]
            geo = geo_map.get(clean_ip)
            
            if not geo or geo["lat"] is None or geo["lon"] is None:
                continue # Skip if we can't geocode
                
            ioc_id = str(ioc.get("id"))
            self._seen_ids.add(ioc_id)
            
            malware = ioc.get("malware_printable") or "Unknown Malware"
            threat_type = ioc.get("threat_type_desc") or ioc.get("threat_type") or "Threat"
            tags = ioc.get("tags") or []
            severity = self._pulse_severity(malware, threat_type, tags)
            
            first_seen = ioc.get("first_seen")
            if not first_seen:
                first_seen = datetime.now(timezone.utc).isoformat()
            elif " UTC" in first_seen:
                # ThreatFox returns "2020-12-08 13:36:27 UTC"
                try:
                    dt = datetime.strptime(first_seen.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
                    first_seen = dt.replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    first_seen = datetime.now(timezone.utc).isoformat()
                    
            event_title = f"{threat_type} — {malware}"
            if len(event_title) > 60:
                event_title = event_title[:57] + "..."
                
            reporter = ioc.get("reporter") or "Unknown"
            confidence = ioc.get("confidence_level", 50)
            
            desc_parts = [
                f"Malware: {malware}",
                f"IOC: {ioc.get('ioc')}",
                f"Confidence: {confidence}%",
                f"Location: {geo.get('city', 'Unknown')}, {geo.get('country', 'Unknown')}"
            ]
            
            self._active_events[ioc_id] = {
                "id": f"cyber-tf-{ioc_id}",
                "type": "cyber",
                "latitude": round(geo["lat"], 4),
                "longitude": round(geo["lon"], 4),
                "severity": severity,
                "timestamp": first_seen,
                "source": f"ThreatFox — {reporter}",
                "title": event_title,
                "description": " · ".join(desc_parts),
                "metadata": {
                    "attack_type": threat_type,
                    "malware": malware,
                    "ioc": ioc.get("ioc"),
                    "confidence": confidence,
                    "tags": tags[:5] if isinstance(tags, list) else [],
                    "reporter": reporter,
                    "reference": ioc.get("reference"),
                    "city": geo.get("city"),
                    "country": geo.get("country")
                },
            }
            
        # Purge _active_events older than 24 hours to keep map fresh
        now_utc = datetime.now(timezone.utc)
        stale_ids = []
        for eid, ev in self._active_events.items():
            try:
                # Event timestamp is ISO string
                ev_time = datetime.fromisoformat(ev["timestamp"])
                if (now_utc - ev_time).total_seconds() > 86400:
                    stale_ids.append(eid)
            except Exception:
                pass
                
        for eid in stale_ids:
            del self._active_events[eid]
            
        # Bound the seen cache
        if len(self._seen_ids) > 5000:
            self._seen_ids = set(list(self._seen_ids)[-2000:])

        active_list = list(self._active_events.values())
        logger.info("[cyber] ThreatFox returning %d total active geolocatable IOCs", len(active_list))
        return active_list
