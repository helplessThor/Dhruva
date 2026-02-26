"""Dhruva — Internet Outage Collector (NetBlocks-style Mock)."""

import random
from datetime import datetime, timezone
from collectors.base_collector import BaseCollector


class OutageCollector(BaseCollector):
    """Generates internet outage/disruption data.
    Can be extended to monitor real NetBlocks / IODA feeds."""

    def __init__(self, interval: int = 120):
        super().__init__(name="outage", interval=interval)

    async def collect(self) -> list[dict]:
        outage_scenarios = [
            {"country": "Iran", "lat": 35.7, "lon": 51.4, "isp": "TIC", "prob": 0.4},
            {"country": "Russia", "lat": 55.8, "lon": 37.6, "isp": "Rostelecom", "prob": 0.3},
            {"country": "China", "lat": 39.9, "lon": 116.4, "isp": "China Telecom", "prob": 0.2},
            {"country": "India", "lat": 28.6, "lon": 77.2, "isp": "BSNL", "prob": 0.3},
            {"country": "Ethiopia", "lat": 9.0, "lon": 38.7, "isp": "Ethio Telecom", "prob": 0.3},
            {"country": "Myanmar", "lat": 16.9, "lon": 96.2, "isp": "MPT", "prob": 0.4},
            {"country": "Cuba", "lat": 23.1, "lon": -82.4, "isp": "ETECSA", "prob": 0.3},
            {"country": "Venezuela", "lat": 10.5, "lon": -66.9, "isp": "CANTV", "prob": 0.3},
            {"country": "Pakistan", "lat": 33.7, "lon": 73.0, "isp": "PTCL", "prob": 0.4},
            {"country": "Nigeria", "lat": 6.5, "lon": 3.4, "isp": "MTN Nigeria", "prob": 0.2},
        ]

        events = []
        for scenario in outage_scenarios:
            if random.random() < scenario["prob"]:
                drop_pct = random.randint(20, 95)
                severity = 5 if drop_pct > 80 else 4 if drop_pct > 60 else 3 if drop_pct > 40 else 2

                events.append({
                    "id": f"outage-{random.randint(100000, 999999)}",
                    "type": "outage",
                    "latitude": scenario["lat"] + random.uniform(-1, 1),
                    "longitude": scenario["lon"] + random.uniform(-1, 1),
                    "severity": severity,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "NetBlocks",
                    "title": f"Internet Disruption — {scenario['country']}",
                    "description": f"{scenario['isp']}: {drop_pct}% traffic drop detected in {scenario['country']}",
                    "metadata": {
                        "country": scenario["country"],
                        "isp": scenario["isp"],
                        "traffic_drop_pct": drop_pct,
                    },
                })
        return events
