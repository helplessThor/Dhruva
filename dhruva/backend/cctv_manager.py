"""Dhruva — CCTV Feed Manager
Selects the Top 4 most unstable countries from the CII engine and serves
their live YouTube CCTV feeds. Fallbacks to neighboring countries if no
reliable feed is found for a specific high-threat region.
"""

import logging
import random
import urllib.request
import urllib.parse
import re
import time
from typing import Dict, List, Optional
from backend.config import settings

logger = logging.getLogger("dhruva.cctv")

# Cache to prevent repeated YouTube scraping
_YOUTUBE_CACHE: Dict[str, str] = {}

_ROTATION_STATE = {
    "last_rotation_time": 0,
    "current_iso": None,
    "cached_feeds": []
}
ROTATION_INTERVAL = 2 * 3600  # 2 hours

def scrape_live_youtube_webcam(city: str, country: str) -> Optional[str]:
    """Dynamically scrape YouTube for a live webcam or feed in the specified city/country."""
    cache_key = f"{city}_{country}"
    if cache_key in _YOUTUBE_CACHE:
        return _YOUTUBE_CACHE[cache_key]
        
    # Introduce explicit delay to avoid getting rate-limited by YouTube if multiple grids fetch
    time.sleep(1.0)
        
    # Build fallback queries. Try exact city camera first, then broad country live stream.
    queries = [
        f"live camera {city} {country} street",
        f"live {country} news english",
        f"live {city} tv"
    ]
    
    for query in queries:
        encoded_query = urllib.parse.quote_plus(query)
        # sp=EgJAAQ%253D%253D filters YouTube search precisely to "Live" videos
        url = f"https://www.youtube.com/results?search_query={encoded_query}&sp=EgJAAQ%253D%253D"
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                html = response.read().decode('utf-8')
                match = re.search(r'var ytInitialData = (\{.*?\});</script>', html)
                if match:
                    import json
                    data = json.loads(match.group(1))
                    contents = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get('primaryContents', {}).get('sectionListRenderer', {}).get('contents', [])
                    if contents:
                        items = contents[0].get('itemSectionRenderer', {}).get('contents', [])
                        for item in items:
                            if 'videoRenderer' in item:
                                vr = item['videoRenderer']
                                title = vr.get('title', {}).get('runs', [{}])[0].get('text', '')
                                vid = vr.get('videoId', '')
                                
                                # Strict Validation: the video title must explicitly mention the city or country
                                # to avoid random proxy streams.
                                title_lower = title.lower()
                                city_match = city.lower() in title_lower and len(city) > 2
                                country_match = country.lower() in title_lower and len(country) > 2
                                
                                if city_match or country_match:
                                    _YOUTUBE_CACHE[cache_key] = vid
                                    return vid
        except Exception as e:
            logger.error(f"Failed to scrape YouTube for {query}: {e}")
            
    return None

# Known unstable region primary cities and their fallback neighbors
CCTV_FEEDS: Dict[str, Dict] = {
    # Highly Volatile / Conflict Zones (Primary Targets)
    "IR": {
        "name": "Tehran",
        "cities": ["Tehran", "Isfahan", "Mashhad", "Shiraz"],
        "video_ids": ["-zGuR1qVKrU"],
        "neighbors": ["IQ", "AF", "PK", "TM", "AZ", "AM", "TR"]
    },
    "UA": {
        "name": "Kyiv",
        "cities": ["Kyiv", "Kharkiv", "Odesa", "Dnipro"],
        "neighbors": ["PL", "RO", "SK", "HU"]
    },
    "PS": {
        "name": "Gaza",
        "cities": ["Gaza", "Rafah", "Khan Yunis", "Hebron"],
        "video_ids": ["4E-iFtUM2kk"],
        "neighbors": ["EG", "JO", "LB", "SY"]
    },
    "IL": {
        "name": "Tel Aviv",
        "cities": ["Tel Aviv", "Jerusalem", "Haifa", "Eilat"],
        "video_ids": ["gmtlJ_m2r5A"],
        "neighbors": ["EG", "JO", "LB", "SY"]
    },
    "RU": {
        "name": "Moscow",
        "cities": ["Moscow", "Saint Petersburg", "Novosibirsk", "Yekaterinburg"],
        "neighbors": ["BY", "KZ", "FI", "EE", "LV"]
    },
    "SY": {
        "name": "Damascus",
        "cities": ["Damascus", "Aleppo", "Homs", "Latakia"],
        "video_ids": ["4E-iFtUM2kk"],
        "neighbors": ["LB", "TR", "IQ", "JO"]
    },
    "YE": {
        "name": "Sana'a",
        "cities": ["Sana'a", "Aden", "Taiz", "Al Hudaydah"],
        "video_ids": ["4E-iFtUM2kk"],
        "neighbors": ["SA", "OM", "DJ"]
    },
    "SD": {
        "name": "Khartoum",
        "cities": ["Khartoum", "Omdurman", "Nyala", "Port Sudan"],
        "neighbors": ["EG", "ER", "ET", "SS", "TD", "CF"]
    },
    
    # Generic Global Capitals
    "US": {
        "name": "New York",
        "cities": ["New York", "Los Angeles", "Chicago", "Houston"],
        "neighbors": ["CA", "MX"]
    },
    "CN": {
        "name": "Beijing",
        "cities": ["Beijing", "Shanghai", "Shenzhen", "Guangzhou"],
        "neighbors": ["RU", "MN", "KP", "VN", "MM"]
    },
    "GB": {
        "name": "London",
        "cities": ["London", "Birmingham", "Manchester", "Glasgow"],
        "neighbors": ["IE", "FR"]
    },
    "JP": {
        "name": "Tokyo",
        "cities": ["Tokyo", "Yokohama", "Osaka", "Nagoya"],
        "neighbors": ["KR", "KP"]
    },
    "KR": {
        "name": "Seoul",
        "cities": ["Seoul", "Busan", "Incheon", "Daegu"],
        "neighbors": ["KP", "JP", "CN"]
    },
    "TR": {
        "name": "Istanbul",
        "cities": ["Istanbul", "Ankara", "Izmir", "Bursa"],
        "neighbors": ["GR", "BG", "SY", "IQ", "IR", "AM", "GE"]
    },
    "EG": {
        "name": "Cairo",
        "cities": ["Cairo", "Alexandria", "Giza", "Shubra El Kheima"],
        "neighbors": ["SD", "LY", "PS", "IL"]
    },
    "SA": {
        "name": "Riyadh",
        "cities": ["Riyadh", "Jeddah", "Mecca", "Medina"],
        "neighbors": ["YE", "OM", "AE", "QA", "KW", "IQ", "JO"]
    },
    "LB": {
        "name": "Beirut",
        "cities": ["Beirut", "Tripoli", "Sidon", "Tyre"],
        "video_ids": ["4E-iFtUM2kk"],
        "neighbors": ["SY", "IL", "CY"]
    },
    "PL": {
        "name": "Warsaw",
        "cities": ["Warsaw", "Kraków", "Łódź", "Wrocław"],
        "neighbors": ["UA", "BY", "LT", "RU", "DE", "CZ", "SK"]
    },
    "FR": {
        "name": "Paris",
        "cities": ["Paris", "Marseille", "Lyon", "Toulouse"],
        "neighbors": ["ES", "BE", "DE", "CH", "IT"]
    },
    "IT": {
        "name": "Rome",
        "cities": ["Rome", "Milan", "Naples", "Turin"],
        "neighbors": ["FR", "CH", "AT", "SI"]
    },
    "IN": {
        "name": "Mumbai",
        "cities": ["Mumbai", "Delhi", "Bangalore", "Hyderabad"],
        "neighbors": ["PK", "CN", "NP", "BT", "BD", "MM"]
    },
    "PK": {
        "name": "Islamabad",
        "cities": ["Islamabad", "Karachi", "Lahore", "Faisalabad"],
        "neighbors": ["IN", "AF", "IR", "CN"]
    },
}

def _get_feed_for_country(iso2: str, country_name: str, index: int = 0, visited: set = None) -> Optional[Dict]:
    """Recursively search for a valid video feed, falling back to neighbors."""
    if visited is None:
        visited = set()
        
    if iso2 in visited:
        return None
    visited.add(iso2)
    
    country_data = CCTV_FEEDS.get(iso2)
    
    # Base Case: Try and scrape a dynamic video
    if country_data:
        cities = country_data.get("cities", [country_data["name"]])
        city = cities[index % len(cities)]
        video_ids = country_data.get("video_ids", [])
        
        video_id = None
        if video_ids:
            # If explicit links are provided, rotate through them
            video_id = video_ids[index % len(video_ids)]
        else:
            video_id = scrape_live_youtube_webcam(city, country_name)
            
        if video_id:
            return {
            "country": country_name, # Display the Originally requested country name, even if neighbor feed
            "iso2": iso2,
            "city": city,
            "video_id": f"https://www.youtube.com/embed/{video_id}?autoplay=1&mute=1",
            "is_fallback": len(visited) > 1 # True if we recursed
        }
        
    # Recursive Case: Try neighbors
    if country_data and country_data.get("neighbors"):
        for neighbor_iso in country_data["neighbors"]:
            result = _get_feed_for_country(neighbor_iso, country_name, index, visited)
            if result:
                # If we found a neighbor video, annotate that it's a proxy view
                if not result.get("actual_country_iso"):
                    result["actual_country_iso"] = neighbor_iso
                    result["subtitle"] = f"Neighboring Proxy View: {CCTV_FEEDS.get(neighbor_iso, {}).get('name', 'Unknown')}, {neighbor_iso}"
                return result
                
    # If no neighbors or all neighbors exhausted, return default fallback
    return None

def get_top_cctv_feeds(cii_results: list[dict], count=4) -> list[dict]:
    """
    Given the computed CII results (sorted highest instability first),
    return exactly `count` CCTV feed objects for the MOST unstable country.
    If the target is actively at war, `count` dynamically shifts to match war severity (min 2, max 4).
    Rotates every 2-3 hours.
    """
    global _ROTATION_STATE
    now = time.time()
    
    if now - _ROTATION_STATE["last_rotation_time"] < ROTATION_INTERVAL and _ROTATION_STATE["cached_feeds"]:
        cached = _ROTATION_STATE["cached_feeds"]
        # Update current CII scores visually without rotating the streams
        for c in cii_results:
            if c.get("iso2") == _ROTATION_STATE["current_iso"]:
                for f in cached:
                    f["cii_score"] = c.get("score", 0)
                    f["cii_label"] = c.get("label", "NOMINAL")
                    f["cii_color"] = c.get("color", "#00cc88")
                    f["war_severity"] = c.get("war_severity", 0)
                break
        return cached

    # Time to rotate! Focus on the topmost unstable country that we support.
    feeds = []
    
    target = None
    for c in cii_results:
        # We only want to target countries we have explicit city lists for,
        # otherwise we end up with generic fallback streams (like 4 feeds of Andorra)
        if c.get("iso2") in CCTV_FEEDS:
            target = c
            break
            
    # Absolute fallback to US if literally nothing matches
    if not target and cii_results:
        target = cii_results[0]
        
    iso2 = target.get("iso2") if target else "US"
    c_name = target.get("country", iso2) if target else "United States"
    c_score = target.get("score", 0) if target else 0
    c_label = target.get("label", "NOMINAL") if target else "NOMINAL"
    c_color = target.get("color", "#00cc88") if target else "#00cc88"
    c_war_severity = target.get("war_severity", 0) if target else 0
    
    # The user specifically requested exactly ONE feed globally, utilizing "-zGuR1qVKrU"
    count = 1
    
    feeds.append({
        "country": c_name,
        "iso2": iso2,
        "city": "OSINT Central Command" if c_war_severity > 0 else f"{c_name} HQ",
        "video_id": "https://www.youtube.com/embed/-zGuR1qVKrU?autoplay=1&mute=1",
        "is_fallback": True,
        "subtitle": "Global War Tracking Feed",
        "cii_score": c_score,
        "cii_label": c_label,
        "cii_color": c_color,
        "war_severity": c_war_severity
    })
            
    _ROTATION_STATE["last_rotation_time"] = now
    _ROTATION_STATE["current_iso"] = iso2
    _ROTATION_STATE["cached_feeds"] = feeds
            
    return feeds
