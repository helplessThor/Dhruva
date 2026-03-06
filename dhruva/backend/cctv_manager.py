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
from typing import Dict, List, Optional
from backend.config import settings

logger = logging.getLogger("dhruva.cctv")

# Cache to prevent repeated YouTube scraping
_YOUTUBE_CACHE: Dict[str, str] = {}

def scrape_live_youtube_webcam(city: str, country: str) -> Optional[str]:
    """Dynamically scrape YouTube for a live webcam or feed in the specified city/country."""
    cache_key = f"{city}_{country}"
    if cache_key in _YOUTUBE_CACHE:
        return _YOUTUBE_CACHE[cache_key]
        
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
# We no longer hardcode video IDs; we dynamically scrape them!
CCTV_FEEDS: Dict[str, Dict] = {
    # Highly Volatile / Conflict Zones (Primary Targets)
    "UA": {
        "name": "Kyiv",
        "neighbors": ["PL", "RO", "SK", "HU"]
    },
    "PS": {
        "name": "Gaza",
        "neighbors": ["EG", "JO", "LB", "SY"]
    },
    "IL": {
        "name": "Tel Aviv",
        "neighbors": ["EG", "JO", "LB", "SY"]
    },
    "RU": {
        "name": "Moscow",
        "neighbors": ["BY", "KZ", "FI", "EE", "LV"]
    },
    "SY": {
        "name": "Damascus",
        "neighbors": ["LB", "TR", "IQ", "JO"]
    },
    "YE": {
        "name": "Sana'a",
        "neighbors": ["SA", "OM", "DJ"]
    },
    "SD": {
        "name": "Khartoum",
        "neighbors": ["EG", "ER", "ET", "SS", "TD", "CF"]
    },
    
    # Generic Global Capitals
    "US": {
        "name": "New York",
        "neighbors": ["CA", "MX"]
    },
    "CN": {
        "name": "Beijing",
        "neighbors": ["RU", "MN", "KP", "VN", "MM"]
    },
    "GB": {
        "name": "London",
        "neighbors": ["IE", "FR"]
    },
    "JP": {
        "name": "Tokyo",
        "neighbors": ["KR", "KP"]
    },
    "KR": {
        "name": "Seoul",
        "neighbors": ["KP", "JP", "CN"]
    },
    "TR": {
        "name": "Istanbul",
        "neighbors": ["GR", "BG", "SY", "IQ", "IR", "AM", "GE"]
    },
    "EG": {
        "name": "Cairo",
        "neighbors": ["SD", "LY", "PS", "IL"]
    },
    "SA": {
        "name": "Riyadh",
        "neighbors": ["YE", "OM", "AE", "QA", "KW", "IQ", "JO"]
    },
    "LB": {
        "name": "Beirut",
        "neighbors": ["SY", "IL", "CY"]
    },
    "PL": {
        "name": "Warsaw",
        "neighbors": ["UA", "BY", "LT", "RU", "DE", "CZ", "SK"]
    },
    "FR": {
        "name": "Paris",
        "neighbors": ["ES", "BE", "DE", "CH", "IT"]
    },
    "IT": {
        "name": "Rome",
        "neighbors": ["FR", "CH", "AT", "SI"]
    },
    "IN": {
        "name": "Mumbai",
        "neighbors": ["PK", "CN", "NP", "BT", "BD", "MM"]
    },
    "PK": {
        "name": "Islamabad",
        "neighbors": ["IN", "AF", "IR", "CN"]
    },
}

def _get_feed_for_country(iso2: str, country_name: str, visited: set = None) -> Optional[Dict]:
    """Recursively search for a valid video feed, falling back to neighbors."""
    if visited is None:
        visited = set()
        
    if iso2 in visited:
        return None
    visited.add(iso2)
    
    country_data = CCTV_FEEDS.get(iso2)
    
    # Base Case: Try and scrape a dynamic video
    if country_data:
        video_id = scrape_live_youtube_webcam(country_data["name"], country_name)
        if video_id:
            return {
            "country": country_name, # Display the Originally requested country name, even if neighbor feed
            "iso2": iso2,
            "city": country_data["name"],
            "video_id": f"https://www.youtube.com/embed/{video_id}?autoplay=1&mute=1",
            "is_fallback": len(visited) > 1 # True if we recursed
        }
        
    # Recursive Case: Try neighbors
    if country_data and country_data.get("neighbors"):
        for neighbor_iso in country_data["neighbors"]:
            result = _get_feed_for_country(neighbor_iso, country_name, visited)
            if result:
                # If we found a neighbor video, annotate that it's a proxy view
                if not result.get("actual_country_iso"):
                    result["actual_country_iso"] = neighbor_iso
                    result["subtitle"] = f"Neighboring Proxy View: {CCTV_FEEDS[neighbor_iso]['name']}, {neighbor_iso}"
                return result
                
    # If no neighbors or all neighbors exhausted, return default fallback
    return None

def get_top_cctv_feeds(cii_results: list[dict], count=4) -> list[dict]:
    """
    Given the computed CII results (sorted highest instability first),
    return exactly `count` CCTV feed objects.
    """
    feeds = []
    used_isos = set()
    
    # 1. Try to fulfill the requested count with the most unstable countries
    for c in cii_results:
        if len(feeds) >= count:
            break
            
        iso2 = c.get("iso2")
        if not iso2 or iso2 in used_isos:
            continue
            
        feed = _get_feed_for_country(iso2, c.get("country", iso2))
        if feed:
            feed["cii_score"] = c.get("score", 0)
            feed["cii_label"] = c.get("label", "LOW")
            feed["cii_color"] = c.get("color", "#00cc88")
            feeds.append(feed)
            used_isos.add(iso2)
            
    # 2. If we didn't find 4 solid feeds, backfill with top global capitals
    fallbacks = ["US", "GB", "FR", "JP", "CN", "TR"]
    for fb_iso in fallbacks:
        if len(feeds) >= count:
            break
        if fb_iso in used_isos:
            continue
            
        feed = _get_feed_for_country(fb_iso, fb_iso) # City name acts as country name here
        if feed:
            feed["cii_score"] = 0
            feed["cii_label"] = "NOMINAL (Fallback)"
            feed["cii_color"] = "#00cc88"
            feed["country"] = fb_iso # It's a fallback, so just label it
            feeds.append(feed)
            used_isos.add(fb_iso)
            
    return feeds
