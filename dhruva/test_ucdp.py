import asyncio
import logging
from collectors.ucdp_collector import UCDPCollector

logging.basicConfig(level=logging.WARNING)

async def main():
    c = UCDPCollector()
    print("Testing UCDP Collector RSS Scraping...")
    
    # Let's intercept the events before Groq
    import urllib.parse
    import xml.etree.ElementTree as ET
    from datetime import datetime, timezone, timedelta
    from email.utils import parsedate_to_datetime
    
    from collectors.ucdp_collector import CONFLICT_KEYWORDS, RSS_FEEDS
    events = []
    query_str = "(" + " OR ".join(f'"{kw}"' for kw in CONFLICT_KEYWORDS) + f") when:{UCDPCollector.FRESHNESS_HOURS}h"
    encoded_query = urllib.parse.quote(query_str)
    
    for base_feed in RSS_FEEDS:
        url = base_feed.format(query=encoded_query)
        import httpx
        try:
            resp = httpx.get(url, timeout=30.0)
            root = ET.fromstring(resp.text)
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=UCDPCollector.FRESHNESS_HOURS)
            
            for item in root.findall(".//item"):
                title = item.findtext("title") or ""
                pub_date_str = item.findtext("pubDate") or ""
                if not pub_date_str: continue
                pub_date = parsedate_to_datetime(pub_date_str)
                if pub_date.tzinfo is None: pub_date = pub_date.replace(tzinfo=timezone.utc)
                if pub_date < cutoff_time: continue
                
                title_lower = title.lower()
                if not any(kw.replace("\"", "") in title_lower for kw in CONFLICT_KEYWORDS):
                    continue
                    
                lat, lon, country = c._extract_conflict_coords(title_lower)
                events.append({
                    "title": title,
                    "inferred_country": country
                })
        except Exception as e:
            print(f"Error: {e}")
            
    print(f"Total Unique Articles Matching Keywords: {len(events)}")
    for e in events:
        print(f"[{e['inferred_country']}] {e['title']}")

if __name__ == "__main__":
    asyncio.run(main())
