import asyncio
import httpx
import json

THREATFOX_API_URL = "https://threatfox-api.abuse.ch/api/v1/"
IP_API_BATCH_URL  = "http://ip-api.com/batch"

# Get key from config
import sys
sys.path.append('c:\\Users\\Kuntal\\Desktop\\Projects\\WorldView\\dhruva\\backend')
from config import settings

async def main():
    api_key = getattr(settings, "threatfox_api_key", "")
    print(f"API Key present: {bool(api_key)}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Hit ThreatFox
        headers = {"Auth-Key": api_key}
        payload = {"query": "get_iocs", "days": 1}
        print("Fetching ThreatFox...")
        resp = await client.post(THREATFOX_API_URL, headers=headers, json=payload)
        data = resp.json()
        
        iocs_data = data.get("data", [])
        print(f"Total RAW IOCs returned: {len(iocs_data)}")
        
        # Step 2: Filter IP IOCs
        ip_iocs = []
        for ioc in iocs_data:
            ioc_type = ioc.get("ioc_type", "")
            if ioc_type in ("ip:port", "ipv4"):
                raw_ioc = ioc.get("ioc", "")
                clean_ip = raw_ioc.split(":")[0] if ":" in raw_ioc else raw_ioc
                ip_iocs.append(clean_ip)
                
        print(f"Total IP (geolocatable) IOCs: {len(ip_iocs)}")
        
        if not ip_iocs:
            return
            
        unique_ips = list(set(ip_iocs))
        print(f"Total UNIQUE IPs: {len(unique_ips)}")
        
        batch = unique_ips[:100]
        print(f"Sending first batch of {len(batch)} to IP-API...")
        
        resp = await client.post(IP_API_BATCH_URL, json=batch)
        geo_results = resp.json()
        
        success_count = sum(1 for r in geo_results if r.get("status") == "success")
        fail_count = len(geo_results) - success_count
        print(f"IP-API Results: {success_count} success, {fail_count} failed")
        
        if fail_count > 0:
            failed_reasons = [r.get("message") for r in geo_results if r.get("status") != "success"]
            print(f"Fail Messaages: {set(failed_reasons)}")
            

if __name__ == "__main__":
    asyncio.run(main())
