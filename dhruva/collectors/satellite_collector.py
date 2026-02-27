"""Dhruva — Live Satellite Tracker (N2YO API).

Fetches real-time positions for key satellite constellations and objects
(e.g., Starlink, Military, GPS, ISS) using the N2YO 'What's up' endpoint.
"""

import logging
import asyncio
from datetime import datetime, timezone
import httpx

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

N2YO_API_URL = "https://api.n2yo.com/rest/v1/satellite/above/{lat}/{lon}/{alt}/{radius}/{category}/&apiKey={key}"

# Satellite categories to track
# 52: Starlink
# 30: Military
# 20: GPS
# 10: Geostationary (Comms/Regional, e.g. IRNSS, GSAT)
# 3: Weather (e.g. INSAT, NOAA, Meteosat)
# 15: Iridium (Comms)
# 27: Earth Resources (Polar Orbiting)
TRACKED_CATEGORIES = {
    52: "Starlink",
    30: "Military",
    20: "GPS",
    10: "Geostationary (Comms)",
    3: "Weather",
    15: "Iridium",
    27: "Earth Observation"
}

# 5 anchor points provide global coverage with a 70-degree search radius:
# - North/South poles cover all longitudes in their hemispheres.
# - 3 equatorial points overlap to cover the equatorial band.
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
        # 60 seconds is reasonable for satellite sweeps.
        super().__init__(name="satellite", interval=interval)
        self._seen_satids: set[str] = set()
        self._anchor_index = 0

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
            
            # The API returns an 'info' dict and an 'above' list
            if "above" in data and data["above"]:
                return data["above"]
            if "error" in data:
                logger.error("[satellite] API Error for category %s: %s", cat_id, data["error"])
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
        """Collect live satellite positions."""
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("[satellite] Cannot collect: N2YO API key missing.")
            return []

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)

        # To avoid blasting the N2YO API and hitting rate limits (1000/hour),
        # we rotate through our 5 anchor points. One anchor per cycle (60s).
        # This results in 7 requests per minute (420/hour), safely under the limit.
        current_anchor = ANCHOR_POINTS[self._anchor_index]
        self._anchor_index = (self._anchor_index + 1) % len(ANCHOR_POINTS)
        
        all_sats = []
        seen_in_cycle = set()
        
        tasks = []
        for cat_id in TRACKED_CATEGORIES.keys():
            lat, lon = current_anchor 
            tasks.append(self._fetch_category_at_anchor(api_key, cat_id, lat, lon))
                
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error("[satellite] Async fetch task failed: %s", res)
                continue
                
            cat_id = list(TRACKED_CATEGORIES.keys())[i]
            cat_name = TRACKED_CATEGORIES[cat_id]
            
            for sat in res:
                satid = str(sat.get("satid"))
                
                # Deduplicate if we saw this sat in a different anchor zone this cycle
                if satid in seen_in_cycle:
                    continue
                seen_in_cycle.add(satid)
                
                satlat = sat.get("satlat")
                satlng = sat.get("satlng")
                satalt = sat.get("satalt")
                name = sat.get("satname", f"Unknown Sat {satid}")
                
                if satlat is None or satlng is None:
                    continue
                    
                # Calculate an arbitrary severity to make military/starlink visually distinct
                # if needed, otherwise stick to 2.
                severity = 2
                if cat_id == 30: # Military
                    severity = 3
                elif cat_id == 52: # Starlink
                    severity = 1
                
                all_sats.append({
                    "id": f"sat-{satid}",
                    "type": "satellite",
                    "latitude": round(float(satlat), 4),
                    "longitude": round(float(satlng), 4),
                    "severity": severity,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "N2YO API",
                    "title": f"{cat_name} Satellite — {name}",
                    "description": f"Altitude: {satalt} km · Launch: {sat.get('launchDate', 'Unknown')}",
                    "metadata": {
                        "satid": satid,
                        "satname": name,
                        "category": cat_name,
                        "altitude_km": satalt,
                        "designator": sat.get("intDesignator", ""),
                        "launch_date": sat.get("launchDate", "")
                    }
                })

        # Update historical cache bounds (kept for parity with base collector patterns)
        self._seen_satids = set(list(seen_in_cycle)[:5000])

        logger.info("[satellite] N2YO fetched %d live satellite positions", len(all_sats))
        return all_sats
