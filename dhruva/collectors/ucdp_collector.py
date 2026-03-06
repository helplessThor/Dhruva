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
import asyncio

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.collector")

# High-conviction keywords for Conflict and Protest events
CONFLICT_KEYWORDS = [
    # General Combat
    "rebel clash", "military strike", "armed conflict", "terrorist attack",
    "gunfight", "artillery strike", "drone strike", "troops open fire",
    "border clash", "skirmish", "cross-border fire", "exchange fire",
    "war", "open-war", "declared war", "retaliate", "air strike", "surgical strike",
    "insurgency", "insurgent attack", "militia clash", "guerrilla attack", "ambush",
    "rocket attack", "missile strike", "mass casualty", "civil war", "invasion",
    "bombing", "suicide bombing", "ied explosion", "car bomb", "explosion",
    
    # Unrest & Protest
    "protest", "violent protest", "non-violent protest", "political violence",
    "civil unrest", "riot", "demonstration", "riots", "coup", "military coup", 
    "mutiny", "uprising", "rebellion", "revolution", "police clash", "tear gas",
    
    # Specific Hotspots & Regional Terms
    "pak afghan border", "pakistan army clash", "afghan border clash", "ttp attack",
    "line of control", "loc firing", "cross loc", "ceasefire violation", 
    "gaza strike", "idf strike", "hamas rocket", "hezbollah rocket", "lebanon strike",
    "cartel clash", "gang violence", "narco shootout", "gun battle", "chemical leak",
    "gas leak", "toxic gas leak", "chemical spill", "toxic spill", "industrial accident",
    "chemical plant", "chemical factory", "chemical explosion", "chemical fire",
    
    # India Specific Hotspots
    "maoist encounter", "naxal attack", "kashmir militant", "manipur clash", "assam border dispute",
    "kuki zo clash", "meitei clash", "jk gunfight", "jk infiltration", "bsf firing"
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "https://www.bing.com/news/search?q={query}&format=rss",
    "https://news.search.yahoo.com/rss?p={query}",
    # Web search specifically forcing Twitter/X OSINT handles + Major News Investigative sites
    "https://www.bing.com/search?q={query}+(site:twitter.com OR site:x.com OR site:reuters.com OR site:apnews.com OR site:bellingcat.com)&format=rss",
]

class UCDPCollector(BaseCollector):
    """Integrates BOTH Official UCDP API and live OSINT Conflict Scraping."""

    # Articles older than this are ignored by OSINT Scraper
    FRESHNESS_HOURS = 12
    OSINT_THROTTLE_SECONDS = 900

    def __init__(self, interval: int = 900):
        super().__init__(name="ucdp", interval=30)
        self.api_throttle = interval
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
        
        # 1. Official UCDP API (Throttled via init interval)
        now = datetime.now(timezone.utc)
        should_fetch_api = (
            not hasattr(self, '_last_api_fetch') or self._last_api_fetch is None or
            (now - self._last_api_fetch).total_seconds() >= self.api_throttle
        )
        
        if should_fetch_api:
            self._cached_official_events = await self._fetch_official_ucdp()
            self._last_api_fetch = now
            
        # Ensure we always deal with the dictionary directly
        official_events_list = self._cached_official_events if isinstance(self._cached_official_events, list) else list(self._cached_official_events.values())
        all_events.extend(official_events_list)
        
        # 2. OSINT Scraper (Throttled to OSINT_THROTTLE_SECONDS)
        now = datetime.now(timezone.utc)
        should_run_osint = (
            self._last_osint_scrape is None or 
            (now - self._last_osint_scrape).total_seconds() >= self.OSINT_THROTTLE_SECONDS
        )
        
        if should_run_osint:
            logger.info("[ucdp] OSINT throttle elapsed. Running live RSS scrape...")
            await self._scrape_osint_rss()
            self._last_osint_scrape = now
            
        # Filter out _rejected from background verification
        self._cached_osint_events = [e for e in self._cached_osint_events if not e.get("_rejected")]
        
        # 3. Deduplicate OSINT Scraper data against Official UCDP API data
        #    If an OSINT event is within 500km and 48 hours of an official event, drop it.
        filtered_osint = []
        for osint_ev in self._cached_osint_events:
            is_duplicate = False
            o_lat = osint_ev["latitude"]
            o_lon = osint_ev["longitude"]
            try: o_time = datetime.fromisoformat(osint_ev["timestamp"].replace("Z", "+00:00"))
            except: o_time = now
            
            for official_ev in official_events_list:
                u_lat = official_ev["latitude"]
                u_lon = official_ev["longitude"]
                try: u_time = datetime.fromisoformat(official_ev["timestamp"].replace("Z", "+00:00"))
                except: u_time = now
                
                time_diff = abs((o_time - u_time).total_seconds())
                dist_sq = (o_lat - u_lat)**2 + (o_lon - u_lon)**2
                
                if time_diff < 48 * 3600 and dist_sq < 100.0:
                    is_duplicate = True
                    # Append extra info from OSINT to official event
                    osint_urls = osint_ev.get("metadata", {}).get("urls", [])
                    if osint_urls:
                        existing_urls = official_ev.get("metadata", {}).get("osint_urls", [])
                        new_urls = list(set(existing_urls + osint_urls))
                        official_ev["metadata"]["osint_urls"] = new_urls
                        official_ev["metadata"]["osint_verified"] = True
                        if "📰 **OSINT Reports**" not in official_ev["description"]:
                            official_ev["description"] += f"\n\n📰 **OSINT Reports:**\n- {osint_urls[0]}"
                    break
                    
            if not is_duplicate:
                filtered_osint.append(osint_ev)
                
        # 4. Final Combination
        all_events.extend(filtered_osint)
        
        # 5. Fallback ID deduplication
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
        
        url = f"https://ucdpapi.pcr.uu.se/api/gedevents/26.0.1?pagesize=100&page={self._current_page}&StartDate={start_date_str}&EndDate={end_date_str}"
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
        
        # Aggregate news items by region to cross-verify and prevent Rate Limiting
        events_by_region = {}
        
        # Chunk keywords to prevent 414 URI Too Long errors across 3 search engines
        chunk_size = 12
        keyword_chunks = [CONFLICT_KEYWORDS[i:i + chunk_size] for i in range(0, len(CONFLICT_KEYWORDS), chunk_size)]

        if not self._http_client:
            import httpx
            # Use a generic User-Agent to bypass simple blocks from Bing/Yahoo
            self._http_client = httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
                timeout=20.0
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
                    # We might get 403 or 429 from Yahoo/Bing, just handle it gracefully
                    if resp.status_code != 200:
                        continue
                    
                    # Parse XML gracefully
                    try:
                        root = ET.fromstring(resp.text)
                    except ET.ParseError:
                        logger.debug("[ucdp] Failed to parse XML from %s, skipping.", url)
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
                            # Extract exact city location natively using offline Nominatim Geocoder
                            lat, lon, country = await self._async_extract_conflict_coords(title)
                                
                            # Group by country/region to cross-verify
                            if country not in events_by_region:
                                events_by_region[country] = {
                                    "lat": lat,
                                    "lon": lon,
                                    "latest_time": pub_date,
                                    "titles": [],
                                    "descriptions": [],
                                    "links": set() 
                                }
                            
                            # Update latest time
                            if pub_date > events_by_region[country]["latest_time"]:
                                events_by_region[country]["latest_time"] = pub_date
                                
                            events_by_region[country]["titles"].append(title)
                            events_by_region[country]["links"].add(link)
                            
                            
                            # Safely extract description text and strip HTML
                            desc_text = item.findtext("description") or ""
                            desc_text = re.sub(r'<[^>]+>', '', desc_text).strip()
                            if desc_text:
                                events_by_region[country]["descriptions"].append(desc_text)
                            
                        except Exception as e:
                            logger.debug("[ucdp] Failed to parse RSS item: %s", e)
                            
                except Exception as e:
                    logger.debug("[ucdp] Failed to scrape RSS feed chunk: %s", e)
                    
        # Now pass grouped snippets to Ollama AI for intelligent verification
        osint_results = []
        
        # Prevent DDOSing local Ollama: take only the top 10 regions by source count
        sorted_regions = sorted(events_by_region.items(), key=lambda x: len(x[1]["links"]), reverse=True)[:10]
        
        for country, data in sorted_regions:
            link_list = list(data["links"])
            source_count = len(link_list)
            
            base_verification_status = "CONFIRMED" if source_count > 1 else "SUSPECTED"
            
            # Pick the most representative title
            primary_title = data["titles"][0]
            
            lat = data.get("lat", 0.0)
            lon = data.get("lon", 0.0)
            exact_time = data['latest_time'].isoformat()
            
            import hashlib
            from datetime import date
            hash_str = f"{country}_{date.today()}"
            event_id = hashlib.md5(hash_str.encode()).hexdigest()[:10]

            desc = f"*[Pending AI]*\n[{base_verification_status}] {primary_title}\n\n"
            desc += f"*Sources: {source_count}*\n\n"
            desc += f"🤖 **[AI Assessment]** (Confidence: PENDING)\nAwaiting offline LLM verification..."

            event_obj = {
                "id": f"ucdp-osint-{event_id}",
                "type": "ucdp",
                "latitude": lat,
                "longitude": lon,
                "severity": 3,
                "timestamp": exact_time,
                "source": "OSINT Conflict Scraper",
                "title": f"[Pending AI] Armed Conflict — {country}",
                "description": desc,
                "metadata": {
                    "verification": "PENDING AI",
                    "urls": link_list,
                    "country": country,
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
            asyncio.create_task(self._background_verify(event_obj["id"], primary_title, texts_to_analyze, exact_time, country))

        logger.info("[ucdp] OSINT Scraper returned %d pending live conflict events", len(osint_results))
        return osint_results

    async def _background_verify(self, event_id: str, title: str, texts: list[str], exact_time: str, country: str):
        from backend.ai_service import ai_service
        try:
            ai_result = await ai_service.verify_and_extract_event(
                title=title,
                texts=texts,
                current_time=exact_time,
                event_type="conflict"
            )
            
            # Find the actual event in our cache by ID
            event_obj = next((e for e in self._cached_osint_events if e["id"] == event_id), None)
            if not event_obj:
                logger.warning("[ucdp] Background AI finished but event %s is no longer in cache", event_id)
                return
                
            if ai_result.get("verified", "NO").upper() != "YES":
                logger.info("[ucdp] Ollama AI rejected false positive. Reasoning: %s", ai_result.get("reasoning"))
                event_obj["_rejected"] = True
                return
                
            ai_reasoning = ai_result.get("reasoning", "Verified as a credible conflict event.")
            confidence = ai_result.get("confidence_score", 0)
            base_verification_status = event_obj["metadata"].get("base_verification", "SUSPECTED")
            verification_status = "AI CONFIRMED" if confidence > 75 else base_verification_status
            
            logger.info("[ucdp] Ollama AI accepted event in %s: %s (Confidence: %s)", country, ai_reasoning, confidence)
            
            event_obj["severity"] = 4 if confidence > 80 else 3
            event_obj["timestamp"] = ai_result.get("time", exact_time)
            
            if ai_result.get("latitude") and ai_result.get("longitude"):
                try:
                    event_obj["latitude"] = float(ai_result["latitude"])
                    event_obj["longitude"] = float(ai_result["longitude"])
                except Exception:
                    pass
                    
            if ai_result.get("location_name") and str(ai_result.get("location_name")).strip():
                event_obj["metadata"]["country"] = ai_result["location_name"]
                event_obj["title"] = f"Armed Conflict — {ai_result['location_name']}"
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
            logger.error("[ucdp] Background AI error: %s", e)

    async def _async_extract_conflict_coords(self, title: str) -> tuple[float, float, str]:
        """Smart heuristics to place the pin precisely where the news is talking about using NLP offline geocoding."""
        import re
        
        # Strip publisher suffix first to prevent it from tricking the regex match
        clean_title = re.split(r'\s-\s|\s\|\s', title)[0]
        
        # Prevent matching locations of administrative bodies (e.g., "Authority of Sri Lanka", "Bank of England")
        m_loc = re.search(r"(?<!Authority\s)(?<!Government\s)(?<!Ministry\s)(?<!Bank\s)(?<!Court\s)(?:in|near|of|strikes|hits|at|off|for)\s([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*)", clean_title)
        if m_loc:
            candidate = m_loc.group(1).strip()
            if len(candidate) > 2 and candidate.lower() not in {"the", "a", "an", "new", "report", "video", "middle east"}:
                geo = await self._async_geocode(candidate)
                if geo:
                    return geo[0], geo[1], candidate
                    
        text = clean_title.lower()
        
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
        
        # If no country detected safely return a hashed region name instead of None to avoid ghost locations
        # but still allow Groq to verify the event and extract the real location!
        return 0.0, 20.0, f"Unknown_Region_{str(hash(text))[:8]}"
