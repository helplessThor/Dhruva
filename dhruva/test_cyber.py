import asyncio
import logging
import json
from collectors.cyber_collector import CyberCollector

logging.basicConfig(level=logging.INFO)

async def test():
    c = CyberCollector()
    print("Testing CyberCollector (ThreatFox)...")
    
    events = await c.collect()
    print(f"\nYielded {len(events)} events!")
    if events:
        print("\nSample Event (first 3):")
        for e in events[:3]:
            print(json.dumps(e, indent=2))

if __name__ == "__main__":
    asyncio.run(test())
