"""Dhruva — Global Economic Index Collector."""

import random
from datetime import datetime, timezone
from collectors.base_collector import BaseCollector


class EconomicCollector(BaseCollector):
    """Generates economic indicator data for major financial centers.
    Can be extended to pull from Yahoo Finance, Alpha Vantage, etc."""

    def __init__(self, interval: int = 300):
        super().__init__(name="economic", interval=interval)

    async def collect(self) -> list[dict]:
        markets = [
            {"name": "NYSE", "index": "S&P 500", "lat": 40.71, "lon": -74.01, "base": 5200},
            {"name": "NASDAQ", "index": "NASDAQ Composite", "lat": 40.76, "lon": -73.98, "base": 16500},
            {"name": "LSE", "index": "FTSE 100", "lat": 51.51, "lon": -0.09, "base": 7800},
            {"name": "TSE", "index": "Nikkei 225", "lat": 35.68, "lon": 139.77, "base": 38000},
            {"name": "SSE", "index": "Shanghai Composite", "lat": 31.23, "lon": 121.47, "base": 3100},
            {"name": "BSE", "index": "SENSEX", "lat": 18.93, "lon": 72.83, "base": 73000},
            {"name": "HKEX", "index": "Hang Seng", "lat": 22.29, "lon": 114.17, "base": 17000},
            {"name": "Euronext", "index": "CAC 40", "lat": 48.87, "lon": 2.34, "base": 7900},
            {"name": "XETRA", "index": "DAX", "lat": 50.11, "lon": 8.68, "base": 17500},
            {"name": "ASX", "index": "ASX 200", "lat": -33.87, "lon": 151.21, "base": 7700},
        ]

        events = []
        for market in markets:
            change_pct = round(random.uniform(-3.5, 3.5), 2)
            value = round(market["base"] * (1 + change_pct / 100), 2)

            # Severity based on absolute change
            abs_change = abs(change_pct)
            severity = 5 if abs_change > 3 else 4 if abs_change > 2 else 3 if abs_change > 1 else 2 if abs_change > 0.5 else 1

            direction = "▲" if change_pct > 0 else "▼"
            color = "green" if change_pct > 0 else "red"

            events.append({
                "id": f"econ-{market['name'].lower()}-{random.randint(1000, 9999)}",
                "type": "economic",
                "latitude": market["lat"],
                "longitude": market["lon"],
                "severity": severity,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": market["name"],
                "title": f"{market['index']} {direction} {abs(change_pct)}%",
                "description": f"{market['index']}: {value:,.2f} ({direction}{abs(change_pct)}%)",
                "metadata": {
                    "market": market["name"],
                    "index_name": market["index"],
                    "value": value,
                    "change_pct": change_pct,
                    "direction": "up" if change_pct > 0 else "down",
                },
            })
        return events
