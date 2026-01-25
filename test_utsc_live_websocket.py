#!/usr/bin/env python3
"""Test UTSC Live WebSocket functionality end-to-end."""

import asyncio
import json
import time
import requests
import websockets

# Test configuration
SERVER_URL = "http://localhost:5050"
WS_URL = "ws://localhost:5050"
MAC_ADDRESS = "fc:01:7c:bf:73:e3"
CMTS_IP = "172.16.6.212"
RF_PORT = 1079058432
COMMUNITY = "Z1gg0Sp3c1@l"
TFTP_IP = "172.16.6.101"

async def test_utsc_websocket():
    """Test UTSC WebSocket end-to-end."""
    print("=" * 80)
    print("UTSC WebSocket Live Test")
    print("=" * 80)
    
    # Step 1: Trigger UTSC via API
    print(f"\n[1/4] Triggering UTSC for {MAC_ADDRESS}...")
    api_url = f"{SERVER_URL}/api/pypnm/upstream/utsc/start/{MAC_ADDRESS}"
    payload = {
        "cmts_ip": CMTS_IP,
        "rf_port_ifindex": RF_PORT,
        "community": COMMUNITY,
        "tftp_ip": TFTP_IP,
        "trigger_mode": 2,  # Freerun
        "center_freq_hz": 50000000,
        "span_hz": 80000000,
        "num_bins": 3200,
        "repeat_period_ms": 1000,  # 1 second between captures
        "freerun_duration_ms": 120000  # 120 seconds total
    }
    
    try:
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        api_result = response.json()
        print(f"✓ API Response: {api_result.get('success', False)}")
        if not api_result.get('success'):
            print(f"✗ API Error: {api_result.get('error', 'Unknown')}")
            return False
    except Exception as e:
        print(f"✗ API call failed: {e}")
        return False
    
    # Step 2: Connect WebSocket immediately
    print(f"\n[2/4] Connecting WebSocket...")
    ws_url = f"{WS_URL}/ws/utsc/{MAC_ADDRESS}?refresh=500&duration=120&rf_port={RF_PORT}&cmts_ip={CMTS_IP}&community={COMMUNITY}"
    
    try:
        async with websockets.connect(ws_url, ping_interval=10, ping_timeout=5) as websocket:
            print(f"✓ WebSocket connected")
            
            # Step 3: Wait for connected message
            print(f"\n[3/4] Waiting for connection confirmation...")
            msg = await asyncio.wait_for(websocket.recv(), timeout=5)
            data = json.loads(msg)
            
            if data.get('type') == 'connected':
                print(f"✓ Connection confirmed: {data.get('message')}")
            else:
                print(f"✗ Unexpected message: {data}")
                return False
            
            # Step 4: Wait for spectrum data (skip buffering messages)
            print(f"\n[4/4] Collecting 60 spectrum samples...")
            spectrum_count = 0
            buffering_count = 0
            start_time = time.time()
            timeout = 130  # 130 second timeout for 120s capture
            saved_samples = []
            
            while time.time() - start_time < timeout:
                try:
                    msg = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data = json.loads(msg)
                    
                    if data.get('type') == 'spectrum':
                        spectrum_count += 1
                        
                        # Save raw_data if available
                        if 'raw_data' in data:
                            saved_samples.append({
                                'timestamp': data.get('timestamp'),
                                'filename': data.get('filename'),
                                'frequencies': data['raw_data'].get('frequencies', []),
                                'amplitudes': data['raw_data'].get('amplitudes', [])
                            })
                        
                        if spectrum_count == 1:
                            print(f"✓ First spectrum data received!")
                            raw = data.get('raw_data', {})
                            print(f"  - Frequencies: {len(raw.get('frequencies', []))} points")
                            print(f"  - Amplitudes: {len(raw.get('amplitudes', []))} points")
                        
                        if spectrum_count % 10 == 0:
                            print(f"  Collected {spectrum_count}/60 samples...")
                        
                        if spectrum_count >= 60:
                            print(f"✓ Collected {spectrum_count} spectrum samples")
                            
                            # Save to file
                            output_file = f"/tmp/utsc_samples_{int(time.time())}.json"
                            with open(output_file, 'w') as f:
                                json.dump(saved_samples, f, indent=2)
                            
                            print(f"✓ Saved to: {output_file}")
                            print(f"\n{'=' * 80}")
                            print("✓✓✓ TEST PASSED ✓✓✓")
                            print(f"{'=' * 80}")
                            return True
                    
                    elif data.get('type') == 'buffering':
                        buffering_count += 1
                        if buffering_count % 5 == 0:
                            print(f"  Buffering... ({data.get('buffer_size', 0)}/3)")
                    
                    elif data.get('type') == 'error':
                        print(f"✗ Error from server: {data.get('message')}")
                        return False
                
                except asyncio.TimeoutError:
                    print(f"  Still waiting... ({int(time.time() - start_time)}s elapsed)")
                    continue
            
            print(f"\n✗ Timeout: Only received {spectrum_count} spectrum samples in {timeout}s")
            return False
    
    except Exception as e:
        print(f"✗ WebSocket error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_utsc_websocket())
    exit(0 if result else 1)
