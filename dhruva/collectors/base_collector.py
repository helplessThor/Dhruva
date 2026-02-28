"""Dhruva — Abstract Base Collector."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger("dhruva.collector")


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
        logger.info("[%s] Collector started (interval=%ds)", self.name, self.interval)

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

    async def ask_groq(self, prompt: str, system: str = "You are a military intelligence OSINT analyst.", json_mode: bool = False) -> str:
        """Execute high-speed zero-shot inference via Groq to verify OSINT. Falls back if rate-limited."""
        from backend.config import settings
        if not settings.groq_api_key:
            return ""
            
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json"
        }
        
        # Priority list of models to cycle through upon rate limiting
        models = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "gemma2-9b-it"
        ]
        
        system_content = f"{system}\nYou MUST output strictly valid JSON only." if json_mode else system
        
        for model in models:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.0,
                "max_tokens": 500,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            
            try:
                resp = await self._http_client.post(url, headers=headers, json=payload, timeout=10.0)
                
                # Check for 429 Rate Limit
                if resp.status_code == 429:
                    logger.warning("[%s] Groq 429 Rate Limit on model %s, falling back to next...", self.name, model)
                    continue
                    
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    logger.warning("[%s] Groq 429 Rate Limit on model %s, falling back to next...", self.name, model)
                    continue
                logger.error("[%s] Groq API HTTP error %s: %s", self.name, e.response.status_code, e.response.text)
                return ""
            except Exception as e:
                logger.error("[%s] Groq API inference failed on model %s: %s", self.name, model, e)
                # Network or timeout errors might be transient, try the next model
                continue
                
        logger.error("[%s] All Groq fallback models exhausted due to rate limits or errors.", self.name)
        return ""
