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
]
class EarthquakeCollector(BaseCollector):
    """Fetches real-time earthquake data from USGS."""

    API_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"

    FRESHNESS_HOURS = 36
    OSINT_THROTTLE_SECONDS = 3600

    def __init__(self, interval: int = 30):
        super().__init__(name="earthquake", interval=interval)
        self.retention_hours = 12.0
        
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
        data = await self.fetch_json(self.API_URL)
        events = []
        now = datetime.now(timezone.utc)

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
            self._cached_osint_events = await self._scrape_osint_rss()
            self._last_osint_scrape = now
            
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
                    
                # Time within 2 hours AND distance roughly within 5 degrees (approx 500km)
                time_diff = abs((o_time - u_time).total_seconds())
                dist_sq = (o_lat - u_lat)**2 + (o_lon - u_lon)**2
                
                if time_diff < 7200 and dist_sq < 25.0:
                    is_duplicate = True
                    break
                    
            if not is_duplicate:
                filtered_osint.append(osint_ev)
            
        usgs_events.extend(filtered_osint)

        return usgs_events

    async def _scrape_osint_rss(self) -> list[dict]:
        # Aggregate news items by region to cross-verify and prevent Rate Limiting
        events_by_region = {}
        
        query_str = "(" + " OR ".join(f'"{kw}"' for kw in EARTHQUAKE_KEYWORDS) + f") when:{self.FRESHNESS_HOURS}h"
        encoded_query = urllib.parse.quote(query_str)
        
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
                        if not any(kw.replace("\"", "") in title_lower for kw in EARTHQUAKE_KEYWORDS):
                            continue
                            
                        # Extract hint
                        lat, lon, loc_name, mag = self._extract_earthquake_coords(title_lower)
                        if lat is None:
                            continue  # Drop unknown locations instead of rendering ghost coordinates
                        
                        if loc_name not in events_by_region:
                            events_by_region[loc_name] = {
                                "lat": lat,
                                "lon": lon,
                                "mag": mag,
                                "latest_time": pub_date,
                                "titles": [],
                                "links": set() 
                            }
                        
                        if pub_date > events_by_region[loc_name]["latest_time"]:
                            events_by_region[loc_name]["latest_time"] = pub_date
                            
                        events_by_region[loc_name]["titles"].append(title)
                        events_by_region[loc_name]["links"].add(link)
                        
                    except Exception as e:
                        logger.debug("[earthquake] Failed to parse RSS item: %s", e)
                        
            except Exception as e:
                logger.error("[earthquake] Failed to scrape RSS feed: %s", e)
                
        # Groq AI Verification
        osint_results = []
        for loc_name, data in events_by_region.items():
            link_list = list(data["links"])
            source_count = len(link_list)
            primary_title = data["titles"][0]
            
            ai_prompt = (
                f"You are a geophysical OSINT analyst observing global seismic reports.\n"
                f"Title: '{primary_title}'\n"
                f"Article Time: {data['latest_time'].isoformat()}\n\n"
                "Task: Verify if this is a real-world, current news report of an Earthquake.\n"
                "Extract the following information as strict JSON only.\n\n"
                "RULES:\n"
                "- Extract coordinates and location as accurately as possible.\n"
                "- Extract the earthquake magnitude strictly as a float.\n"
                "- Include the exact Date and Time of occurrence extracted from the text (using Article Time as a reference point). Use ISO 8601 format.\n\n"
                "Return format:\n"
                "{\n"
                '  "is_earthquake": true/false,\n'
                '  "reasoning": "1 sentence explanation.",\n'
                '  "magnitude": 5.4,\n'
                '  "exact_time": "2026-10-24T14:00:00Z", \n'
                '  "location_name": "CountryName / Region",\n'
                '  "lat": 1.23,\n'
                '  "lon": 4.56\n'
                "}"
            )
            try:
                ai_response = await self.ask_groq(ai_prompt)
                
                # Try safely extracting JSON chunk
                import re, json
                json_match = re.search(r"\{.*\}", ai_response, re.DOTALL)
                if json_match:
                    ai_response = json_match.group(0)
                
                result = json.loads(ai_response)
                
                if not result.get("is_earthquake"):
                    logger.debug("[earthquake] Groq AI rejected false positive: %s", result.get("reasoning", "No reason"))
                    continue
                    
                lat = result.get("lat")
                lon = result.get("lon")
                if lat is None or lon is None:
                    lat, lon = data["lat"], data["lon"]
                    
                mag = float(result.get("magnitude", data["mag"]))
                exact_time = result.get("exact_time") or data['latest_time'].isoformat()
                ai_loc_name = result.get("location_name", loc_name)
                reasoning = result.get("reasoning", "Verified as credible earthquake based on OSINT.")
                
                event_id = str(hash(ai_loc_name + exact_time + primary_title))[:10].replace("-", "")

                osint_results.append({
                    "id": f"eq-osint-{event_id}",
                    "type": "earthquake",
                    "latitude": lat,
                    "longitude": lon,
                    "severity": self._magnitude_to_severity(mag),
                    "timestamp": exact_time,
                    "source": "OSINT Scraper",
                    "title": f"[AI Verified] M{mag} Earthquake — {ai_loc_name}",
                    "description": f"[CONFIRMED] {primary_title}\n\n🤖 **[Groq AI Assessment]**\n{reasoning}\nMagnitude: {mag}\n*Sources: {source_count}*",
                    "metadata": {
                        "magnitude": mag,
                        "urls": link_list,
                        "location_name": ai_loc_name,
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "groq_verification": reasoning,
                    },
                })
            except Exception as e:
                err_str = str(e)
                if "rate_limit" in err_str or "tokens per day" in err_str:
                    logger.warning("[earthquake] Groq AI Rate Limit Reached! Using Fallback Strategy for '%s'", loc_name)
                else:
                    logger.debug("[earthquake] Failed to parse Groq OSINT response: %s", e)
                
                event_id = str(hash(loc_name + str(data['latest_time'])))[:10].replace("-", "")
                osint_results.append({
                    "id": f"eq-osint-fallback-{event_id}",
                    "type": "earthquake",
                    "latitude": data["lat"],
                    "longitude": data["lon"],
                    "severity": self._magnitude_to_severity(data["mag"]),
                    "timestamp": data['latest_time'].isoformat(),
                    "source": "OSINT Scraper",
                    "title": f"[Pending AI Verification] M{data['mag']} Earthquake — {loc_name}",
                    "description": f"[SUSPECTED] {primary_title}\n\n🤖 **[Groq AI Assessment]**\nPending AI Verification (Processing or Rate Limit Error)\nMagnitude: {data['mag']}\n*Sources: {source_count}*",
                    "metadata": {
                        "magnitude": data["mag"],
                        "urls": link_list,
                        "location_name": loc_name,
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "groq_verification": "AI Verification Pending",
                    },
                })
                
            # Anti-spam delay to prevent 429 limits from Groq API
            await asyncio.sleep(1.5)

        logger.info("[earthquake] OSINT Scraper returned %d verified earthquake events", len(osint_results))
        return osint_results

    def _extract_earthquake_coords(self, text: str) -> tuple[float, float, str, float]:
        """Fallback heuristics for earthquake extraction [lat, lon, location_name, mag]"""
        text = text.lower()
        mag = 4.0 # default
        import re
        m = re.search(r"magnitude\s+([\d\.]+)", text) or re.search(r"m\s?([\d\.]+)", text)
        if m:
            try: mag = float(m.group(1))
            except: pass
                
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
        
        # If no country detected safely return None to avoid ghost locations
        return None, None, None, mag
