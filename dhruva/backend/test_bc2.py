import sys
import os
import asyncio

# Setup paths exactly like main.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.ucdp_collector import UCDPCollector

async def run_test():
    print("Initializing UCDPCollector...")
    # interval 900
    u = UCDPCollector(interval=900)
    
    event_obj = {
        "id": "ucdp-osint-123",
        "type": "ucdp",
        "description": "*[Pending AI]*",
        "metadata": {
            "base_verification": "SUSPECTED",
        }
    }
    u._cached_osint_events.append(event_obj)
    
    print("Calling _background_verify...")
    await u._background_verify("ucdp-osint-123", "Test military clash in Region X", ["Troops opened fire near border."], "2023-10-10", "Test Country")
    print("Verification result:")
    print(u._cached_osint_events[0])
    
if __name__ == "__main__":
    asyncio.run(run_test())
