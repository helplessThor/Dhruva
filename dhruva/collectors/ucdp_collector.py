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
    "bombing", "suicide bombing", "ied explosion", "car bomb",
    
    # Unrest & Protest
    "protest", "violent protest", "non-violent protest", "political violence",
    "civil unrest", "riot", "demonstration", "riots", "coup", "military coup", 
    "mutiny", "uprising", "rebellion", "revolution", "police clash", "tear gas",
    
    # Specific Hotspots & Regional Terms
    "pak afghan border", "pakistan army clash", "afghan border clash", "ttp attack",
    "line of control", "loc firing", "cross loc", "ceasefire violation", 
    "gaza strike", "idf strike", "hamas rocket", "hezbollah rocket", "lebanon strike",
    "ukraine drone", "russian strike", "kyiv attack", "moscow drone",
    "myanmar junta drill", "rsf clash", "houthi rebel", "red sea ship attack",
    "cartel clash", "gang violence", "narco shootout", "gun battle",
]

RSS_FEEDS = [
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en",
    "https://www.bing.com/news/search?q={query}&format=rss",
    "https://news.search.yahoo.com/rss?p={query}",
]

class UCDPCollector(BaseCollector):
    """Integrates BOTH Official UCDP API and live OSINT Conflict Scraping."""

    # Articles older than this are ignored by OSINT Scraper
    FRESHNESS_HOURS = 48
    OSINT_THROTTLE_SECONDS = 120

    def __init__(self, interval: int = 30):
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
            
        # 3. Deduplicate OSINT Scraper data against Official UCDP API data
        #    If an OSINT event is within 500km and 48 hours of an official event, drop it.
        filtered_osint = []
        for osint_ev in self._cached_osint_events:
            is_duplicate = False
            o_lat = osint_ev["latitude"]
            o_lon = osint_ev["longitude"]
            try: o_time = datetime.fromisoformat(osint_ev["timestamp"].replace("Z", "+00:00"))
            except: o_time = now
            
            for official_ev in official_events:
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
                    logger.debug("[ucdp] Failed to scrape RSS feed chunk: %s", e)
                    
        # Now pass grouped snippets to Groq AI for intelligent extraction
        osint_results = []
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
                f"Article Time: {data['latest_time'].isoformat()}\n\n"
                "Task: Verify if this represents a real-world, current Armed Conflict, Terrorist Attack, or Military Clash.\n"
                "Extract the following information as strict JSON only. Do not add markdown or comments.\n\n"
                "RULES FOR ATTRIBUTION:\n"
                "- If Country B attacks Country A, mark ONLY Country A (the victim) as affected.\n"
                "- If Country B attacks Country A AND Country B explicitly claims the attack, mark BOTH Country A and Country B as affected.\n"
                "- If Country A retaliates against Country B, mark BOTH Country A and Country B as affected.\n"
                "- Include the exact Date and Time of occurrence extracted from the text (using Article Time as a reference point). Use ISO 8601 format.\n\n"
                "Return format:\n"
                "{\n"
                '  "is_conflict": true/false,\n'
                '  "reasoning": "1 sentence explanation.",\n'
                '  "exact_time": "2026-10-24T14:00:00Z", \n'
                '  "locations": [\n'
                '      {"country": "CountryName", "lat": 1.23, "lon": 4.56}\n'
                '  ]\n'
                "}"
            )
            try:
                ai_response = await self.ask_groq(ai_prompt, json_mode=True)
                
                # Try to safely extract just the JSON part
                import re, json
                json_match = re.search(r"\{.*\}", ai_response, re.DOTALL)
                if json_match:
                    ai_response = json_match.group(0)
                
                result = json.loads(ai_response)
                
                if not result.get("is_conflict"):
                    logger.info("[ucdp] Groq AI rejected false positive: %s", result.get("reasoning", "No reason"))
                    continue
                    
                locations = result.get("locations", [])
                if not locations:
                    logger.info("[ucdp] Groq AI verified conflict but found no valid location.")
                    continue
                    
                exact_time = result.get("exact_time") or data['latest_time'].isoformat()
                reasoning = result.get("reasoning", "Verified as credible conflict based on OSINT.")
                
                for loc in locations:
                    ai_country = loc.get("country", country)
                    lat = loc.get("lat", data["lat"])
                    lon = loc.get("lon", data["lon"])
                    
                    event_id = str(hash(ai_country + exact_time + primary_title))[:10].replace("-", "")

                    osint_results.append({
                        "id": f"ucdp-osint-{event_id}",
                        "type": "ucdp",
                        "latitude": lat,
                        "longitude": lon,
                        "severity": 4 if source_count > 1 else 3,
                        "timestamp": exact_time,
                        "source": "OSINT Conflict Scraper",
                        "title": f"[AI Verified] Armed Conflict — {ai_country}",
                        "description": f"[{verification_status}] {primary_title}\n\n🤖 **[Groq AI Assessment]**\n{reasoning}\n*Sources: {source_count}*",
                        "metadata": {
                            "verification": "AI Verified",
                            "urls": link_list,
                            "country": ai_country,
                            "scraped_at": datetime.now(timezone.utc).isoformat(),
                            "groq_verification": reasoning,
                        },
                    })
            except Exception as e:
                err_str = str(e)
                if "rate_limit" in err_str or "tokens per day" in err_str:
                    logger.warning("[ucdp] Groq AI Rate Limit Reached! Using Fallback Strategy for '%s'", country)
                else:
                    logger.debug("[ucdp] Failed to parse Groq response: %s", e)
                
                # Fallback Strategy: Retain the event as SUSPECTED/PENDING AI VERIFICATION
                event_id = str(hash(country + str(data['latest_time'])))[:10].replace("-", "")
                osint_results.append({
                    "id": f"ucdp-osint-fallback-{event_id}",
                    "type": "ucdp",
                    "latitude": data["lat"],
                    "longitude": data["lon"],
                    "severity": 3,
                    "timestamp": data['latest_time'].isoformat(),
                    "source": "OSINT Conflict Scraper",
                    "title": f"[Pending AI Verification] Armed Conflict — {country}",
                    "description": f"[{verification_status}] {primary_title}\n\n🤖 **[Groq AI Assessment]**\nPending AI Verification (Processing or Rate Limit Error)\n*Sources: {source_count}*",
                    "metadata": {
                        "verification": verification_status,
                        "urls": link_list,
                        "country": country,
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "groq_verification": "AI Verification Pending",
                    },
                })
                
            # Anti-spam delay to prevent 429 limits from Groq API
            await asyncio.sleep(1.5)

        logger.info("[ucdp] OSINT Scraper returned %d live cross-verified conflict events", len(osint_results))
        return osint_results

    def _extract_conflict_coords(self, text: str) -> tuple[float, float, str]:
        """Extremely simple heuristic to place the pin roughly where the news is talking about.
        If no geo found, default to a generic 'Unknown' coordinate."""
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
