"""Dhruva — Cyber Threat Collector (AlienVault OTX).

Uses the AlienVault Open Threat Exchange (OTX) API to surface real,
live threat intelligence: active malware campaigns, C2 infrastructure,
phishing kits, ransomware, APT activity — all with real geo attribution.

API key is loaded from credentials.json → "otx_api_key" or env var
DHRUVA_OTX_API_KEY. The OTX API is free; the key simply unlocks
subscribed pulses and higher rate limits.

No mock data. No synthetic events. Returns [] on API failure.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# ── Load OTX API key ────────────────────────────────────────────────
_CREDS_FILE = Path(__file__).resolve().parent.parent / "credentials.json"
OTX_API_KEY: str = ""

try:
    if _CREDS_FILE.exists():
        import json as _json
        _creds = _json.loads(_CREDS_FILE.read_text(encoding="utf-8"))
        OTX_API_KEY = _creds.get("otx_api_key", "")
        if OTX_API_KEY:
            logger.info("[cyber] OTX API key loaded from credentials.json")
except Exception as _e:
    logger.warning("[cyber] Could not read credentials.json: %s", _e)

if not OTX_API_KEY:
    OTX_API_KEY = os.environ.get("DHRUVA_OTX_API_KEY", "")
    if OTX_API_KEY:
        logger.info("[cyber] OTX API key loaded from env")
    else:
        logger.warning("[cyber] No OTX API key found — cyber layer will be inactive")


# ── Country-code → centroid look-up ─────────────────────────────────
# Used to geo-locate OTX indicators that carry only a country code.
# Covers the most commonly seen source/target countries in threat intel.
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "US": (37.09,  -95.71),  "RU": (61.52,   105.31), "CN": (35.86,   104.19),
    "BR": (-14.24,  -51.93), "DE": (51.17,    10.45),  "IN": (20.59,    78.96),
    "GB": (55.38,   -3.44),  "FR": (46.23,     2.21),  "JP": (36.20,   138.25),
    "KP": (40.34,  127.51),  "IR": (32.43,    53.69),  "UA": (48.38,    31.17),
    "PK": (30.37,   69.35),  "NG": (9.08,      8.68),  "TR": (38.96,    35.24),
    "ID": (-0.79,  113.92),  "NL": (52.09,     5.29),  "AU": (-25.27,  133.78),
    "CA": (56.13,  -106.35), "MX": (23.63,   -102.55), "SG": (1.35,    103.82),
    "KR": (35.91,  127.77),  "VN": (14.06,   108.28),  "BD": (23.68,    90.36),
    "ZA": (-30.56,  22.94),  "EG": (26.82,    30.80),  "AR": (-38.42, -63.62),
    "IT": (41.87,   12.57),  "ES": (40.46,   -3.75),   "PL": (51.92,   19.15),
    "SA": (23.89,   45.08),  "TH": (15.87,  100.99),   "RO": (45.94,   24.97),
    "UA": (48.38,   31.17),  "TW": (23.70,  120.96),   "HK": (22.40,  114.11),
    "IL": (31.05,   34.85),  "AE": (23.42,   53.85),   "SE": (60.13,   18.64),
    "CH": (46.82,    8.23),  "BE": (50.50,    4.47),   "NO": (60.47,    8.47),
    "FI": (61.92,   25.75),  "CZ": (49.82,   15.47),   "HU": (47.16,   19.51),
    "BY": (53.71,   27.95),  "AZ": (40.14,   47.58),   "LB": (33.85,   35.86),
    "SY": (34.80,   38.99),  "YE": (15.55,   48.52),   "IQ": (33.22,   43.68),
    "MM": (21.91,   95.96),  "ET": (9.14,    40.49),   "KE": (-0.02,   37.91),
    "TZ": (-6.37,  34.89),   "GH": (7.95,    -1.02),   "CI": (7.54,   -5.55),
    "MY": (4.21,  108.00),   "PH": (12.88,  121.77),   "LY": (26.34,   17.23),
}

# ── Severity mapping ──────────────────────────────────────────────────
_TLP_SEVERITY = {
    "white": 1, "green": 2, "amber": 3, "red": 4, "": 2,
}

_ATTACK_KEYWORDS = {
    "ransomware": 4, "apt": 4, "zero-day": 5, "zero day": 5, "supply chain": 4,
    "ddos": 3, "phishing": 2, "malware": 3, "trojan": 3, "botnet": 3,
    "c2": 3, "c&c": 3, "command and control": 3, "exploit": 4,
    "data exfil": 4, "exfiltration": 4, "credential": 3, "bruteforce": 2,
    "brute force": 2, "keylog": 3, "backdoor": 4, "rootkit": 4,
    "worm": 3, "cryptominer": 2, "skimmer": 3,
}

OTX_SUBSCRIBED_URL = "https://otx.alienvault.com/api/v1/pulses/subscribed"
OTX_RECENT_URL     = "https://otx.alienvault.com/api/v1/pulses/activity"


class CyberCollector(BaseCollector):
    """Fetches live threat intelligence pulses from AlienVault OTX.

    Each OTX pulse describes a real threat campaign or incident, with:
      - adversary / actor attribution
      - targeted industries and countries
      - malware families
      - indicator types (IP, domain, hash, URL)
      - TLP classification

    This collector surfaces the most recent pulses and geo-locates them
    using country attribution from each pulse's targeted_countries field
    or the indicator's country_code.
    """

    PULSE_LIMIT = 50   # pulses per fetch cycle

    def __init__(self, interval: int = 120):
        super().__init__(name="cyber", interval=interval)
        self._seen_ids: set[str] = set()

    @staticmethod
    def _pulse_severity(pulse: dict) -> int:
        """Derive severity 1-5 from TLP level and attack keywords."""
        tlp = (pulse.get("tlp") or "").lower()
        base = _TLP_SEVERITY.get(tlp, 2)

        # Bump severity based on attack-type keywords in name/description
        name = (pulse.get("name") or "").lower()
        desc = (pulse.get("description") or "").lower()
        combined = f"{name} {desc}"
        for kw, sev in _ATTACK_KEYWORDS.items():
            if kw in combined:
                base = max(base, sev)

        return min(base, 5)

    @staticmethod
    def _classify_attack(pulse: dict) -> str:
        """Return the best human-readable attack classification."""
        tags = [t.lower() for t in (pulse.get("tags") or [])]
        name = (pulse.get("name") or "").lower()
        combined = f"{name} {' '.join(tags)}"

        priority = [
            ("zero-day", "Zero-Day Exploit"),
            ("zero day", "Zero-Day Exploit"),
            ("ransomware", "Ransomware"),
            ("apt", "APT Intrusion"),
            ("supply chain", "Supply Chain Attack"),
            ("data exfil", "Data Exfiltration"),
            ("exfiltration", "Data Exfiltration"),
            ("backdoor", "Backdoor / RAT"),
            ("rootkit", "Rootkit"),
            ("ddos", "DDoS Campaign"),
            ("phishing", "Phishing Campaign"),
            ("credential", "Credential Theft"),
            ("c&c", "C2 Infrastructure"),
            ("c2", "C2 Infrastructure"),
            ("botnet", "Botnet Activity"),
            ("trojan", "Trojan"),
            ("worm", "Worm"),
            ("malware", "Malware Campaign"),
        ]
        for kw, label in priority:
            if kw in combined:
                return label
        return "Threat Intelligence"

    def _geo_locate_pulse(self, pulse: dict) -> tuple[float, float] | None:
        """Return (lat, lon) for the pulse target, or None if unavailable."""
        # 1. Prefer explicit targeted countries
        targeted = pulse.get("targeted_countries") or []
        for country in targeted:
            code = country.strip().upper()
            coords = COUNTRY_CENTROIDS.get(code)
            if coords:
                return coords

        # 2. Try adversary country
        adversary_countries = pulse.get("adversary") and []   # advisory field
        # (OTX adversary is a name string, not a code — not useful for geo)

        # 3. Try industries targeted as a last resort (skip — no geo info)
        return None

    async def collect(self) -> list[dict]:
        """Fetch latest threat pulses from AlienVault OTX."""
        if not OTX_API_KEY:
            logger.warning("[cyber] OTX API key not configured, skipping collection")
            return []

        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=30.0)

        headers = {"X-OTX-API-KEY": OTX_API_KEY}
        params  = {"limit": self.PULSE_LIMIT, "page": 1}

        try:
            resp = await self._http_client.get(
                OTX_SUBSCRIBED_URL, headers=headers, params=params, timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("[cyber] OTX API request failed: %s", e)
            return []

        pulses = data.get("results", [])
        if not pulses:
            logger.warning("[cyber] OTX returned no pulses")
            return []

        events = []
        for pulse in pulses:
            pulse_id = pulse.get("id", "")
            if pulse_id in self._seen_ids:
                continue

            coords = self._geo_locate_pulse(pulse)
            if not coords:
                # Try to find geo from indicators
                for indicator in (pulse.get("indicators") or [])[:20]:
                    cc = (indicator.get("country_code") or "").upper()
                    if cc in COUNTRY_CENTROIDS:
                        coords = COUNTRY_CENTROIDS[cc]
                        break

            if not coords:
                # Skip pulses we can't locate — they'd clutter the globe at 0,0
                logger.debug("[cyber] Pulse %s has no geo info, skipping", pulse_id)
                continue

            lat, lon = coords
            attack_type = self._classify_attack(pulse)
            severity    = self._pulse_severity(pulse)

            # Pulse metadata
            author   = pulse.get("author_name") or "Unknown"
            name     = pulse.get("name") or "Unnamed Threat"
            tlp      = (pulse.get("tlp") or "WHITE").upper()
            tags     = pulse.get("tags") or []
            ioc_count = pulse.get("indicator_count") or len(pulse.get("indicators") or [])
            adversary = pulse.get("adversary") or ""
            malware_families = [
                mf.get("display_name") or mf.get("id", "")
                for mf in (pulse.get("malware_families") or [])
            ]
            targeted_industries = pulse.get("targeted_countries") or []
            modified = pulse.get("modified") or datetime.now(timezone.utc).isoformat()

            # Compose description
            desc_parts = [attack_type]
            if adversary:
                desc_parts.append(f"Actor: {adversary}")
            if malware_families:
                desc_parts.append(f"Malware: {', '.join(malware_families[:3])}")
            if ioc_count:
                desc_parts.append(f"{ioc_count} IOCs")
            desc_parts.append(f"TLP:{tlp}")

            self._seen_ids.add(pulse_id)
            events.append({
                "id": f"cyber-otx-{pulse_id}",
                "type": "cyber",
                "latitude": round(lat, 4),
                "longitude": round(lon, 4),
                "severity": severity,
                "timestamp": modified,
                "source": f"AlienVault OTX — {author}",
                "title": f"{attack_type} — {name[:60]}",
                "description": " · ".join(desc_parts),
                "metadata": {
                    "attack_type": attack_type,
                    "pulse_name": name,
                    "pulse_id": pulse_id,
                    "adversary": adversary,
                    "tlp": tlp,
                    "tags": tags[:10],
                    "ioc_count": ioc_count,
                    "malware_families": malware_families[:5],
                    "targeted_industries": targeted_industries[:5],
                    "author": author,
                    "otx_url": f"https://otx.alienvault.com/pulse/{pulse_id}",
                },
            })

        # Bound the seen cache
        if len(self._seen_ids) > 2000:
            self._seen_ids = set(list(self._seen_ids)[-1000:])

        logger.info("[cyber] OTX returned %d geolocatable threat pulses", len(events))
        return events
