import asyncio
import logging
import json
from collectors.satellite_collector import SatelliteCollector

logging.basicConfig(level=logging.INFO)

async def test():
    c = SatelliteCollector()
    print("Testing SatelliteCollector (N2YO API)...")
    
    events = await c.collect()
    print(f"\nYielded {len(events)} events!")
    if events:
        print("\nSample Event (first 1):")
        for e in events[:1]:
            print(json.dumps(e, indent=2))

if __name__ == "__main__":
    asyncio.run(test())
