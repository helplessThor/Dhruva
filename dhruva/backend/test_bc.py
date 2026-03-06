import sys
import os

# Set up python path for local imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from dhruva.collectors.ucdp_collector import UCDPCollector

async def test():
    print("Testing UCDP _background_verify...")
    u = UCDPCollector()
    await u._background_verify("test-123", "Test Title", ["Test text"], "2023-10-10", "Test Country")
    print("Test finished!")

if __name__ == "__main__":
    asyncio.run(test())
