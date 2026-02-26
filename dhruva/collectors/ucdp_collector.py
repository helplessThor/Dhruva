"""Dhruva — Live OSINT Conflict Scraper (UCDP Replacement).

Scrapes live news/OSINT RSS feeds to detect real-time conflicts, clashes,
and strikes across the globe.
Filters for articles published within the last 6 hours.
"""

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# High-conviction keywords for Conflict events
CONFLICT_KEYWORDS = [
    "rebel clash", "military strike", "armed conflict", "terrorist attack",
    "gunfight", "artillery strike", "drone strike", "troops open fire"
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
]

class UCDPCollector(BaseCollector):
    """Integrates BOTH Official UCDP API and live OSINT Conflict Scraping."""

    # Articles older than this are ignored by OSINT Scraper
    FRESHNESS_HOURS = 6
    OSINT_THROTTLE_SECONDS = 3600

    def __init__(self, interval: int = 20):
        super().__init__(name="ucdp", interval=interval)
        from backend.config import settings
        self.ucdp_api_token = settings.ucdp_api_token
        
        # State tracking for Official Pagination
        self._current_page = 0
        self._cached_official_events: dict[str, dict] = {}
        
        # State tracking for OSINT Scraper
        self._last_osint_scrape: datetime | None = None
        self._cached_osint_events: list[dict] = []

    async def collect(self) -> list[dict]:
        all_events = []
        
        # 1. Official UCDP API (Runs every interval, paginating)
        official_events = await self._fetch_official_ucdp()
        all_events.extend(official_events)
        
        # 2. OSINT Scraper (Throttled to run only once per hour)
        now = datetime.now(timezone.utc)
        should_run_osint = (
            self._last_osint_scrape is None or 
            (now - self._last_osint_scrape).total_seconds() >= self.OSINT_THROTTLE_SECONDS
        )
        
        if should_run_osint:
            logger.info("[ucdp] OSINT throttle elapsed. Running live RSS scrape...")
            self._cached_osint_events = await self._scrape_osint_rss()
            self._last_osint_scrape = now
            
        all_events.extend(self._cached_osint_events)
        
        # 3. Final Overall Deduplication (Fallback)
        unique_events = {}
        for ev in all_events:
            unique_events[ev["id"]] = ev
            
        return list(unique_events.values())
        
    async def _fetch_official_ucdp(self) -> list[dict]:
        if not self.ucdp_api_token:
            logger.warning("[ucdp] No Official API Token found in config. Skipping API sync.")
            return list(self._cached_official_events.values())
            
        today = datetime.now(timezone.utc)
        two_days_ago = today - timedelta(days=2)
        start_date_str = two_days_ago.strftime("%Y-%m-%d")
        end_date_str = today.strftime("%Y-%m-%d")
        
        url = f"https://ucdpapi.pcr.uu.se/api/gedevents/25.1?pagesize=100&page={self._current_page}&StartDate={start_date_str}&EndDate={end_date_str}"
        headers = {"x-ucdp-access-token": self.ucdp_api_token}
        
        try:
            if not self._http_client:
                import httpx
                self._http_client = httpx.AsyncClient(timeout=30.0)
                
            resp = await self._http_client.get(url, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
            
            items = data.get("Result", [])
            for item in items:
                try:
                    lat = float(item.get("latitude", 0))
                    lon = float(item.get("longitude", 0))
                    country = item.get("country", "Unknown")
                    conflict_name = item.get("conflict_name", "Unknown Conflict")
                    date_start = item.get("date_start", "")
                    
                    event_id = str(item.get("id", ""))
                    if not event_id:
                         event_id = str(hash(f"{lat}{lon}{date_start}"))[:10]
                    
                    event_obj = {
                        "id": f"ucdp-official-{event_id}",
                        "type": "ucdp",
                        "latitude": lat,
                        "longitude": lon,
                        "severity": 4, 
                        "timestamp": date_start if date_start else datetime.now(timezone.utc).isoformat(),
                        "source": "Official UCDP API",
                        "title": f"[OFFICIAL: UCDP] {conflict_name}",
                        "description": f"Location: {item.get('adm_1', '')}, {country}\nDeaths: {item.get('best', 0)}",
                        "metadata": {
                            "verification": "OFFICIAL",
                            "country": country,
                            "deaths": item.get("best", 0),
                            "source_office": item.get("source_office", ""),
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                        },
                    }
                    
                    # Store deduplicated by Official ID
                    self._cached_official_events[event_obj["id"]] = event_obj
                except Exception as e:
                    logger.debug("[ucdp] Failed to parse official API item: %s", e)
                    
            logger.info("[ucdp] Official API processed page %d (Cache: %d items)", self._current_page, len(self._cached_official_events))
            
            # Keep Rolling Cache to maximum 2,000 to prevent ballooning memory
            if len(self._cached_official_events) > 2000:
                keys_to_drop = list(self._cached_official_events.keys())[:-2000]
                for k in keys_to_drop:
                    del self._cached_official_events[k]
                    
            # Increment pagination
            self._current_page += 1
            if not data.get("NextPageUrl"):
                logger.info("[ucdp] Reached end of Official API pages. Resetting to 0.")
                self._current_page = 0
                
        except Exception as e:
            logger.error("[ucdp] Failed to fetch Official UCDP API: %s", e)
            
        return list(self._cached_official_events.values())

    async def _scrape_osint_rss(self) -> list[dict]:
        events = []
        
        # Build the boolean query
        query_str = "(" + " OR ".join(f'"{kw}"' for kw in CONFLICT_KEYWORDS) + ") when:6h"
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
                            
                        # Quick Keyword validation
                        title_lower = title.lower()
                        if not any(kw.replace("\"", "") in title_lower for kw in CONFLICT_KEYWORDS):
                            continue
                            
                        # Extract basic location hint via NER-lite approach
                        lat, lon, country = self._extract_conflict_coords(title_lower)
                        
                        # Group by country/region to cross-verify
                        if country not in events_by_region:
                            events_by_region[country] = {
                                "lat": lat,
                                "lon": lon,
                                "latest_time": pub_date,
                                "titles": [],
                                "links": set() 
                            }
                        
                        # Update latest time
                        if pub_date > events_by_region[country]["latest_time"]:
                            events_by_region[country]["latest_time"] = pub_date
                            
                        events_by_region[country]["titles"].append(title)
                        events_by_region[country]["links"].add(link)
                        
                    except Exception as e:
                        logger.debug("[ucdp] Failed to parse RSS item: %s", e)
                        
            except Exception as e:
                logger.error("[ucdp] Failed to scrape RSS feed: %s", e)
                
        # Now convert the aggregated intelligence into OsintEvents
        for country, data in events_by_region.items():
            link_list = list(data["links"])
            source_count = len(link_list)
            
            # Cross-verification status
            verification_status = "CONFIRMED" if source_count > 1 else "SUSPECTED"
            
            # Pick the most representative title
            primary_title = data["titles"][0]
            
            # ── GROQ AI VERIFICATION ──────────────────────────────────────
            ai_prompt = (
                f"You are an OSINT intelligence analyst observing global conflicts.\n"
                f"Title: '{primary_title}'\n"
                f"Sources: {link_list}\n"
                f"Current Time: {data['latest_time'].isoformat()}\n\n"
                "Task: Verify if this represents a real-world, current Armed Conflict, Terrorist Attack, or Military Clash.\n"
                "CRITICAL RULES:\n"
                "1. DO NOT INCLUDE ANY URLs or LINKS IN YOUR RESPONSE.\n"
                "2. Your entire response MUST be exactly one sentence.\n"
                "3. You must start with strictly YES or NO, followed by a hyphen.\n"
                "4. You MUST include your best estimate of the EXACT human-readable Date and Time of Occurrence (e.g., 'Tuesday, October 24th at 14:00 UTC, 2026').\n\n"
                "Example Format: 'YES - Based on the reports, armed forces opened fire in Sudan on Tuesday, October 24th at approximately 14:00 UTC, 2026.'"
            )
            ai_response = await self.ask_groq(ai_prompt)
            
            # If the LLM outright rejects it (e.g., historical retrospective or movie), skip it entirely
            if ai_response.upper().startswith("NO"):
                logger.info("[ucdp] Groq AI rejected false positive: %s", ai_response)
                continue
            
            # Extract the reasoning to show the user
            ai_reasoning = ai_response.replace("YES -", "").replace("YES-", "").replace("YES", "").strip()
            if not ai_reasoning:
                ai_reasoning = "Verified as a credible armed conflict based on the provided OSINT sources."
                
            logger.info("[ucdp] Groq AI accepted event: %s", ai_response)
            # ──────────────────────────────────────────────────────────────
            
            # Build unified description with AI assessment
            desc = f"[{verification_status}] {primary_title}\n\n"
            desc += f"🤖 **[Groq AI Assessment]**\n{ai_reasoning}"
                 
            event_id = str(hash(country + str(data["latest_time"])))[:10].replace("-", "")

            events.append({
                "id": f"ucdp-osint-{event_id}",
                "type": "ucdp",
                "latitude": data["lat"],
                "longitude": data["lon"],
                "severity": 4 if source_count > 1 else 3,  # Multi-source boosts severity
                "timestamp": data["latest_time"].isoformat(),
                "source": "OSINT Conflict Scraper",
                "title": f"[{verification_status}] Armed Conflict — {country}",
                "description": desc,
                "metadata": {
                    "verification": verification_status,
                    "source_count": source_count,
                    "urls": link_list,
                    "country": country,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "groq_verification": ai_reasoning,
                },
            })
                
        logger.info("[ucdp] OSINT Scraper returned %d live cross-verified conflict events", len(events))
        return events

    def _extract_conflict_coords(self, text: str) -> tuple[float, float, str]:
        """Extremely simple heuristic to place the pin roughly where the news is talking about.
        If no geo found, default to a generic "Unknown" coordinate."""
        if "ukraine" in text or "kyiv" in text or "donetsk" in text: return 48.0, 31.0, "Ukraine"
        if "gaza" in text or "israel" in text or "hamas" in text: return 31.5, 34.4, "Israel/Gaza"
        if "lebanon" in text or "hezbollah" in text: return 33.8, 35.5, "Lebanon"
        if "yemen" in text or "houthi" in text: return 15.5, 48.5, "Yemen"
        if "sudan" in text or "khartoum" in text: return 15.6, 32.5, "Sudan"
        if "myanmar" in text or "junta" in text: return 21.9, 95.9, "Myanmar"
        if "syria" in text: return 34.8, 38.9, "Syria"
        if "russia" in text or "moscow" in text: return 55.7, 37.6, "Russia"
        if "somalia" in text or "al-shabaab" in text: return 5.1, 46.1, "Somalia"
        if "dr congo" in text or "m23" in text: return -4.0, 21.7, "DR Congo"
        # Default pin if we can't match a hot conflict zone (put it near equator/africa as fallback)
        return 0.0, 20.0, "Unknown Region"
