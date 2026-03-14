import asyncio
import logging
import json
from datetime import datetime, timezone
import aiohttp
import uuid
import re
import traceback

from collectors.base_collector import BaseCollector
from backend.models import OsintEvent
from fusion_engine.global_countries import GLOBAL_COUNTRIES

logger = logging.getLogger("dhruva.collectors.war")

class WarCollector(BaseCollector):
    """
    Uses Gemini API to identify major active wars and map them to their 
    participating countries.
    Runs globally every 4 hours.
    """
    
    def __init__(self, interval: int = 14400):  # 4 hours
        super().__init__(name="war", interval=interval)
        from backend.config import settings
        self.api_key = settings.gemini_api_key
        if not self.api_key:
            logger.warning("[war] Gemini API key (Dhruva API) not configured. War collection disabled.")

    def _get_coords_for_iso(self, iso2: str):
        for data in GLOBAL_COUNTRIES.values():
            if data["iso2"] == iso2:
                return data["lat"], data["lon"]
        return 0.0, 0.0

    async def collect(self) -> list[dict]:
        if not self.api_key:
            logger.info("[war] Skipping war collection as API key is missing.")
            return []

        logger.info("[war] Fetching ongoing armed conflicts from Gemini API...")
        events = []
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
        
        current_date = datetime.now(timezone.utc).strftime('%B %Y')
        prompt = (
            f"CRITICAL INSTRUCTION: You MUST use the Google Search tool to find live data for exactly today, {current_date}. Do not rely on your training data. "
            "Get a comprehensive list of ALL currently active armed conflicts globally as of right now. "
            "You MUST exclude non-sovereign insurgencies, local rebel groups, cartels, gangs, protests, and civil unrest. "
            "Return a pure JSON array format where each object has: "
            "'conflict_name' (string), "
            "'severity' (integer between 1 and 5, where 1 is a minor skirmish and 5 is a major theater war), "
            "'iso2_codes' (list of participating countries ISO2 letters. ONLY include countries with active, official military boots-on-the-ground or direct kinetic involvement. Do NOT include countries that are merely supplying weapons, funding, or political support [e.g. exclude NATO suppliers from the Ukraine war unless they have formal troops deployed]), "
            "'summary' (string, a detailed 2-3 sentence explanation of the conflict, current status, and cause). "
            "Do not include any markdown formatting like ```json, just output the raw JSON array."
        )

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {
                "temperature": 0.1
            }
        }

        try:
            if not self._http_client:
                import httpx
                self._http_client = httpx.AsyncClient(timeout=120.0)
                
            resp = await self._http_client.post(url, json=payload, timeout=120.0)
            if resp.status_code != 200:
                logger.error(f"[war] Gemini API error: {resp.status_code} - {resp.text}")
                return []
                
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error("[war] No candidates returned from Gemini.")
                return []
                
            text_response = candidates[0].get("content", {}).get("parts", [])[0].get("text", "")
            
            # Use regex to strip any possible markdown just in case 
            text_response = re.sub(r'```json\n|\n```|```', '', text_response).strip()
            
            wars = json.loads(text_response)
            
            deduped = {}
            for war in wars:
                conflict_name = war.get("conflict_name", "Unknown Conflict")
                severity = int(war.get("severity", 4))
                summary = war.get("summary", "")
                iso_codes = war.get("iso2_codes", [])
                
                for iso2 in iso_codes:
                    if not iso2 or len(iso2) != 2:
                        continue
                        
                    iso2 = iso2.upper()
                    lat, lon = self._get_coords_for_iso(iso2)
                    
                    event = OsintEvent(
                        id=f"war_{iso2}_{uuid.uuid4().hex[:8]}",
                        type="war",
                        latitude=lat,
                        longitude=lon,
                        severity=severity,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        source="AI (Gemini) - Live Conflicts",
                        title=f"Major War: {conflict_name}",
                        description=f"{summary} Severity: {severity}/5.",
                        metadata={"country_iso2": iso2, "conflict_zone": "Multiple", "base_severity": severity}
                    )
                    
                    event_dict = event.model_dump(mode="json")
                    
                    if iso2 not in deduped or event_dict["severity"] > deduped[iso2]["severity"]:
                        deduped[iso2] = event_dict
                        
            final_events = list(deduped.values())
            logger.info(f"[war] Found {len(final_events)} active national war zones via Gemini.")
            return final_events

        except json.JSONDecodeError as je:
            logger.error(f"[war] Failed to parse JSON from Gemini. Error: {je} Raw Text: {text_response}")
            return []
        except Exception as e:
            logger.error(f"[war] Failed to fetch ongoing wars via Gemini: {traceback.format_exc()}")
            return []
