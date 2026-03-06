"""Dhruva — AI Service using Ollama."""

import httpx
import logging
import json
import asyncio
import time
from backend.config import settings

logger = logging.getLogger("dhruva.ai")

class AIService:
    def __init__(self):
        self.base_url = settings.ollama_url
        self.model = settings.ollama_model
        # Use single shared client for efficiency
        self._http_client = None
        self._queue = None
        self._worker_task = None
        
    def _get_client(self):
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=180.0)
        return self._http_client

    def _start_worker(self):
        if self._queue is None:
            self._queue = asyncio.PriorityQueue()
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self):
        while True:
            priority, timestamp, future, coro = await self._queue.get()
            try:
                logger.info(f"[ai_service] Resolving AI queue task with Priority {priority}")
                # Execute inference sequentially to avoid memory thrashing on GPU
                result = await coro
                if not future.done():
                    future.set_result(result)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)
            finally:
                self._queue.task_done()

    async def _enqueue_inference(self, priority: int, coro):
        self._start_worker()
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._queue.put((priority, time.monotonic(), future, coro))
        return await future

    async def _ask_ollama(self, prompt: str, system: str = "You are a military intelligence OSINT analyst.", json_mode: bool = False) -> str:
        """Execute inference via local Ollama endpoint."""
        url = f"{self.base_url}/api/generate"
        
        system_content = f"{system}\nYou MUST output strictly valid JSON only." if json_mode else system
        full_prompt = f"{system_content}\n\n{prompt}"
        
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 500,
            }
        }
        
        if json_mode:
            payload["format"] = "json"
            
        try:
            client = self._get_client()
            resp = await client.post(url, json=payload, timeout=180.0)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
                
        except httpx.HTTPStatusError as e:
            logger.error("[ai_service] Ollama HTTP Error %s: %s", e.response.status_code, e.response.text)
            return ""
        except Exception as e:
            logger.exception("[ai_service] Ollama inference failed:")
            return ""

    async def verify_and_extract_event(self, title: str, texts: list[str], current_time: str, event_type: str = "conflict") -> dict:
        """
        Takes raw event details and returns a structured extraction including:
        - verification_status (e.g. YES/NO)
        - human_readable_time
        - confidence_score (0-100)
        - reasoning
        """
        priority = 4
        if event_type == "naval":
            task_type = "Naval Deployment"
            priority = 1
            example = '{"verified": "YES", "time": "Tuesday, 08:00 UTC", "confidence_score": 90, "reasoning": "Reports indicate USS Nimitz deployed.", "latitude": 35.0, "longitude": 18.0, "location_name": "Mediterranean Sea"}'
            rules = "Determine if this represents a real-world, current Naval Deployment of a carrier group or submarine. Extract the precise coordinates of the deployment."
        elif event_type == "earthquake":
            task_type = "Earthquake"
            priority = 4 # Currently earthquake AI verification is off, but just in case
            example = '{"verified": "YES", "time": "Latest timestamp", "confidence_score": 95, "reasoning": "Multiple sources report a 6.8 magnitude earthquake.", "latitude": 34.0, "longitude": -118.0, "location_name": "Los Angeles"}'
            rules = "Determine if this is a credible, real-world earthquake event. Extract the precise coordinates of the epicenter."
        elif event_type == "notam":
            task_type = "Airspace Closure / Restriction"
            priority = 3
            example = '{"verified": "YES", "time": "Latest timestamp", "confidence_score": 85, "reasoning": "Airspace closed due to military exercises.", "latitude": 50.0, "longitude": 30.0, "location_name": "Kyiv, Ukraine"}'
            rules = "Determine if this represents a real-world airspace closure, NO-FLY zone, or significant flight restriction (NOTAM). Extract the precise coordinates of the restricted airspace."
        else: # conflict / ucdp
            task_type = "Conflict/OSINT Event"
            priority = 2
            example = '{"verified": "YES", "time": "Latest timestamp", "confidence_score": 85, "reasoning": "Multiple sources confirm the conflict in the specific region.", "latitude": 31.5, "longitude": 34.4, "location_name": "Gaza Strip"}'
            rules = "Determine if this is a credible, real-world conflict, military strike, unrest, or protest event. Extract the precise coordinates of the event."

        prompt = (
            f"Title: '{title}'\n"
            f"Report Excerpts: {texts}\n"
            f"Current Time: {current_time}\n\n"
            f"Event Classification: {task_type}\n"
            f"Task: {rules}\n"
            "CRITICAL RULES:\n"
            "1. Output exactly a JSON dict with keys: 'verified' (YES/NO), 'time' (string), 'confidence_score' (int 0-100), 'reasoning' (string), 'latitude' (float or null), 'longitude' (float or null), 'location_name' (string or empty).\n"
            "2. Base your reasoning ONLY on the provided report excerpts.\n"
            "3. If the excerpts strongly imply the event occurred, output YES. Be lenient for breaking news.\n"
            "4. Provide realistic decimal latitude and longitude coordinates based on the real-world location mentioned in the text. If you cannot deduce the exact city, provide the coordinates of the country or region.\n"
            f"Example: {example}"
        )
        
        response_text = await self._enqueue_inference(
            priority=priority,
            coro=self._ask_ollama(prompt, json_mode=True)
        )
        
        default_resp = {
            "verified": "NO",
            "time": current_time,
            "confidence_score": 0,
            "reasoning": "Failed to verify via Ollama."
        }
        
        if not response_text:
            return default_resp
            
        try:
            data = json.loads(response_text)
            return {
                "verified": data.get("verified", "NO").upper(),
                "time": data.get("time", current_time),
                "confidence_score": data.get("confidence_score", 0),
                "reasoning": data.get("reasoning", "No reasoning provided."),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "location_name": data.get("location_name")
            }
        except json.JSONDecodeError as e:
            logger.error("[ai_service] Failed to parse Ollama JSON output: %s", e)
            return default_resp

    async def deduplicate_events(self, source_a: dict, source_b: dict) -> bool:
        """
        Intelligently compare two event descriptions to see if they refer to the exact same incident.
        Returns True if they are the same event, False otherwise.
        """
        desc_a = source_a.get("description", "")
        desc_b = source_b.get("description", "")
        
        prompt = (
            f"Event A description: '{desc_a}'\n"
            f"Event B description: '{desc_b}'\n\n"
            "Task: Are these two descriptions referring to the exact same real-world incident?\n"
            "Output strictly a JSON dict with key 'is_duplicate' set to true or false."
        )
        
        response_text = await self._enqueue_inference(
            priority=1, # Deduplication is fast and blocks loops, high priority
            coro=self._ask_ollama(prompt, system="You are an expert at deduplicating news events.", json_mode=True)
        )
        
        if not response_text:
            return False
            
        try:
            data = json.loads(response_text)
            return data.get("is_duplicate", False)
        except json.JSONDecodeError:
            return False

# Export a default instance
ai_service = AIService()
