import asyncio
from collectors.ucdp_collector import UCDPCollector
import logging
import json

logging.basicConfig(level=logging.INFO)

async def test():
    c = UCDPCollector()
    
    async for events in c.start():
        print(f"Yielded {len(events)} events!")
        if events:
            print(json.dumps(events[0], indent=2))
        break

if __name__ == "__main__":
    asyncio.run(test())
