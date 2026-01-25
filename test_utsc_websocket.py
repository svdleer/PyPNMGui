#!/usr/bin/env python3
"""Test UTSC WebSocket streaming functionality."""
import asyncio
import json
import websockets
import requests
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:5050"
WS_URL = "ws://localhost:5050"
MAC = "fc:01:7c:bf:73:e3"
CMTS_IP = "172.16.6.212"
RF_PORT = 1079058432
COMMUNITY = "Z1gg0Sp3c1@l"

async def test_utsc_flow():
    """Test complete UTSC flow: WebSocket connect -> API trigger -> Data streaming."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting UTSC WebSocket test...")
    
    # Step 1: Connect WebSocket FIRST
    ws_url = f"{WS_URL}/ws/utsc/{MAC}?refresh=500&duration=60&rf_port={RF_PORT}&cmts_ip={CMTS_IP}&community={COMMUNITY}"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Connecting to WebSocket: {ws_url}")
    
    samples_received = 0
    messages_received = []
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ WebSocket connected")
            
            # Step 2: Wait for initial 'connected' message
            initial_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            data = json.loads(initial_msg)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Received: {data['type']} - {data.get('message', '')}")
            messages_received.append(data)
            
            if data['type'] != 'connected':
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ ERROR: Expected 'connected', got '{data['type']}'")
                return False
            
            # Step 3: Trigger UTSC via API (WebSocket is already listening)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Triggering UTSC API...")
            api_url = f"{BASE_URL}/api/pypnm/upstream/utsc/start/{MAC}"
            payload = {
                "cmts_ip": CMTS_IP,
                "rf_port_ifindex": RF_PORT,
                "community": COMMUNITY,
                "tftp_ip": "172.16.6.101",
                "trigger_mode": 2,
                "center_freq_hz": 50000000,
                "span_hz": 80000000,
                "num_bins": 800,
                "repeat_period_ms": 100,
                "freerun_duration_ms": 10000  # 10s test
            }
            
            response = requests.post(api_url, json=payload, timeout=10)
            if response.status_code == 200:
                result = response.json()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ API response: {result.get('status', 'unknown')}")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ API failed: {response.status_code}")
                return False
            
            # Step 4: Receive data for 15 seconds
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for spectrum data...")
            timeout = 15
            start_time = asyncio.get_event_loop().time()
            
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(msg)
                    msg_type = data.get('type', 'unknown')
                    
                    if msg_type == 'data':
                        samples_received += 1
                        if samples_received <= 3:  # Show first 3
                            freq_start = data['data']['frequencies'][0]
                            freq_end = data['data']['frequencies'][-1]
                            amp_range = f"{min(data['data']['amplitudes']):.1f} to {max(data['data']['amplitudes']):.1f}"
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Sample #{samples_received}: {len(data['data']['frequencies'])} points, freq {freq_start/1e6:.1f}-{freq_end/1e6:.1f} MHz, amp {amp_range} dBmV")
                    elif msg_type == 'buffering':
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⟳ {data['message']}")
                    elif msg_type == 'complete':
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Stream complete")
                        break
                    elif msg_type == 'error':
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ ERROR: {data['message']}")
                        return False
                    
                    messages_received.append(data)
                    
                except asyncio.TimeoutError:
                    if samples_received == 0:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠ Still waiting for data...")
                    continue
            
            # Results
            print(f"\n{'='*60}")
            print(f"Test Results:")
            print(f"  Total samples received: {samples_received}")
            print(f"  Total messages: {len(messages_received)}")
            print(f"  Message types: {set(m['type'] for m in messages_received)}")
            print(f"{'='*60}\n")
            
            if samples_received >= 3:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ SUCCESS: Received {samples_received} spectrum samples")
                return True
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ FAIL: Only received {samples_received} samples (expected >= 3)")
                return False
                
    except websockets.exceptions.WebSocketException as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ WebSocket error: {e}")
        return False
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_utsc_flow())
    exit(0 if success else 1)
