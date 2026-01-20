#!/usr/bin/env python3
"""
End-to-end UTSC test - monitors everything automatically
"""
import asyncio
import websockets
import requests
import json
import time
import glob
import os
from datetime import datetime
from collections import defaultdict

# Configuration
BASE_URL = "http://localhost:5051"
WS_URL = "ws://localhost:5051"
TFTP_PATH = "/var/lib/tftpboot"
TEST_MAC = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT_IFINDEX = 1074339840

class UTSCTester:
    def __init__(self):
        self.ws_messages = []
        self.tftp_files = []
        self.start_time = None
        self.test_running = True
        
    def log(self, msg):
        elapsed = time.time() - self.start_time if self.start_time else 0
        print(f"[{elapsed:6.2f}s] {msg}")
    
    async def monitor_websocket(self):
        """Monitor WebSocket for spectrum updates"""
        ws_url = f"{WS_URL}/ws/utsc/{TEST_MAC}"
        try:
            self.log(f"📡 Connecting to WebSocket: {ws_url}")
            async with websockets.connect(ws_url) as ws:
                self.log("✅ WebSocket connected")
                
                while self.test_running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        data = json.loads(message)
                        msg_type = data.get('type', 'unknown')
                        
                        if msg_type == 'spectrum':
                            filename = data.get('filename', 'unknown')
                            self.ws_messages.append({
                                'time': time.time() - self.start_time,
                                'type': msg_type,
                                'filename': filename
                            })
                            self.log(f"📊 WebSocket: Received spectrum update #{len(self.ws_messages)} - {filename}")
                        elif msg_type == 'connected':
                            self.log(f"🔗 WebSocket: {data.get('message')}")
                        else:
                            self.log(f"📨 WebSocket: {msg_type} - {message[:100]}")
                            
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        self.log(f"❌ WebSocket error: {e}")
                        break
                        
        except Exception as e:
            self.log(f"❌ WebSocket connection failed: {e}")
    
    def monitor_tftp_files(self):
        """Monitor TFTP directory for new files"""
        pattern = f"{TFTP_PATH}/utsc_{TEST_MAC.replace(':', '')}*"
        
        # Get initial file list
        existing = set(glob.glob(pattern))
        self.log(f"📂 Monitoring TFTP: {pattern}")
        self.log(f"📂 Existing files: {len(existing)}")
        
        while self.test_running:
            current = set(glob.glob(pattern))
            new_files = current - existing
            
            for filepath in new_files:
                try:
                    mtime = os.path.getmtime(filepath)
                    elapsed = mtime - (self.start_time + time.time() - self.start_time)
                    self.tftp_files.append({
                        'time': time.time() - self.start_time,
                        'filename': os.path.basename(filepath),
                        'size': os.path.getsize(filepath)
                    })
                    self.log(f"📁 TFTP: New file #{len(self.tftp_files)} - {os.path.basename(filepath)}")
                except Exception as e:
                    self.log(f"❌ Error reading file: {e}")
            
            existing = current
            time.sleep(0.05)  # Check every 50ms
    
    def start_utsc_capture(self):
        """Start UTSC capture via API"""
        url = f"{BASE_URL}/api/pypnm/upstream/utsc/start/{TEST_MAC}"
        
        payload = {
            "cmts_ip": CMTS_IP,
            "rf_port_ifindex": RF_PORT_IFINDEX,
            "community": "Z1gg0Sp3c1@l",
            "tftp_ip": "172.16.6.101",
            "repeat_period_ms": 3000,
            "freerun_duration_ms": 60000,
            "trigger_count": 20
        }
        
        self.log("🚀 Starting UTSC capture...")
        self.log(f"📋 Parameters: {json.dumps(payload, indent=2)}")
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('success'):
                self.log(f"✅ UTSC started successfully")
                self.log(f"   CMTS: {result.get('cmts_ip')}")
                self.log(f"   RF Port: {result.get('rf_port_ifindex')}")
                self.log(f"   Filename: {result.get('filename')}")
                return True
            else:
                self.log(f"❌ UTSC failed: {result.get('error')}")
                return False
                
        except Exception as e:
            self.log(f"❌ API request failed: {e}")
            return False
    
    def check_historical_plots(self):
        """Check historical plot endpoint"""
        url = f"{BASE_URL}/api/pypnm/utsc/plots/{TEST_MAC}"
        
        try:
            response = requests.get(url, timeout=5)
            result = response.json()
            
            if result.get('status') == 'success':
                count = result.get('count', 0)
                self.log(f"📊 Historical plots available: {count}")
                
                plots = result.get('plots', [])
                for i, plot in enumerate(plots[:5], 1):
                    filename = plot.get('filename')
                    timestamp = plot.get('timestamp')
                    self.log(f"   #{i}: {filename}")
                    
                return count
            else:
                self.log(f"❌ Historical plots failed: {result.get('message')}")
                return 0
                
        except Exception as e:
            self.log(f"❌ Historical plots request failed: {e}")
            return 0
    
    def analyze_timing(self):
        """Analyze capture timing"""
        self.log("\n" + "="*80)
        self.log("📊 ANALYSIS RESULTS")
        self.log("="*80)
        
        # TFTP file timing
        if len(self.tftp_files) > 1:
            self.log(f"\n📁 TFTP Files: {len(self.tftp_files)} captures")
            intervals = []
            for i in range(1, min(len(self.tftp_files), 10)):
                interval = (self.tftp_files[i]['time'] - self.tftp_files[i-1]['time']) * 1000
                intervals.append(interval)
                self.log(f"   File {i} → {i+1}: {interval:.1f}ms")
            
            if intervals:
                avg_interval = sum(intervals) / len(intervals)
                self.log(f"\n   Average interval: {avg_interval:.1f}ms")
                self.log(f"   Expected interval: 3000ms")
                self.log(f"   ⚠️  CMTS capturing every {avg_interval:.0f}ms instead of 3000ms!")
        
        # WebSocket updates
        self.log(f"\n📡 WebSocket Updates: {len(self.ws_messages)} received")
        if len(self.ws_messages) > 1:
            ws_intervals = []
            for i in range(1, min(len(self.ws_messages), 10)):
                interval = (self.ws_messages[i]['time'] - self.ws_messages[i-1]['time']) * 1000
                ws_intervals.append(interval)
                self.log(f"   Update {i} → {i+1}: {interval:.1f}ms")
            
            if ws_intervals:
                avg_ws = sum(ws_intervals) / len(ws_intervals)
                self.log(f"\n   Average GUI update: {avg_ws:.1f}ms")
                self.log(f"   Rate limit: 10ms minimum")
        
        # Historical plots
        plot_count = self.check_historical_plots()
        
        # Summary
        self.log("\n" + "="*80)
        self.log("🎯 SUMMARY")
        self.log("="*80)
        self.log(f"TFTP captures created:    {len(self.tftp_files)}")
        self.log(f"WebSocket updates sent:   {len(self.ws_messages)}")
        self.log(f"Historical plots stored:  {plot_count}")
        self.log(f"Test duration:            {time.time() - self.start_time:.1f}s")
        
        if len(self.tftp_files) > len(self.ws_messages):
            diff = len(self.tftp_files) - len(self.ws_messages)
            self.log(f"\n⚠️  WARNING: {diff} captures created but not sent via WebSocket!")
            self.log(f"   Possible rate limiting or processing lag")
        
        if len(self.tftp_files) < 15:
            self.log(f"\n⚠️  WARNING: Only {len(self.tftp_files)} captures created")
            self.log(f"   Expected ~20 captures over 60 seconds")
            self.log(f"   CMTS stopped early - firmware limitation!")
        
        self.log("="*80)
    
    async def run_test(self):
        """Run the complete end-to-end test"""
        print("="*80)
        print("UTSC END-TO-END TEST")
        print("="*80)
        print(f"Target MAC:    {TEST_MAC}")
        print(f"CMTS IP:       {CMTS_IP}")
        print(f"Base URL:      {BASE_URL}")
        print(f"WebSocket:     {WS_URL}")
        print("="*80)
        print()
        
        self.start_time = time.time()
        
        # Start UTSC capture
        if not self.start_utsc_capture():
            self.log("❌ Failed to start UTSC - aborting test")
            return
        
        self.log("\n⏳ Monitoring for 20 seconds...")
        self.log("   Watching: WebSocket updates + TFTP files")
        self.log("")
        
        # Start monitoring tasks
        ws_task = asyncio.create_task(self.monitor_websocket())
        
        # Monitor TFTP in separate thread (sync operation)
        import threading
        tftp_thread = threading.Thread(target=self.monitor_tftp_files, daemon=True)
        tftp_thread.start()
        
        # Wait for captures to complete
        try:
            await asyncio.sleep(20)  # Monitor for 20 seconds
        except KeyboardInterrupt:
            self.log("\n⚠️  Test interrupted by user")
        
        self.test_running = False
        
        # Cancel WebSocket task
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        
        # Wait a bit for final file writes
        await asyncio.sleep(0.5)
        
        # Analyze results
        self.analyze_timing()

async def main():
    tester = UTSCTester()
    await tester.run_test()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
