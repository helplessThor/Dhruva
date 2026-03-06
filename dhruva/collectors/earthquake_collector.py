"""Dhruva — Earthquake Collector (USGS GeoJSON Feed)."""

from datetime import datetime, timezone, timedelta
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import logging
import asyncio

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

EARTHQUAKE_KEYWORDS = [
    "earthquake", "magnitude", "tremor", "seismic", "quake"
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "https://www.bing.com/news/search?q={query}&format=rss",
    "https://news.search.yahoo.com/rss?p={query}",
    # Web search specifically forcing Twitter/X OSINT handles + Major News Investigative sites
    "https://www.bing.com/search?q={query}+(site:twitter.com OR site:x.com OR site:reuters.com OR site:apnews.com OR site:bellingcat.com)&format=rss",
]
class EarthquakeCollector(BaseCollector):
    """Fetches real-time earthquake data from USGS."""

    API_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson"

    FRESHNESS_HOURS = 24
    OSINT_THROTTLE_SECONDS = 3600

    def __init__(self, interval: int = 300):
        super().__init__(name="earthquake", interval=30)
        self.api_throttle = interval
        self.retention_hours = 24.0
        
        # State tracking for APIs
        self._last_usgs_fetch: datetime | None = None
        self._cached_usgs_data: dict = {}
        
        # State tracking for OSINT Scraper
        self._last_osint_scrape: datetime | None = None
        self._cached_osint_events: list[dict] = []

    def _magnitude_to_severity(self, mag: float) -> int:
        if mag >= 7.0:
            return 5
        elif mag >= 5.0:
            return 4
        elif mag >= 4.0:
            return 3
        elif mag >= 2.5:
            return 2
        return 1

    async def collect(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        
        # Throttled USGS Fetch
        should_fetch_usgs = (
            self._last_usgs_fetch is None or
            (now - self._last_usgs_fetch).total_seconds() >= self.api_throttle
        )
        if should_fetch_usgs:
            logger.info("[earthquake] Fetching latest USGS feed...")
            self._cached_usgs_data = await self.fetch_json(self.API_URL)
            self._last_usgs_fetch = now
            
        data = self._cached_usgs_data
        events = []

        for feature in data.get("features", []):
            fid = feature["id"]
            props = feature["properties"]
            coords = feature["geometry"]["coordinates"]  # [lon, lat, depth]
            mag = props.get("mag", 0) or 0
            
            eq_time = datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc)
            
            if (now - eq_time).total_seconds() > self.retention_hours * 3600:
                continue

            events.append({
                "id": f"eq-{fid}",
                "type": "earthquake",
                "latitude": coords[1],
                "longitude": coords[0],
                "severity": self._magnitude_to_severity(mag),
                "timestamp": eq_time.isoformat(),
                "source": "USGS",
                "title": props.get("title", f"M{mag} Earthquake"),
                "description": f"Magnitude {mag} at depth {coords[2]}km",
                "metadata": {
                    "magnitude": mag,
                    "depth_km": coords[2],
                    "felt": props.get("felt"),
                    "tsunami": props.get("tsunami", 0),
                    "url": props.get("url", ""),
                },
            })

        # 1. Fetch official USGS data
        usgs_events = events
        
        # 2. Add OSINT Scraper data (Throttled)
        should_run_osint = (
            self._last_osint_scrape is None or 
            (now - self._last_osint_scrape).total_seconds() >= self.OSINT_THROTTLE_SECONDS
        )
        
        if should_run_osint:
            logger.info("[earthquake] OSINT throttle elapsed. Running live RSS scrape...")
            await self._scrape_osint_rss()
            self._last_osint_scrape = now
            
        # Filter out _rejected ones
        self._cached_osint_events = [e for e in self._cached_osint_events if not e.get("_rejected")]
            
        # Deduplicate OSINT events against official USGS events
        filtered_osint = []
        for osint_ev in self._cached_osint_events:
            is_duplicate = False
            o_lat = osint_ev["latitude"]
            o_lon = osint_ev["longitude"]
            try:
                o_time = datetime.fromisoformat(osint_ev["timestamp"].replace("Z", "+00:00"))
            except:
                o_time = now
                
            for usgs_ev in usgs_events:
                u_lat = usgs_ev["latitude"]
                u_lon = usgs_ev["longitude"]
                try:
                    u_time = datetime.fromisoformat(usgs_ev["timestamp"].replace("Z", "+00:00"))
                except:
                    u_time = now
                    
                # Expand merge radius to be highly aggressive! (48 hours, ~10 degrees)
                time_diff = abs((o_time - u_time).total_seconds())
                dist_sq = (o_lat - u_lat)**2 + (o_lon - u_lon)**2
                
                if time_diff < 48 * 3600 and dist_sq < 100.0:
                    is_duplicate = True
                    # Append OSINT extra info to USGS event
                    osint_urls = osint_ev.get("metadata", {}).get("urls", [])
                    if osint_urls:
                        existing_urls = usgs_ev.get("metadata", {}).get("osint_urls", [])
                        new_urls = list(set(existing_urls + osint_urls))
                        usgs_ev["metadata"]["osint_urls"] = new_urls
                        usgs_ev["metadata"]["osint_verified"] = True
                        if "📰 **OSINT Reports**" not in usgs_ev["description"]:
                            usgs_ev["description"] += f"\n\n📰 **OSINT Reports:**\n- {osint_urls[0]}"
                    break
                    
            if not is_duplicate:
                filtered_osint.append(osint_ev)
            
        usgs_events.extend(filtered_osint)

        return usgs_events

    async def _scrape_osint_rss(self) -> list[dict]:
        # Aggregate news items by region to cross-verify and prevent Rate Limiting
        events_by_region = {}
        
        # Chunk keywords to prevent 414 URI Too Long errors across diverse search engines
        chunk_size = 3
        keyword_chunks = [EARTHQUAKE_KEYWORDS[i:i + chunk_size] for i in range(0, len(EARTHQUAKE_KEYWORDS), chunk_size)]

        if not self._http_client:
            import httpx
            # Use a generic User-Agent to bypass simple blocks from Bing/Yahoo
            self._http_client = httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                timeout=30.0
            )
            
        for base_feed in RSS_FEEDS:
            for chunk in keyword_chunks:
                # Google News strictly supports the 'when:XXh' operator
                query_str = " OR ".join(f'"{kw}"' for kw in chunk)
                if "news.google.com" in base_feed:
                    query_str += f" when:{self.FRESHNESS_HOURS}h"
                    
                encoded_query = urllib.parse.quote(query_str)
                url = base_feed.format(query=encoded_query)
                
                try:
                    resp = await self._http_client.get(url)
                    if resp.status_code != 200:
                        continue
                
                    # Parse XML gracefully
                    try:
                        root = ET.fromstring(resp.text)
                    except ET.ParseError:
                        logger.debug("[earthquake] Failed to parse XML from %s, skipping.", url)
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
                                continue  # Too old
                                
                            # Quick Keyword validation
                            title_lower = title.lower()
                            if not any(kw.replace("\"", "") in title_lower for kw in EARTHQUAKE_KEYWORDS):
                                continue
                                
                            # Extract hint using original title case for Capitalized Entity Regex
                            lat, lon, loc_name, mag = await self._async_extract_earthquake_coords(title)
                            
                            if loc_name not in events_by_region:
                                events_by_region[loc_name] = {
                                    "lat": lat,
                                    "lon": lon,
                                    "mag": mag,
                                    "latest_time": pub_date,
                                    "titles": [],
                                    "descriptions": [],
                                    "links": set() 
                                }
                            
                            if pub_date > events_by_region[loc_name]["latest_time"]:
                                events_by_region[loc_name]["latest_time"] = pub_date
                                
                            events_by_region[loc_name]["titles"].append(title)
                            events_by_region[loc_name]["links"].add(link)
                            
                            
                            # Safely extract description text and strip HTML
                            desc_text = item.findtext("description") or ""
                            desc_text = re.sub(r'<[^>]+>', '', desc_text).strip()
                            if desc_text:
                                events_by_region[loc_name]["descriptions"].append(desc_text)
                            
                        except Exception as e:
                            logger.debug("[earthquake] Failed to parse RSS item: %s", e)
                            
                except Exception as e:
                    logger.debug("[earthquake] Failed to scrape RSS feed chunk: %s", e)
                    
        # Immediately return OSINT array as Pending and fire background verification tasks
        osint_results = []
        for loc_name, data in events_by_region.items():
            link_list = list(data["links"])
            source_count = len(link_list)
            primary_title = data["titles"][0]
            
            mag = data.get("mag", 4.0)
            lat = data.get("lat", 0.0)
            lon = data.get("lon", 0.0)
            exact_time = data['latest_time'].isoformat()
            import hashlib
            from datetime import date
            hash_str = f"{loc_name}_{date.today()}"
            event_id = hashlib.md5(hash_str.encode()).hexdigest()[:10]

            desc = f"{primary_title}\n\nMagnitude: {mag}\n*Sources: {source_count}*\n\n"
            desc += f"🤖 **[AI Assessment]** (Turned Off)"

            event_obj = {
                "id": f"eq-osint-{event_id}",
                "type": "earthquake",
                "latitude": lat,
                "longitude": lon,
                "severity": self._magnitude_to_severity(mag),
                "timestamp": exact_time,
                "source": "OSINT Scraper",
                "title": f"M{mag} Earthquake — {loc_name}",
                "description": desc,
                "metadata": {
                    "magnitude": mag,
                    "urls": link_list,
                    "location_name": loc_name,
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                    "verification": "SUSPECTED",
                    "ai_verification": "AI Verification Disabled",
                    "confidence_score": 0,
                },
            }
                        # Prevent array wiping and redundant AI spam
            existing = next((e for e in self._cached_osint_events if e["id"] == event_obj["id"]), None)
            if existing:
                continue
            self._cached_osint_events.append(event_obj)
            osint_results.append(event_obj)
            
            # Fire background task (Turned off for earthquakes)
            # texts_to_analyze = [primary_title] + data.get("descriptions", [])[:3]
            # asyncio.create_task(self._background_verify(event_obj, primary_title, texts_to_analyze, exact_time))

        logger.info("[earthquake] OSINT Scraper returned %d pending earthquake events", len(osint_results))
        return osint_results

    async def _background_verify(self, event_obj, title, texts, exact_time):
        from backend.ai_service import ai_service
        try:
            ai_result = await ai_service.verify_and_extract_event(
                title=title,
                texts=texts,
                current_time=exact_time,
                event_type="earthquake"
            )
            
            if ai_result.get("verified", "NO").upper() != "YES":
                logger.info("[earthquake] Ollama AI rejected false positive. Reasoning: %s", ai_result.get("reasoning"))
                event_obj["_rejected"] = True
                return
                
            confidence = ai_result.get("confidence_score", 0)
            reasoning = ai_result.get("reasoning", "Verified earthquake event.")
            
            logger.info("[earthquake] Ollama AI accepted event: %s (Confidence: %s)", reasoning, confidence)
            
            event_obj["metadata"]["verification"] = "AI CONFIRMED" if confidence > 75 else "SUSPECTED"
            event_obj["metadata"]["ai_verification"] = reasoning
            event_obj["metadata"]["confidence_score"] = confidence
            event_obj["title"] = event_obj["title"].replace("[Pending AI] ", "")
            
            # Update desc
            desc = event_obj["description"].replace("*[Pending AI]*\n", "")
            desc = desc.replace(
                "🤖 **[AI Assessment]** (Confidence: PENDING)\nAwaiting offline LLM verification...", 
                f"🤖 **[AI Assessment]** (Confidence: {confidence}%)\n{ai_result.get('reasoning', reasoning)}"
            )
            event_obj["description"] = desc
        except Exception as e:
            logger.error("[earthquake] Background AI error: %s", e)
    async def _async_extract_earthquake_coords(self, title: str) -> tuple[float, float, str, float]:
        """Smart heuristics for earthquake extraction [lat, lon, location_name, mag] using NLP offline geocoding."""
        import re
        
        # Strip publisher suffix first to prevent it from tricking the regex match (e.g. " - The Times of India")
        clean_title = re.split(r'\s-\s|\s\|\s', title)[0]
        text = clean_title.lower()
        mag = 4.0 # default
        
        m_mag = re.search(r"magnitude\s+([\d\.]+)", text) or re.search(r"m\s?([\d\.]+)", text)
        if m_mag:
            try: mag = float(m_mag.group(1))
            except: pass
            
        # 1. Attempt strict Entity Extraction for exact cities/regions
        # Prevent matching locations of administrative bodies
        m_loc = re.search(r"(?<!Authority\s)(?<!Government\s)(?<!Ministry\s)(?<!Bank\s)(?<!Court\s)(?:in|near|of|strikes|hits|at|off)\s([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)", clean_title)
        if m_loc:
            candidate = m_loc.group(1).strip()
            if len(candidate) > 2 and candidate.lower() not in {"the", "a", "an", "new", "report", "video"}:
                geo = await self._async_geocode(candidate)
                if geo:
                    return geo[0], geo[1], candidate, mag
                
        # 2. Fallback to generic known-hotspot centroids
        if "california" in text or "los angeles" in text: return 36.7, -119.4, "California, USA", mag
        if "taiwan" in text: return 23.6, 120.9, "Taiwan", mag
        if "japan" in text or "tokyo" in text: return 36.2, 138.2, "Japan", mag
        if "turkey" in text or "syria" in text: return 38.9, 35.2, "Turkey/Syria", mag
        if "chile" in text: return -35.6, -71.5, "Chile", mag
        if "mexico" in text: return 23.6, -102.5, "Mexico", mag
        if "indonesia" in text: return -0.7, 113.9, "Indonesia", mag
        if "philippines" in text: return 12.8, 121.7, "Philippines", mag
        if "new zealand" in text: return -40.9, 174.8, "New Zealand", mag
        if "italy" in text: return 41.8, 12.5, "Italy", mag
        if "peru" in text: return -9.1, -75.0, "Peru", mag
        if "afghanistan" in text: return 33.9, 67.7, "Afghanistan", mag
        if "papua new guinea" in text: return -6.3, 143.9, "Papua New Guinea", mag
        if "greece" in text: return 39.0, 22.0, "Greece", mag
        
        # If no country detected safely return generic fallback to allow Groq processing
        return 0.0, 0.0, f"Unknown_Loc_{str(hash(text))[:8]}", mag
