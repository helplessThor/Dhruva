import asyncio
import json
from collectors.war_collector import WarCollector

async def main():
    collector = WarCollector()
    events = await collector.collect()
    print(f"Fetched {len(events)} war events.")
    for e in events[:5]:
        print(f"---")
        print(f"{e.get('metadata', {}).get('country_iso2')}: {e.get('title')} [Sev: {e.get('severity')}]")
        print(f"Details: {e.get('description')}")

if __name__ == "__main__":
    asyncio.run(main())
