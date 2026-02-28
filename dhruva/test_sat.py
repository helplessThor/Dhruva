import asyncio
import logging
import json
from collectors.satellite_collector import SatelliteCollector

logging.basicConfig(level=logging.INFO)

async def test():
    c = SatelliteCollector()
    print("Testing SatelliteCollector (N2YO API) over multiple iterations...")
    
    events = []
    for i in range(15):
        print(f"Iteration {i+1}...")
        res = await c.collect()
        if res:
            events.extend(res)
            print(f"Found {len(res)} satellites this iteration.")
        await asyncio.sleep(1) # tiny sleep to avoid spamming too fast in tests
        
    print(f"\nYielded a total of {len(events)} events!")
    if events:
        print("\nSample Event (first 1):")
        for e in events[:1]:
            print(json.dumps(e, indent=2))

if __name__ == "__main__":
    asyncio.run(test())
