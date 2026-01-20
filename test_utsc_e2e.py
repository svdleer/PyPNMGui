#!/usr/bin/env python3
"""
End-to-End UTSC Test - Automated monitoring of entire UTSC workflow
Tests: API trigger, WebSocket streaming, TFTP file creation, timing analysis
"""

import asyncio
import json
import time
import requests
import websockets
from datetime import datetime
import subprocess

# Test configuration
BACKEND_URL = "http://localhost:5051"
WEBSOCKET_URL = "ws://localhost:5051/ws/utsc"
MAC_ADDRESS = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT = 1074339840
TEST_DURATION = 65  # Slightly more than freerun_duration

class UTSCEndToEndTest:
    def __init__(self):
        self.websocket_messages = []
        self.tftp_files_before = set()
        self.tftp_files_after = set()
        self.test_start_time = None
        
    def get_tftp_files(self):
        """Get list of UTSC files via SSH"""
        try:
            mac_clean = MAC_ADDRESS.replace(':', '').lower()
            cmd = f'ssh -p 65001 access-engineering.nl "ls -1 /var/lib/tftpboot/utsc_{mac_clean}_* 2>/dev/null"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return set(line.strip() for line in result.stdout.split('\n') if line.strip())
            return set()
        except Exception as e:
            print(f"❌ Error getting TFTP files: {e}")
            return set()
    
    async def monitor_websocket(self):
        """Monitor WebSocket for UTSC spectrum data"""
        print(f"\n📡 Connecting to WebSocket: {WEBSOCKET_URL}/{MAC_ADDRESS}")
        
        try:
            async with websockets.connect(f"{WEBSOCKET_URL}/{MAC_ADDRESS}") as ws:
                print("✅ WebSocket connected")
                
                # Wait for messages
                start = time.time()
                while time.time() - start < TEST_DURATION:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        data = json.loads(message)
                        timestamp = time.time() - self.test_start_time
                        
                        if data.get('type') == 'spectrum':
                            self.websocket_messages.append({
                                'timestamp': timestamp,
                                'filename': data.get('filename'),
                                'has_plot': bool(data.get('plot'))
                            })
                            print(f"  📊 [{timestamp:.1f}s] Received spectrum: {data.get('filename')} (plot: {len(data.get('plot', ''))} bytes)")
                        elif data.get('type') == 'connected':
                            print(f"  ✅ [{timestamp:.1f}s] Connection confirmed: {data.get('message')}")
                        else:
                            print(f"  ℹ️  [{timestamp:.1f}s] Message: {data.get('type')}")
                            
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"  ⚠️  Error receiving message: {e}")
                        break
                        
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
    
    def trigger_utsc(self):
        """Trigger UTSC capture via API"""
        print(f"\n🚀 Triggering UTSC for {MAC_ADDRESS}")
        
        url = f"{BACKEND_URL}/api/pypnm/upstream/utsc/start/{MAC_ADDRESS}"
        payload = {
            "cmts_ip": CMTS_IP,
            "rf_port_ifindex": RF_PORT,
            "community": "Z1gg0Sp3c1@l",
            "tftp_ip": "172.16.6.101",
            "repeat_period_ms": 3000,
            "freerun_duration_ms": 60000,
            "trigger_count": 20
        }
        
        print(f"  Request: POST {url}")
        print(f"  Payload: {json.dumps(payload, indent=2)}")
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Success: {result.get('success')}")
                print(f"  Filename: {result.get('filename')}")
                print(f"  CMTS IP: {result.get('cmts_ip')}")
                return result.get('success', False)
            else:
                print(f"  ❌ Error: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ API request failed: {e}")
            return False
    
    def analyze_results(self):
        """Analyze test results"""
        print("\n" + "="*80)
        print("📊 TEST RESULTS ANALYSIS")
        print("="*80)
        
        # WebSocket analysis
        print(f"\n🌐 WebSocket Results:")
        print(f"  Total messages received: {len(self.websocket_messages)}")
        
        if self.websocket_messages:
            print(f"  First message at: {self.websocket_messages[0]['timestamp']:.2f}s")
            print(f"  Last message at: {self.websocket_messages[-1]['timestamp']:.2f}s")
            
            if len(self.websocket_messages) > 1:
                intervals = [
                    self.websocket_messages[i+1]['timestamp'] - self.websocket_messages[i]['timestamp']
                    for i in range(len(self.websocket_messages)-1)
                ]
                avg_interval = sum(intervals) / len(intervals)
                print(f"  Average interval: {avg_interval*1000:.1f}ms")
                print(f"  Min interval: {min(intervals)*1000:.1f}ms")
                print(f"  Max interval: {max(intervals)*1000:.1f}ms")
        
        # TFTP analysis
        new_files = self.tftp_files_after - self.tftp_files_before
        print(f"\n📁 TFTP Files:")
        print(f"  Files before test: {len(self.tftp_files_before)}")
        print(f"  Files after test: {len(self.tftp_files_after)}")
        print(f"  New files created: {len(new_files)}")
        
        if new_files:
            print(f"  New files:")
            for f in sorted(new_files)[-10:]:  # Show last 10
                print(f"    {f.split('/')[-1]}")
        
        # Verdict
        print(f"\n⚖️  VERDICT:")
        if len(self.websocket_messages) >= 15:
            print(f"  ✅ PASS - Received {len(self.websocket_messages)} spectrum updates (expected ~20)")
        elif len(self.websocket_messages) >= 5:
            print(f"  ⚠️  PARTIAL - Received only {len(self.websocket_messages)} updates (expected ~20)")
        else:
            print(f"  ❌ FAIL - Only {len(self.websocket_messages)} updates received")
        
        if len(new_files) >= 15:
            print(f"  ✅ PASS - Created {len(new_files)} TFTP files (expected ~20)")
        elif len(new_files) >= 5:
            print(f"  ⚠️  PARTIAL - Only {len(new_files)} TFTP files created")
        else:
            print(f"  ❌ FAIL - Only {len(new_files)} TFTP files created")
        
        print("="*80)
    
    async def run_test(self):
        """Run complete end-to-end test"""
        print("="*80)
        print("🧪 UTSC END-TO-END TEST")
        print("="*80)
        print(f"Test time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: {TEST_DURATION}s")
        
        # Get baseline TFTP files
        print("\n📸 Getting baseline TFTP file count...")
        self.tftp_files_before = self.get_tftp_files()
        print(f"  Baseline: {len(self.tftp_files_before)} files")
        
        # Start WebSocket monitoring in background
        self.test_start_time = time.time()
        ws_task = asyncio.create_task(self.monitor_websocket())
        
        # Wait a moment for WebSocket to connect
        await asyncio.sleep(1)
        
        # Trigger UTSC
        if not self.trigger_utsc():
            print("❌ Failed to trigger UTSC - aborting test")
            ws_task.cancel()
            return
        
        # Wait for test duration
        print(f"\n⏳ Monitoring for {TEST_DURATION} seconds...")
        print("   (UTSC configured for 60s with 3s intervals = ~20 captures expected)")
        
        for i in range(TEST_DURATION):
            await asyncio.sleep(1)
            if i % 10 == 0 and i > 0:
                print(f"   ... {i}s elapsed, {len(self.websocket_messages)} messages received so far")
        
        # Cancel WebSocket monitoring
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        
        # Get final TFTP files
        print("\n📸 Getting final TFTP file count...")
        await asyncio.sleep(2)  # Give TFTP a moment to finish writing
        self.tftp_files_after = self.get_tftp_files()
        print(f"  Final: {len(self.tftp_files_after)} files")
        
        # Analyze and report
        self.analyze_results()

async def main():
    test = UTSCEndToEndTest()
    await test.run_test()

if __name__ == "__main__":
    asyncio.run(main())
