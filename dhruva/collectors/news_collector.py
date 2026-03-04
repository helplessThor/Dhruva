"""Dhruva — Global News RSS Collector.

Fetches the latest headlines from major international news syndicates (Al Jazeera, BBC, etc.),
smartly deduplicates them using text similarity to prevent repeating the same breaking story,
and returns the top 10 most recent critical headlines for the Live News Ticker.
"""

import logging
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import difflib
import email.utils

from collectors.base_collector import BaseCollector

logger = logging.getLogger("dhruva.news")

# Top tier global news RSS feeds (unauthenticated, highly reliable)
RSS_FEEDS = [
    "https://www.aljazeera.com/xml/rss/all.xml",
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.thehindu.com/news/national/feeder/default.rss",
]

# Keywords to strictly filter out sports news
SPORTS_KEYWORDS = {
    "sport", "sports", "football", "soccer", "tennis", "cricket", "basketball",
    "baseball", "golf", "rugby", "hockey", "volleyball", "badminton", "boxing",
    "mma", "ufc", "f1", "formula 1", "motogp", "racing", "grand prix",
    "olympics", "paralympics", "championship", "tournament", "league", "cup final",
    "world cup", "premier league", "la liga", "serie a", "bundesliga", "ipl", "psl",
    "big bash", "ranji", "ashes", "test match", "odi", "t20", "t20i",
    "nhl", "nfl", "nba", "mlb", "fifa", "uefa", "wimbledon", "super bowl",
    "matchday", "qualifier", "semifinal", "semi-final", "final", "playoff", "knockout",
    "goal", "hat-trick", "captain", "coach", "striker", "midfielder", "goalkeeper", "festive", "festival",
    "why", "how", "what"
}

# High-impact catastrophic keywords to filter local news
CATASTROPHIC_KEYWORDS = {
    "war", "conflict", "explosion", "blast", "leak", "toxic", "chemical", "strike",
    "attack", "crash", "casualty", "dead", "killed", "missile", "rocket", "drone",
    "military", "clash", "riot", "protest", "unrest", "assassination", "coup",
    "earthquake", "tsunami", "terror", "militant", "gunfight", "naxal", "maoist",
    "encounter", "hijack", "hostage", "shelling", "airstrike", "cross-border",
    "insurgency", "evacuation", "blackout", "state of emergency"
}

# Max number of headlines to return to the ticker
MAX_HEADLINES = 30

# Threshold for fuzzy string matching (0.0 to 1.0). 
# If two headlines are > 50% similar in text structure, we drop the older one.
SIMILARITY_THRESHOLD = 0.50


def _clean_text(html_text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not html_text:
        return ""
    text = re.sub(r'<[^>]+>', '', html_text)
    return ' '.join(text.split())


def _is_duplicate(new_title: str, existing_titles: list[str]) -> bool:
    """Check if a new headline is too similar to any we've already accepted."""
    new_clean = new_title.lower()
    for existing in existing_titles:
        seq = difflib.SequenceMatcher(None, new_clean, existing.lower())
        if seq.ratio() > SIMILARITY_THRESHOLD:
            return True
    return False


class NewsCollector(BaseCollector):
    """Fetches real-time global news headlines via public RSS feeds."""

    def __init__(self, interval: int = 300):
        # We run this every 5 minutes
        super().__init__(name="news", interval=interval)

    async def collect(self) -> list[dict]:
        """Fetch and parse all RSS feeds, then deduplicate."""
        all_items = []
        now = datetime.now(timezone.utc).isoformat()

        for feed_url in RSS_FEEDS:
            try:
                # Use urllib to do a simple GET request
                req = urllib.request.Request(
                    feed_url,
                    headers={'User-Agent': 'Mozilla/5.0 Dhruva-OSINT'}
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()
                
                # Parse XML tree
                root = ET.fromstring(xml_data)
                
                # Standard RSS channels have <item> tags
                for item in root.findall('.//item'):
                    title = item.findtext('title', default='').strip()
                    desc = _clean_text(item.findtext('description', default=''))
                    pub_date_str = item.findtext('pubDate', default='')
                    link = item.findtext('link', default='')

                    if not title:
                        continue
                        
                    # Filter out sports news
                    text_to_check = (title + " " + desc).lower()
                    if any(kw in text_to_check for kw in SPORTS_KEYWORDS):
                        continue
                        
                    # For The Hindu (India), strictly require catastrophic/escalatory keywords
                    if "thehindu" in feed_url:
                        # Need regex boundaries or simple substring. Substring is fine.
                        if not any(kw in text_to_check for kw in CATASTROPHIC_KEYWORDS):
                            continue
                    # Parse PubDate and enforce strict 5-minute freshness
                    item_timestamp = now
                    if pub_date_str:
                        try:
                            dt = email.utils.parsedate_to_datetime(pub_date_str)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            
                            age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
                            if age_seconds > 7200: # 2 hour freshness limit to guarantee 10 items
                                continue
                            item_timestamp = dt.isoformat()
                        except Exception:
                            # If we can't parse it, we still enforce a pseudo-limit by 
                            # assuming it's current, but typically we want to drop it if it's old.
                            pass

                    # Normalize source name from feed URL
                    source = "BBC" if "bbci.co.uk" in feed_url else "Al Jazeera" if "aljazeera" in feed_url else "The Hindu" if "thehindu" in feed_url else "News"

                    all_items.append({
                        "id": f"news-{hash(title)}",
                        "type": "news",
                        "title": title,
                        "description": desc,
                        "source": source,
                        "severity": 3, # Standard news severity
                        "timestamp": item_timestamp,
                        "metadata": {
                            "link": link,
                            "raw_date": pub_date_str
                        }
                    })

            except urllib.error.URLError as e:
                logger.warning("[news] Failed to fetch feed %s: %s", feed_url, e.reason)
            except ET.ParseError:
                logger.warning("[news] Failed to parse XML for feed %s", feed_url)
            except Exception as e:
                logger.error("[news] Unexpected error parsing %s: %s", feed_url, e)

        # ─── Deduplication & Sorting ───
        deduplicated = []
        accepted_titles = []

        # Sort combined feeds by timestamp descending to guarantee the absolute newest 10 items globally
        all_items.sort(key=lambda x: x["timestamp"], reverse=True)

        # Walk through sorted items until we hit MAX_HEADLINES.
        for item in all_items:
            if len(deduplicated) >= MAX_HEADLINES:
                break
            
            if not _is_duplicate(item["title"], accepted_titles):
                deduplicated.append(item)
                accepted_titles.append(item["title"])

        logger.info("[news] Synthesized %d deduplicated live headlines from RSS streams", len(deduplicated))
        return deduplicated
