"""Dhruva — Live Satellite Tracker (N2YO API).

Fetches real-time positions for ALL satellite constellations and objects
using the N2YO 'What's up' endpoint. Distributes API calls evenly to avoid
the strict 1000 requests/hour limit.
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta
import httpx

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

N2YO_API_URL = "https://api.n2yo.com/rest/v1/satellite/above/{lat}/{lon}/{alt}/{radius}/{category}/&apiKey={key}"

# ALL 57 N2YO categories
TRACKED_CATEGORIES = {
    18: "Amateur radio", 35: "Beidou Navigation System", 1: "Brightest", 45: "Celestis",
    54: "Chinese Space Station", 32: "CubeSats", 8: "Disaster monitoring", 6: "Earth resources",
    29: "Education", 28: "Engineering", 19: "Experimental", 48: "Flock", 22: "Galileo",
    57: "GeeSAT", 27: "Geodetic", 10: "Geostationary", 50: "GPS Constellation", 20: "GPS Operational",
    17: "Globalstar", 51: "Glonass Constellation", 21: "Glonass Operational", 5: "GOES",
    40: "Gonets", 12: "Gorizont", 11: "Intelsat", 15: "Iridium", 46: "IRNSS", 2: "ISS",
    56: "Kuiper", 49: "Lemur", 30: "Military", 14: "Molniya", 24: "Navy Navigation Satellite",
    4: "NOAA", 43: "O3B Networks", 53: "OneWeb", 16: "Orbcomm", 38: "Parus", 55: "Qianfan",
    47: "QZSS", 31: "Radar Calibration", 13: "Raduga", 25: "Russian LEO Navigation",
    23: "SBAS", 7: "Search & rescue", 26: "Space & Earth Science",
    52: "Starlink", 39: "Strela", 9: "TDRSS", 44: "Tselina",
    42: "Tsikada", 41: "Tsiklon", 34: "TV", 3: "Weather", 37: "Westford Needles", 33: "XM and Sirius",
    36: "Yaogan"
}

# 5 anchor points provide global coverage with a 70-degree search radius.
ANCHOR_POINTS = [
    (80.0, 0.0),       # North Pole Region
    (-80.0, 0.0),      # South Pole Region
    (0.0, 0.0),        # Equator (Africa/Europe)
    (0.0, 120.0),      # Equator (Asia/Pacific)
    (0.0, -120.0)      # Equator (Americas)
]


class SatelliteCollector(BaseCollector):
    """Fetches satellite positions traversing the globe."""

    def __init__(self, interval: int = 60):
        super().__init__(name="satellite", interval=interval)
        
        # Build master list of (category_id, lat, lon) to cycle through
        self._combinations = []
        for cat_id in TRACKED_CATEGORIES.keys():
            for lat, lon in ANCHOR_POINTS:
                self._combinations.append((cat_id, lat, lon))
                
        self._combo_index = 0
        self._satellite_cache: dict[str, dict] = {} # satid -> OsintEvent raw dict
        self._quota_exhausted_until: datetime = None

    def _get_api_key(self) -> str:
        try:
            from backend.config import settings
            return getattr(settings, "n2yo_api_key", "") or ""
        except Exception:
            return ""

    async def _fetch_category_at_anchor(self, key: str, cat_id: int, lat: float, lon: float) -> list[dict]:
        """Fetch a specific category of satellites above a specific coordinate."""
        url = N2YO_API_URL.format(lat=lat, lon=lon, alt=0, radius=70, category=cat_id, key=key)
        
        try:
            resp = await self._http_client.get(url, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            
            if "above" in data and data["above"]:
                return data["above"]
            if "error" in data:
                err = data["error"]
                if "exceeded" in err.lower() or "transactions allowed" in err.lower():
                    logger.warning("[satellite] N2YO Hourly Quota Exceeded. Suspending calls.")
                    return "RATE_LIMIT"
                logger.debug("[satellite] API msg for category %s: %s", cat_id, err)
            return []
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("[satellite] N2YO Rate limit exceeded fetching category %s", cat_id)
            else:
                logger.error("[satellite] HTTP %s fetching category %s: %s", e.response.status_code, cat_id, e)
            return []
        except Exception as e:
            logger.error("[satellite] Request failed fetching category %s: %s", cat_id, e)
            return []

    async def collect(self) -> list[dict]:
        """Collect live satellite positions with round-robin globally distributed payload limits."""
        # 1. Check if we are currently in a rate-limit penalty box
        if self._quota_exhausted_until:
            if datetime.now(timezone.utc) < self._quota_exhausted_until:
                # Still exhausted, return cached valid events but don't fetch
                return self._purge_and_get_cache()
            else:
                self._quota_exhausted_until = None
                logger.info("[satellite] N2YO API Quota penalty lifted. Resuming sweeps.")
        
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("[satellite] Cannot collect: N2YO API key missing.")
            return []

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)

        # We have 285 total combinations (57 cats * 5 anchors).
        # Making 14 requests per minute = 840 requests/hour (comfortably under the 1000/hour limit).
        # It takes ~20 minutes to complete a full global sweep but updates seamlessly in batches.
        
        batch = []
        for _ in range(14):
            batch.append(self._combinations[self._combo_index])
            self._combo_index = (self._combo_index + 1) % len(self._combinations)
            
        tasks = []
        for cat_id, lat, lon in batch:
            tasks.append(self._fetch_category_at_anchor(api_key, cat_id, lat, lon))
                
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        
        new_updates = 0
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error("[satellite] Async fetch task failed: %s", res)
                continue
            if res == "RATE_LIMIT":
                # API limit hit. Suspend all calls for 60 minutes.
                self._quota_exhausted_until = datetime.now(timezone.utc) + timedelta(minutes=60)
                return self._purge_and_get_cache()
                
            cat_id = batch[i][0]
            cat_name = TRACKED_CATEGORIES.get(cat_id, "Unknown Type")
            
            for sat in res:
                satid = str(sat.get("satid"))
                satlat = sat.get("satlat")
                satlng = sat.get("satlng")
                satalt = sat.get("satalt")
                name = sat.get("satname", f"Unknown Sat {satid}")
                
                if satlat is None or satlng is None:
                    continue
                    
                severity = 2
                if cat_id in (30, 31): # Military / Radar Cal
                    severity = 3
                elif cat_id in (52, 53, 56): # Starlink, OneWeb, Kuiper
                    severity = 1
                
                self._satellite_cache[satid] = {
                    "id": f"sat-{satid}",
                    "type": "satellite",
                    "latitude": round(float(satlat), 4),
                    "longitude": round(float(satlng), 4),
                    "severity": severity,
                    "timestamp": now_iso,  # Mark when we last saw it
                    "source": "N2YO API",
                    "title": f"{cat_name} — {name}",
                    "description": f"Altitude: {satalt} km · Launch: {sat.get('launchDate', 'Unknown')}",
                    "metadata": {
                        "satid": satid,
                        "satname": name,
                        "category": cat_name,
                        "altitude_km": satalt,
                        "designator": sat.get("intDesignator", ""),
                        "launch_date": sat.get("launchDate", "")
                    }
                }
                new_updates += 1

        logger.info("[satellite] N2YO sweep yielded %d new updates. Active cache: %d tracking.", new_updates, len(self._satellite_cache))
        return self._purge_and_get_cache()

    def _purge_and_get_cache(self) -> list[dict]:
        """Removes satellites not seen in 25 minutes from the cache and returns the active list."""
        valid_events = []
        now_dt = datetime.now(timezone.utc)
        stale_threshold = now_dt - timedelta(minutes=25)
        
        for satid, event in list(self._satellite_cache.items()):
            try:
                fetched_dt = datetime.fromisoformat(event["timestamp"])
                if fetched_dt < stale_threshold:
                    del self._satellite_cache[satid]
                else:
                    valid_events.append(event)
            except Exception:
                del self._satellite_cache[satid]
                
        return valid_events
