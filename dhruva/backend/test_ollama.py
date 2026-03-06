import asyncio
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ai_service import ai_service
from backend.config import settings

async def main():
    print(f"Testing Local Ollama Integration at {settings.ollama_url} with model {settings.ollama_model}")
    print("---------------------------------------------------------")
    
    print("Test 1: Normal Naval Extraction")
    title = "Deployments: USS Nimitz Carrier Strike Group enters Mediterranean Sea"
    texts = ["USS Nimitz Carrier Strike Group has entered the Mediterranean Sea today", "The carrier group is on a scheduled deployment"]
    time_str = "2023-10-24T12:00:00Z"
    
    res = await ai_service.verify_and_extract_event(title, texts, time_str, event_type="naval")
    print(f"Result: {res}")
    print("---------------------------------------------------------")
    
    print("Test 2: Earthquake Extraction")
    title = "Magnitude 6.8 Earthquake hits off the coast of Japan"
    texts = ["A 6.8 magnitude tremor was reported in Tokyo early this morning.", "No tsunami warning issued."]
    
    res_eq = await ai_service.verify_and_extract_event(title, texts, time_str, event_type="earthquake")
    print(f"Result: {res_eq}")
    print("---------------------------------------------------------")

    print("Test 3: Conflict/UCDP Extraction")
    title = "Heavy artillery fire reported at the Line of Control"
    texts = ["Troops cross border fire today along the line of control in Kashmir.", "The skirmish left several injured."]
    
    res_conf = await ai_service.verify_and_extract_event(title, texts, time_str, event_type="conflict")
    print(f"Result: {res_conf}")
    print("---------------------------------------------------------")

    print("Test 4: NOTAM / Airspace Closure Extraction")
    title = "Flights grounded in Middle East due to missile tests"
    texts = ["Several airlines diverted flights today over civil aviation warnings in the Middle East.", "Airspace closed entirely."]
    
    res_notam = await ai_service.verify_and_extract_event(title, texts, time_str, event_type="notam")
    print(f"Result: {res_notam}")
    print("---------------------------------------------------------")

    print("Test 5: Deduplication")
    event_a = {"description": "Massive earthquake strikes near Tokyo, Japan measuring 6.8 magnitude."}
    event_b = {"description": "A 6.8 magnitude tremor was felt in Tokyo early this morning."}
    
    is_dup = await ai_service.deduplicate_events(event_a, event_b)
    print(f"Are they duplicates? {is_dup}")
    print("---------------------------------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
