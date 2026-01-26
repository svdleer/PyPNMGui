#!/usr/bin/env python3
"""Simple WebSocket test for UTSC streaming"""

import asyncio
import websockets
import json
import requests
import time

# Configuration
WEBSOCKET_URL = "ws://172.16.6.101:5050/ws/utsc/fc:01:7c:bf:73:e3"
API_URL = "http://172.16.6.101:5050/api/utsc/start"
MAC = "fc:01:7c:bf:73:e3"
RF_PORT = 1079058432
CMTS_IP = "172.16.6.212"
COMMUNITY = "Z1gg0Sp3c1@l"

async def test_utsc():
    """Test UTSC WebSocket connection"""
    print("=" * 80)
    print("UTSC WebSocket Test")
    print("=" * 80)
    
    # Build WebSocket URL with parameters
    ws_url = f"{WEBSOCKET_URL}?refresh=500&duration=60&rf_port={RF_PORT}&cmts_ip={CMTS_IP}&community={COMMUNITY}"
    print(f"\n📡 Connecting to: {ws_url}\n")
    
    try:
        async with websockets.connect(ws_url) as ws:
            print("✅ WebSocket connected!\n")
            
            # Trigger UTSC via API
            print("🚀 Triggering UTSC via API...")
            api_params = {
                'mac_address': MAC,
                'rf_port': RF_PORT,
                'cmts_ip': CMTS_IP,
                'community': COMMUNITY
            }
            response = requests.post(API_URL, json=api_params)
            print(f"   API response: {response.status_code} - {response.text}\n")
            
            # Listen for messages
            message_count = 0
            spectrum_count = 0
            start_time = time.time()
            
            print("📥 Listening for messages...\n")
            
            while time.time() - start_time < 30:  # Listen for 30 seconds
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    message_count += 1
                    data = json.parse(message)
                    
                    msg_type = data.get('type', 'unknown')
                    elapsed = time.time() - start_time
                    
                    if msg_type == 'connected':
                        print(f"[{elapsed:6.1f}s] 🔗 {data.get('message')}")
                    
                    elif msg_type == 'buffering':
                        buffer_size = data.get('buffer_size', 0)
                        target = data.get('target', 0)
                        print(f"[{elapsed:6.1f}s] ⏳ Buffering... {buffer_size}/{target} samples")
                    
                    elif msg_type == 'buffering_complete':
                        print(f"[{elapsed:6.1f}s] ✅ {data.get('message')}")
                    
                    elif msg_type == 'spectrum':
                        spectrum_count += 1
                        raw_data = data.get('raw_data', {})
                        bins_count = len(raw_data.get('bins', []))
                        buffer_size = data.get('buffer_size', 0)
                        print(f"[{elapsed:6.1f}s] 📊 Spectrum #{spectrum_count}: {bins_count} bins, buffer={buffer_size}")
                        
                        if spectrum_count == 1:
                            print(f"         First spectrum details:")
                            print(f"         - freq_start_hz: {raw_data.get('freq_start_hz')}")
                            print(f"         - freq_step_hz: {raw_data.get('freq_step_hz')}")
                            print(f"         - bins[0]: {raw_data.get('bins', [None])[0]}")
                    
                    elif msg_type == 'heartbeat':
                        buffer_size = data.get('buffer_size', 0)
                        print(f"[{elapsed:6.1f}s] 💓 Heartbeat (buffer={buffer_size})")
                    
                    elif msg_type == 'error':
                        print(f"[{elapsed:6.1f}s] ❌ ERROR: {data.get('message')}")
                        break
                    
                    else:
                        print(f"[{elapsed:6.1f}s] ❓ Unknown message type: {msg_type}")
                
                except asyncio.TimeoutError:
                    continue
            
            print("\n" + "=" * 80)
            print(f"Test complete!")
            print(f"  Total messages: {message_count}")
            print(f"  Spectrum frames: {spectrum_count}")
            print("=" * 80)
            
            if spectrum_count > 0:
                print("✅ SUCCESS - Spectrum data received!")
            else:
                print("❌ FAILED - No spectrum data received")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_utsc())
