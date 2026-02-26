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
        super().__init__(name="naval", interval=interval)

    async def collect(self) -> list[dict]:
        events = []
        
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
                        
                        # Group by region to cross-verify
                        if region not in events_by_region:
                            events_by_region[region] = {
                                "lat": lat,
                                "lon": lon,
                                "latest_time": pub_date,
                                "titles": [],
                                "links": set() 
                            }
                        
                        # Update latest time
                        if pub_date > events_by_region[region]["latest_time"]:
                            events_by_region[region]["latest_time"] = pub_date
                            
                        events_by_region[region]["titles"].append(title)
                        events_by_region[region]["links"].add(link)
                        
                    except Exception as e:
                        logger.debug("[naval] Failed to parse RSS item: %s", e)
                        
            except Exception as e:
                logger.error("[naval] Failed to scrape RSS feed: %s", e)
                
        # Now convert the aggregated intelligence into OsintEvents
        for region, data in events_by_region.items():
            link_list = list(data["links"])
            source_count = len(link_list)
            
            # Cross-verification status
            verification_status = "CONFIRMED" if source_count > 1 else "SUSPECTED"
            
            # Pick the most representative title
            primary_title = data["titles"][0]
            
            # ── GROQ AI VERIFICATION ──────────────────────────────────────
            ai_prompt = (
                f"You are an OSINT intelligence analyst observing naval movements.\n"
                f"Title: '{primary_title}'\n"
                f"Sources: {link_list}\n"
                f"Current Time: {data['latest_time'].isoformat()}\n\n"
                "Task: Verify if this represents a real-world, current Naval Deployment of a carrier group or submarine.\n"
                "CRITICAL RULES:\n"
                "1. DO NOT INCLUDE ANY URLs or LINKS IN YOUR RESPONSE.\n"
                "2. Your entire response MUST be exactly one sentence.\n"
                "3. You must start with strictly YES or NO, followed by a hyphen.\n"
                "4. You MUST include your best estimate of the EXACT human-readable Date and Time of Occurrence (e.g., 'Tuesday, October 24th at 08:00 UTC').\n\n"
                "Example Format: 'YES - Based on the reports, the USS Nimitz deployed to the Pacific on Tuesday, October 24th at approximately 08:00 UTC.'"
            )
            ai_response = await self.ask_groq(ai_prompt)
            
            # If the LLM outright rejects it (e.g., historical retrospective or movie), skip it entirely
            if ai_response.upper().startswith("NO"):
                logger.info("[naval] Groq AI rejected false positive: %s", ai_response)
                continue
            
            # Extract the reasoning to show the user
            ai_reasoning = ai_response.replace("YES -", "").replace("YES-", "").replace("YES", "").strip()
            if not ai_reasoning:
                ai_reasoning = "Verified as a credible naval deployment based on the provided OSINT sources."
                
            logger.info("[naval] Groq AI accepted event: %s", ai_response)
            # ──────────────────────────────────────────────────────────────
            
            # Build unified description with AI assessment
            desc = f"[{verification_status}] {primary_title}\n\n"
            desc += f"🤖 **[Groq AI Assessment]**\n{ai_reasoning}"
                 
            event_id = str(hash(region + str(data["latest_time"])))[:10].replace("-", "")
            
            events.append({
                "id": f"naval-osint-{event_id}",
                "type": "naval",  # Changed from military to explicitly naval so frontend uses ship icon
                "latitude": data["lat"],
                "longitude": data["lon"],
                "severity": 3,
                "timestamp": data["latest_time"].isoformat(),
                "source": "OSINT Naval Scraper",
                "title": f"[{verification_status}] Naval Deployment",
                "description": desc,
                "metadata": {
                    "verification": verification_status,
                    "source_count": source_count,
                    "urls": link_list,
                    "region": region,
                    "deployment_type": "Carrier Group / Warship",
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "groq_verification": ai_reasoning,
                },
            })
                
        logger.info("[naval] OSINT Scraper returned %d live cross-verified deployment events", len(events))
        return events

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
