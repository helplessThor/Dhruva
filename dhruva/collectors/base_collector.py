"""Dhruva — Abstract Base Collector."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
import random

import httpx

logger = logging.getLogger("dhruva.collector")

# AI functions have moved to backend.ai_service


class BaseCollector(ABC):
    """Base class for all OSINT data collectors."""

    def __init__(self, name: str, interval: int = 60):
        self.name = name
        self.interval = interval
        self._running = False
        self._http_client: Optional[httpx.AsyncClient] = None
        self._last_fetch: Optional[datetime] = None

    async def start(self):
        """Start the collector loop."""
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30.0)
        
        # Jitter: Randomly stagger the start of each collector by 5 to 35 seconds
        # This prevents 4 collectors from waking up simultaneously and crashing Groq API
        jitter = random.uniform(5, 35)
        logger.info("[%s] Collector starting in %.1fs (interval=%ds)", self.name, jitter, self.interval)
        await asyncio.sleep(jitter)

        logger.info("[%s] Collector loop active", self.name)
        while self._running:
            try:
                events = await self.collect()
                self._last_fetch = datetime.utcnow()
                if events:
                    logger.info("[%s] Collected %d events", self.name, len(events))
                    yield events
                else:
                    logger.debug("[%s] No new events", self.name)
                    yield []
            except Exception as e:
                logger.error("[%s] Collection error: %s", self.name, e)
                yield []

            await asyncio.sleep(self.interval)

    async def stop(self):
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
        logger.info("[%s] Collector stopped", self.name)

    # Native Offline Geolocation Cache
    _GEO_CACHE = {}

    async def _async_geocode(self, location_text: str) -> tuple[float, float] | None:
        """Smart offline geocoding using Nominatim (OpenStreetMap) to avoid AI dependencies."""
        if not location_text or len(location_text) < 3:
            return None
            
        location_text = location_text.strip()
        if location_text in self._GEO_CACHE:
            return self._GEO_CACHE[location_text]
            
        try:
            if not self._http_client:
                import httpx
                self._http_client = httpx.AsyncClient(timeout=30.0)
                
            resp = await self._http_client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": location_text, "format": "json", "limit": 1},
                headers={"User-Agent": "WorldViewOSINT/1.0"},
                timeout=10.0
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    self._GEO_CACHE[location_text] = (lat, lon)
                    import asyncio
                    await asyncio.sleep(1.0) # Honor Nominatim 1 req/sec policy
                    return lat, lon
        except Exception as e:
            logger.debug(f"Geocoding failed for '{location_text}': {e}")
            
        self._GEO_CACHE[location_text] = None
        return None

    @abstractmethod
    async def collect(self) -> list[dict]:
        """Fetch and normalize events from the data source. Returns list of OsintEvent dicts."""
        ...

    async def fetch_json(self, url: str, params: dict = None) -> dict:
        """Helper to fetch JSON from a URL."""
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        resp = await self._http_client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    # `ask_groq` has been removed in favor of `backend.ai_service.py`
