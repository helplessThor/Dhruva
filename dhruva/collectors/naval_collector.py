"""Dhruva — Naval Deployment OSINT Collector (Live Scraper).

Scrapes live news/OSINT RSS feeds to detect real-time naval carrier
group and submarine deployments across the globe.
Filters for articles published within the last 1 hour.
"""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# High-conviction keywords for Naval deployments
NAVAL_KEYWORDS = [
    "aircraft carrier", "naval strike group", "submarine deployment", 
    "carrier strike group", "naval exercise", "warship deployed", "csg"
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
]

class NavalCollector(BaseCollector):
    """Scrapes live OSINT News for Naval Deployments."""

    # Articles older than this are ignored
    FRESHNESS_HOURS = 1

    def __init__(self, interval: int = 3600):
        # Override BaseCollector interval to 30 for fast UI updates of background AI tasks
        super().__init__(name="naval", interval=30)
        self.OSINT_THROTTLE_SECONDS = interval
        self._last_osint_scrape = None
        self._cached_osint_events = []

    async def collect(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        should_run_osint = (
            self._last_osint_scrape is None or 
            (now - self._last_osint_scrape).total_seconds() >= self.OSINT_THROTTLE_SECONDS
        )
        
        if should_run_osint:
            logger.info("[naval] OSINT throttle elapsed. Running live RSS scrape...")
            await self._scrape_osint_rss()
            self._last_osint_scrape = now
            
        self._cached_osint_events = [e for e in self._cached_osint_events if not e.get("_rejected")]
        return self._cached_osint_events

    async def _scrape_osint_rss(self) -> list[dict]:
        # Build the boolean query
        query_str = "(" + " OR ".join(f'"{kw}"' for kw in NAVAL_KEYWORDS) + ") when:1h"
        encoded_query = urllib.parse.quote(query_str)
        
        # Aggregate news items by region to cross-verify
        events_by_region = {}
        
        for base_feed in RSS_FEEDS:
            url = base_feed.format(query=encoded_query)
            try:
                if not self._http_client:
                    import httpx
                    self._http_client = httpx.AsyncClient(timeout=30.0)
                    
                resp = await self._http_client.get(url, timeout=30.0)
                resp.raise_for_status()
                
                # Parse XML
                root = ET.fromstring(resp.text)
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
                            continue  # Too old
                            
                        # Quick Keyword validation to ensure it's actually military
                        title_lower = title.lower()
                        if not any(kw in title_lower for kw in ["carrier", "submarine", "navy", "strike group", "warship"]):
                            continue
                            
                        # Extract basic location hint via NER-lite approach
                        # Fallback default coords (center of Indian Ocean if we can't parse text easily, but UI relies on this)
                        # Normally we'd use a real Geocoder here. We will use dummy bounds for Naval OSINT.
                        lat, lon, region = self._extract_ocean_coords(title_lower)
                        
                        if region not in events_by_region:
                            events_by_region[region] = {
                                "lat": lat,
                                "lon": lon,
                                "latest_time": pub_date,
                                "titles": [],
                                "descriptions": [],
                                "links": set() 
                            }
                        
                        # Update latest time
                        if pub_date > events_by_region[region]["latest_time"]:
                            events_by_region[region]["latest_time"] = pub_date
                            
                        events_by_region[region]["titles"].append(title)
                        events_by_region[region]["links"].add(link)
                        
                        
                        # Safely extract description text and strip HTML
                        desc_text = item.findtext("description") or ""
                        desc_text = re.sub(r'<[^>]+>', '', desc_text).strip()
                        if desc_text:
                            events_by_region[region]["descriptions"].append(desc_text)
                        
                    except Exception as e:
                        logger.debug("[naval] Failed to parse RSS item: %s", e)
                        
            except Exception as e:
                logger.error("[naval] Failed to scrape RSS feed: %s", e)
                
        # Now pass grouped snippets to Ollama AI
        osint_results = []
        
        # Prevent DDOSing local Ollama: take only the top 10 regions by source count
        sorted_regions = sorted(events_by_region.items(), key=lambda x: len(x[1]["links"]), reverse=True)[:10]
        
        for region, data in sorted_regions:
            link_list = list(data["links"])
            source_count = len(link_list)
            
            # Cross-verification status
            base_verification_status = "CONFIRMED" if source_count > 1 else "SUSPECTED"
            primary_title = data["titles"][0]
            
            lat = data.get("lat", 0.0)
            lon = data.get("lon", 0.0)
            exact_time = data['latest_time'].isoformat()
            
            import hashlib
            from datetime import date
            hash_str = f"{region}_{date.today()}"
            event_id = hashlib.md5(hash_str.encode()).hexdigest()[:10]

            desc = f"*[Pending AI]*\n[{base_verification_status}] {primary_title}\n\n"
            desc += f"*Sources: {source_count}*\n\n"
            desc += f"🤖 **[AI Assessment]** (Confidence: PENDING)\nAwaiting offline LLM verification..."

            event_obj = {
                "id": f"naval-osint-{event_id}",
                "type": "naval",  # explicitly naval so frontend uses ship icon
                "latitude": lat,
                "longitude": lon,
                "severity": 3,
                "timestamp": exact_time,
                "source": "OSINT Naval Scraper",
                "title": f"[Pending AI] Naval Deployment — {region}",
                "description": desc,
                "metadata": {
                    "verification": "PENDING AI",
                    "source_count": source_count,
                    "urls": link_list,
                    "region": region,
                    "deployment_type": "Carrier Group / Warship",
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
            import asyncio
            asyncio.create_task(self._background_verify(event_obj["id"], primary_title, texts_to_analyze, exact_time, region))

        logger.info("[naval] OSINT Scraper returned %d pending naval events", len(osint_results))
        return osint_results

    async def _background_verify(self, event_id: str, title: str, texts: list[str], exact_time: str, region: str):
        from backend.ai_service import ai_service
        try:
            ai_result = await ai_service.verify_and_extract_event(
                title=title,
                texts=texts,
                current_time=exact_time,
                event_type="naval"
            )
            
            # Find the actual event in our cache by ID
            event_obj = next((e for e in self._cached_osint_events if e["id"] == event_id), None)
            if not event_obj:
                logger.warning("[naval] Background AI finished but event %s is no longer in cache", event_id)
                return
            
            if ai_result.get("verified", "NO").upper() != "YES":
                logger.info("[naval] Ollama AI rejected false positive. Reasoning: %s", ai_result.get("reasoning"))
                event_obj["_rejected"] = True
                return
                
            ai_reasoning = ai_result.get("reasoning", "Verified as a credible naval deployment.")
            confidence = ai_result.get("confidence_score", 0)
            base_verification_status = event_obj["metadata"].get("base_verification", "SUSPECTED")
            verification_status = "AI CONFIRMED" if confidence > 75 else base_verification_status
            
            logger.info("[naval] Ollama AI accepted event in %s: %s (Confidence: %s)", region, ai_reasoning, confidence)
            
            event_obj["severity"] = 5 if confidence > 80 else 4
            event_obj["timestamp"] = ai_result.get("time", exact_time)
            
            if ai_result.get("latitude") and ai_result.get("longitude"):
                try:
                    event_obj["latitude"] = float(ai_result["latitude"])
                    event_obj["longitude"] = float(ai_result["longitude"])
                except Exception:
                    pass
            
            if ai_result.get("location_name") and str(ai_result.get("location_name")).strip():
                event_obj["metadata"]["region"] = ai_result["location_name"]
                event_obj["title"] = f"Naval Deployment — {ai_result['location_name']}"
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
            logger.error("[naval] Background AI error: %s", e)

    def _extract_ocean_coords(self, text: str) -> tuple[float, float, str]:
        """Extremely simple heuristic to place the pin roughly where the news is talking about.
        If no geo found, default to Atlantic (0, -30)."""
        if "pacific" in text: return 0.0, -150.0, "Pacific Ocean"
        if "indian ocean" in text: return -10.0, 70.0, "Indian Ocean"
        if "mediterranean" in text: return 35.0, 18.0, "Mediterranean Sea"
        if "red sea" in text: return 20.0, 38.0, "Red Sea"
        if "south china sea" in text or "philippines" in text or "taiwan" in text: return 15.0, 115.0, "South China Sea"
        if "baltic" in text: return 57.0, 19.0, "Baltic Sea"
        if "black sea" in text: return 43.0, 34.0, "Black Sea"
        if "persian gulf" in text or "strait of hormuz" in text: return 26.0, 52.0, "Persian Gulf"
        return 0.0, -30.0, "Atlantic Ocean"  # Default Atlantic
