#!/usr/bin/env python3
import asyncio
import websockets
import json
import requests
import time

WEBSOCKET_URL = "ws://172.16.6.101:5050/ws/utsc/fc:01:7c:bf:73:e3?refresh=500&duration=20&rf_port=1079058432&cmts_ip=172.16.6.212&community=Z1gg0Sp3c1%40l"
API_URL = "http://172.16.6.101:5050/api/utsc/trigger"

async def test():
    print("Connecting to WebSocket...")
    async with websockets.connect(WEBSOCKET_URL) as ws:
        print("✓ WebSocket connected!")
        
        # Trigger UTSC via API
        print("Triggering UTSC via API...")
        response = requests.post(API_URL, json={
            "cmts_ip": "172.16.6.212",
            "rf_port": 1079058432,
            "community": "Z1gg0Sp3c1@l"
        })
        print(f"✓ API response: {response.status_code}")
        
        # Listen for messages
        message_count = 0
        spectrum_count = 0
        start = time.time()
        
        while time.time() - start < 15:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)
                message_count += 1
                
                if data.get("type") == "spectrum":
                    spectrum_count += 1
                    print(f"✓✓✓ SPECTRUM #{spectrum_count}: {len(data.get('raw_data', {}).get('bins', []))} bins")
                else:
                    print(f"Message #{message_count}: {data.get('type')}")
                    
            except asyncio.TimeoutError:
                continue
        
        print(f"\n=== SUMMARY ===")
        print(f"Total messages: {message_count}")
        print(f"Spectrum frames: {spectrum_count}")
        if spectrum_count == 0:
            print("❌ NO SPECTRUM DATA RECEIVED!")
        else:
            print("✓✓✓ SUCCESS!")

asyncio.run(test())
