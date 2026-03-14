import asyncio
import logging
import json
from datetime import datetime, timezone
import aiohttp
import httpx
import traceback
import re
from backend.config import settings

logger = logging.getLogger("dhruva.pizza")

# In-memory store
pizza_data: dict = {
    "level": 1,
    "summary": "NOMINAL. Standard operations relative to the current environment.",
    "updatedAt": datetime.now(timezone.utc).isoformat()
}

_fetch_lock = asyncio.Lock()

async def fetch_pizza_index():
    """Fetch the latest Pentagon Pizza Meter OSINT using Gemini."""
    global pizza_data
    if not getattr(settings, "gemini_api_key", None):
        logger.warning("[pizza] Gemini API key not configured.")
        return

    async with _fetch_lock:
        logger.info("[pizza] Querying Gemini for Live Pentagon Pizza Index...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}"
        
        current_date_time = datetime.now(timezone.utc).strftime('%B %d, %Y %H:%M UTC')
        prompt = (
            f"CRITICAL INSTRUCTION: You MUST use the Google Search tool to find live OSINT data for today, {current_date_time}. "
            "Search for current news, Twitter/X reports, or 'Google Maps Popular Times' regarding local pizza chains near the Pentagon and White House. "
            "Specifically check: 'Papa John's Pizza Arlington', 'Domino's near Pentagon', 'Pizza Hut Washington DC', or general 'Late night pizza Pentagon'. "
            "The 'Pentagon Pizza Meter' relies on ACTUAL, LITERAL foot-traffic and delivery busyness at these local pizza joints to determine if defense officials are working late unexpectedly. "
            "If they are open late and busier than usual right now, the level increases. If it's normal business hours and normal traffic, it remains low. "
            "Do NOT infer the Pizza Meter level from generalized global military news. Base it SPECIFICALLY on literal OSINT regarding local pizza traffic in Arlington/DC. "
            "Return a pure JSON object containing exactly: "
            "'level' (integer 1-5), "
            "'summary' (string, a brief 1 sentence explanation of why it is at this level based STRICTLY on current literal pizza chatter or food traffic/store hours). "
            "Do not include ```json markdown."
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.2}
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                
                candidates = data.get("candidates", [])
                if not candidates:
                    return
                    
                text_response = candidates[0].get("content", {}).get("parts", [])[0].get("text", "")
                text_response = re.sub(r'```json\n|\n```|```', '', text_response).strip()
                
                result = json.loads(text_response)
                
                level = int(result.get("level", 1))
                # Bound between 1 and 5
                level = max(1, min(level, 5))
                summary = result.get("summary", "No significant Pizza OSINT detected. Using environment baseline.")
                
                pizza_data = {
                    "level": level,
                    "summary": summary,
                    "updatedAt": datetime.now(timezone.utc).isoformat()
                }
                logger.info(f"[pizza] Updated Pizza Index: Level {level}")
                
        except Exception as e:
            logger.error(f"[pizza] Fetch error: {e}")

async def pizza_data_loop(interval: int = 3600):
    """Background loop: fetch Pizza Index every `interval` seconds."""
    logger.info(f"[pizza] Starting Pentagon Pizza fetcher (interval={interval}s)")
    while True:
        try:
            await fetch_pizza_index()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[pizza] Loop error: {e}")
        await asyncio.sleep(interval)

def get_pizza_data() -> dict:
    """Return the latest Pizza Index snapshot."""
    return pizza_data
