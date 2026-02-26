"""Dhruva — Earthquake Collector (USGS GeoJSON Feed)."""

from datetime import datetime, timezone
from collectors.base_collector import BaseCollector


class EarthquakeCollector(BaseCollector):
    """Fetches real-time earthquake data from USGS."""

    API_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"

    def __init__(self, interval: int = 60):
        super().__init__(name="earthquake", interval=interval)
        self._seen_ids: set = set()

    def _magnitude_to_severity(self, mag: float) -> int:
        if mag >= 7.0:
            return 5
        elif mag >= 5.0:
            return 4
        elif mag >= 4.0:
            return 3
        elif mag >= 2.5:
            return 2
        return 1

    async def collect(self) -> list[dict]:
        data = await self.fetch_json(self.API_URL)
        events = []

        for feature in data.get("features", []):
            fid = feature["id"]
            if fid in self._seen_ids:
                continue
            self._seen_ids.add(fid)

            props = feature["properties"]
            coords = feature["geometry"]["coordinates"]  # [lon, lat, depth]
            mag = props.get("mag", 0) or 0

            events.append({
                "id": f"eq-{fid}",
                "type": "earthquake",
                "latitude": coords[1],
                "longitude": coords[0],
                "severity": self._magnitude_to_severity(mag),
                "timestamp": datetime.fromtimestamp(
                    props["time"] / 1000, tz=timezone.utc
                ).isoformat(),
                "source": "USGS",
                "title": props.get("title", f"M{mag} Earthquake"),
                "description": f"Magnitude {mag} at depth {coords[2]}km",
                "metadata": {
                    "magnitude": mag,
                    "depth_km": coords[2],
                    "felt": props.get("felt"),
                    "tsunami": props.get("tsunami", 0),
                    "url": props.get("url", ""),
                },
            })

        # Keep seen IDs bounded
        if len(self._seen_ids) > 5000:
            self._seen_ids = set(list(self._seen_ids)[-2000:])

        return events
