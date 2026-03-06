"""Dhruva — OSINT NOTAM / Airspace Closure Scraper.

Scrapes live news/OSINT RSS feeds to detect real-time No-Fly Zones, Airspace Closures, 
and military flight restrictions to predict conflict zones.
"""

import logging
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import asyncio
import re

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# High-conviction keywords for Airspace Closures
NOTAM_KEYWORDS = [
    "airspace clos", "airport clos", "no-fly", "no fly", "flights suspend",
    "flights grounded", "flights halted", "flights cancel", "airspace restrict", 
    "flight restrict", "notam", "military drill", "missile test", "civil aviation",
    "flights divert", "danger zone", "prohibited airspace"
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "https://www.bing.com/news/search?q={query}&format=rss",
    "https://news.search.yahoo.com/rss?p={query}",
    "https://www.bing.com/search?q={query}+(site:twitter.com OR site:x.com OR site:reuters.com OR site:apnews.com)&format=rss",
]

class NotamCollector(BaseCollector):
    """Scrapes OSINT sources for Airspace Closures."""

    FRESHNESS_HOURS = 24

    def __init__(self, interval: int = 7200):
        super().__init__(name="notam", interval=30)
        self._last_osint_scrape = None
        self._cached_osint_events = []
        self.OSINT_THROTTLE_SECONDS = interval

    async def collect(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        should_run_osint = (
            self._last_osint_scrape is None or 
            (now - self._last_osint_scrape).total_seconds() >= self.OSINT_THROTTLE_SECONDS
        )
        
        if should_run_osint:
            logger.info("[notam] OSINT throttle elapsed. Running live RSS scrape...")
            await self._scrape_osint_rss()
            self._last_osint_scrape = now
            
        self._cached_osint_events = [e for e in self._cached_osint_events if not e.get("_rejected")]
        return self._cached_osint_events

    async def _scrape_osint_rss(self) -> list[dict]:
        events_by_region = {}
        
        # Chunk keywords to prevent 414 URI Too Long errors
        chunk_size = 8
        keyword_chunks = [NOTAM_KEYWORDS[i:i + chunk_size] for i in range(0, len(NOTAM_KEYWORDS), chunk_size)]

        if not self._http_client:
            import httpx
            self._http_client = httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=20.0
            )

        for base_feed in RSS_FEEDS:
            for chunk in keyword_chunks:
                query_str = " OR ".join(f'"{kw}"' for kw in chunk)
                if "news.google.com" in base_feed:
                    query_str += f" when:{self.FRESHNESS_HOURS}h"
                    
                encoded_query = urllib.parse.quote(query_str)
                url = base_feed.format(query=encoded_query)
                
                try:
                    resp = await self._http_client.get(url)
                    if resp.status_code != 200:
                        continue
                    
                    try:
                        root = ET.fromstring(resp.text)
                    except ET.ParseError:
                        continue
                        
                    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=self.FRESHNESS_HOURS)
                    
                    for item in root.findall(".//item"):
                        try:
                            title = item.findtext("title") or ""
                            link = item.findtext("link") or ""
                            pub_date_str = item.findtext("pubDate") or ""
                            
                            if not pub_date_str:
                                continue
                                
                            pub_date = parsedate_to_datetime(pub_date_str)
                            if pub_date.tzinfo is None:
                                pub_date = pub_date.replace(tzinfo=timezone.utc)
                                
                            if pub_date < cutoff_time:
                                continue
                                
                            # Quick Keyword validation
                            title_lower = title.lower()
                            if not any(kw.replace("\"", "") in title_lower for kw in NOTAM_KEYWORDS):
                                continue
                                
                            # Extract exact city location natively using offline Nominatim Geocoder
                            lat, lon, region = await self._async_extract_region_coords(title)
                                
                            # Group by region to cross-verify
                            if region not in events_by_region:
                                events_by_region[region] = {
                                    "lat": lat,
                                    "lon": lon,
                                    "latest_time": pub_date,
                                    "titles": [],
                                    "descriptions": [],
                                    "links": set() 
                                }
                            
                            if pub_date > events_by_region[region]["latest_time"]:
                                events_by_region[region]["latest_time"] = pub_date
                                
                            events_by_region[region]["titles"].append(title)
                            events_by_region[region]["links"].add(link)
                            
                            desc_text = item.findtext("description") or ""
                            desc_text = re.sub(r'<[^>]+>', '', desc_text).strip()
                            if desc_text:
                                events_by_region[region]["descriptions"].append(desc_text)
                            
                        except Exception as e:
                            logger.debug("[notam] Failed to parse RSS item: %s", e)
                            
                except Exception as e:
                    logger.debug("[notam] Failed to scrape RSS feed chunk: %s", e)
                    
        # Now pass grouped snippets to Ollama AI
        osint_results = []
        
        # Prevent DDOSing local Ollama: take only the top 10 regions by source count
        sorted_regions = sorted(events_by_region.items(), key=lambda x: len(x[1]["links"]), reverse=True)[:10]
        
        for region, data in sorted_regions:
            link_list = list(data["links"])
            source_count = len(link_list)
            
            base_verification_status = "CONFIRMED" if source_count > 1 else "SUSPECTED"
            primary_title = data["titles"][0]
            
            lat = data.get("lat", 0.0)
            lon = data.get("lon", 0.0)
            exact_time = data['latest_time'].isoformat()
            radius_km = 200 # Default restriction radius
            
            import hashlib
            from datetime import date
            hash_str = f"{region}_{date.today()}"
            event_id = hashlib.md5(hash_str.encode()).hexdigest()[:10]

            desc = f"*[Pending AI]*\n[{base_verification_status}] {primary_title}\n\nRestriction Radius: ~{radius_km}km\n*Sources: {source_count}*\n\n"
            desc += f"🤖 **[AI Assessment]** (Confidence: PENDING)\nAwaiting offline LLM verification..."

            event_obj = {
                "id": f"notam-osint-{event_id}",
                "type": "notam",
                "latitude": lat,
                "longitude": lon,
                "severity": 4, # High severity for warzone predictions
                "timestamp": exact_time,
                "source": "OSINT NOTAM Scraper",
                "title": f"[Pending AI] Restricted Airspace — {region}",
                "description": desc,
                "metadata": {
                    "verification": "PENDING AI",
                    "urls": link_list,
                    "country": region,
                    "radius_km": radius_km,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "ai_verification": "Awaiting local LLM evaluation...",
                    "confidence_score": 0,
                    "base_verification": base_verification_status,
                },
            }
                        # Prevent array wiping and redundant AI spam
            existing = next((e for e in self._cached_osint_events if e["id"] == event_obj["id"]), None)
            if existing:
                continue
            self._cached_osint_events.append(event_obj)
            osint_results.append(event_obj)
            
            texts_to_analyze = [primary_title] + data.get("descriptions", [])[:3]
            asyncio.create_task(self._background_verify(event_obj["id"], primary_title, texts_to_analyze, exact_time, region))

        logger.info("[notam] OSINT Scraper returned %d pending airspace closure events", len(osint_results))
        return osint_results

    async def _background_verify(self, event_id: str, title: str, texts: list[str], exact_time: str, region: str):
        from backend.ai_service import ai_service
        try:
            ai_result = await ai_service.verify_and_extract_event(
                title=title,
                texts=texts,
                current_time=exact_time,
                event_type="notam"
            )
            
            # Find the actual event in our cache by ID
            event_obj = next((e for e in self._cached_osint_events if e["id"] == event_id), None)
            if not event_obj:
                logger.warning("[notam] Background AI finished but event %s is no longer in cache", event_id)
                return
                
            if ai_result.get("verified", "NO").upper() != "YES":
                logger.info("[notam] Ollama AI rejected false positive. Reasoning: %s", ai_result.get("reasoning"))
                event_obj["_rejected"] = True
                return
                
            ai_reasoning = ai_result.get("reasoning", "Verified as an airspace restriction.")
            confidence = ai_result.get("confidence_score", 0)
            base_verification_status = event_obj["metadata"].get("base_verification", "SUSPECTED")
            verification_status = "AI CONFIRMED" if confidence > 75 else base_verification_status
            
            logger.info("[notam] Ollama AI accepted event in %s: %s (Confidence: %s)", region, ai_reasoning, confidence)
            
            event_obj["timestamp"] = ai_result.get("time", exact_time)
            
            if ai_result.get("latitude") and ai_result.get("longitude"):
                try:
                    event_obj["latitude"] = float(ai_result["latitude"])
                    event_obj["longitude"] = float(ai_result["longitude"])
                except Exception:
                    pass
                    
            if ai_result.get("location_name") and str(ai_result.get("location_name")).strip():
                event_obj["metadata"]["country"] = ai_result["location_name"]
                event_obj["title"] = f"Restricted Airspace — {ai_result['location_name']}"
            else:
                event_obj["title"] = event_obj["title"].replace("[Pending AI] ", "")
            
            event_obj["metadata"]["verification"] = verification_status
            event_obj["metadata"]["ai_verification"] = ai_reasoning
            event_obj["metadata"]["confidence_score"] = confidence
            
            desc = event_obj["description"].replace("*[Pending AI]*\n", "")
            desc = desc.replace(
                "🤖 **[AI Assessment]** (Confidence: PENDING)\nAwaiting offline LLM verification...", 
                f"🤖 **[AI Assessment]** (Confidence: {confidence}%)\n{ai_reasoning}"
            )
            event_obj["description"] = desc
        except Exception as e:
            logger.error("[notam] Background AI error: %s", e)

    async def _async_extract_region_coords(self, title: str) -> tuple[float, float, str]:
        """Smart heuristics to place the pin precisely using NLP offline geocoding."""
        import re
        
        # Many RSS feeds append publisher names (e.g. "... - The Times of India")
        # To prevent 'India' from triggering, we MUST strip the publisher suffix FIRST.
        clean_title = re.split(r'\s-\s|\s\|\s', title)[0]
        
        m_loc = re.search(r"(?:in|near|over|of|strikes|hits|at|off|for)\s([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*)", clean_title)
        if m_loc:
            candidate = m_loc.group(1).strip()
            # Ignore common noise words that break the Nominatim lookup
            if len(candidate) > 2 and candidate.lower() not in {"the", "a", "an", "new", "report", "video", "airspace", "flight", "flights", "middle east"}:
                geo = await self._async_geocode(candidate)
                if geo:
                    return geo[0], geo[1], candidate
                    
        text = clean_title.lower()
        
        # Ensure we have the same comprehensive fallback dictionary as UCDP!
        if "ukraine" in text or "kyiv" in text or "donetsk" in text or "russian" in text or "crimea" in text: return 48.0, 31.0, "Ukraine"
        if "gaza" in text or "israel" in text or "hamas" in text or "tel aviv" in text or "palestine" in text: return 31.5, 34.4, "Israel/Gaza"
        if "lebanon" in text or "hezbollah" in text or "beirut" in text: return 33.8, 35.5, "Lebanon"
        if "yemen" in text or "houthi" in text or "sanaa" in text or "red sea" in text: return 15.5, 48.5, "Yemen"
        if "sudan" in text or "khartoum" in text or "rsf" in text: return 15.6, 32.5, "Sudan"
        if "myanmar" in text or "junta" in text or "rakhine" in text: return 21.9, 95.9, "Myanmar"
        if "syria" in text or "damascus" in text or "idlib" in text or "aleppo" in text: return 34.8, 38.9, "Syria"
        if "russia" in text or "moscow" in text or "putin" in text or "belgorod" in text: return 55.7, 37.6, "Russia"
        if "somalia" in text or "al-shabaab" in text or "mogadishu" in text: return 5.1, 46.1, "Somalia"
        if "congo" in text or "m23" in text or "drc" in text or "goma" in text: return -4.0, 21.7, "DR Congo"
        if "afghanistan" in text or "kabul" in text or "taliban" in text: return 33.9, 67.7, "Afghanistan"
        if "pakistan" in text or "waziristan" in text or "balochistan" in text or "islamabad" in text: return 30.3, 69.3, "Pakistan"
        if "iran" in text or "tehran" in text: return 32.4, 53.6, "Iran"
        if "iraq" in text or "baghdad" in text or "erbīl" in text: return 33.2, 43.6, "Iraq"
        if "korea" in text or "pyongyang" in text or "seoul" in text: return 38.3, 127.0, "Korean Peninsula"
        if "taiwan" in text or "taipei" in text: return 23.6, 120.9, "Taiwan"
        if "nigeria" in text or "boko haram" in text or "abuja" in text: return 9.0, 8.6, "Nigeria"
        if "mali" in text or "bamako" in text: return 17.5, -3.9, "Mali"
        if "burkina faso" in text or "ouagadougou" in text: return 12.2, -1.5, "Burkina Faso"
        if "haiti" in text or "port-au-prince" in text: return 18.5, -72.3, "Haiti"
        if "colombia" in text or "farc" in text or "bogota" in text: return 4.5, -74.0, "Colombia"
        if "middle east" in text: return 29.29, 42.55, "Middle East"
        if "mexico" in text or "cartel" in text or "sinaloa" in text: return 23.6, -102.5, "Mexico"
        if "india" in text or "kashmir" in text or "manipur" in text: return 20.5, 78.9, "India"
        if "bangladesh" in text or "dhaka" in text: return 23.6, 90.3, "Bangladesh"
        if "philippines" in text or "manila" in text or "mindanao" in text: return 12.8, 121.7, "Philippines"
        if "kenya" in text or "nairobi" in text: return -0.0, 37.9, "Kenya"
        if "venezuela" in text or "caracas" in text: return 6.4, -66.5, "Venezuela"
        if "brazil" in text or "rio" in text: return -14.2, -51.9, "Brazil"
        if "peru" in text or "lima" in text: return -9.1, -75.0, "Peru"
        if "france" in text or "paris" in text: return 46.2, 2.2, "France"
        if "germany" in text or "berlin" in text: return 51.1, 10.4, "Germany"
        if "uk" in text or "london" in text: return 55.3, -3.4, "UK"
        if "usa" in text or "us" in text or "america" in text or "washington" in text: return 37.0, -95.7, "USA"
        if "egypt" in text or "cairo" in text: return 30.0, 31.2, "Egypt"
        if "jordan" in text or "amman" in text: return 31.9, 35.9, "Jordan"
        
        # If no country detected safely return a hashed region name instead of None
        # This prevents the critical bug where ALL unknown regions get grouped together under "Unknown Region"
        return 0.0, 20.0, f"Unknown_Region_{str(hash(text))[:8]}"
