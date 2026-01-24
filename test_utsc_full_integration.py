#!/usr/bin/env python3
"""
UTSC Full Integration Test Script
Tests complete UTSC pipeline: trigger -> files -> buffering -> streaming -> graph data
Must run from docker host or inside container
TIME LIMIT: 10 minutes to fix GUI
"""

import requests
import websocket
import json
import time
import threading
import sys
from datetime import datetime

# Test configuration  
GUI_BASE_URL = "http://localhost:5050"  # External port from host
MODEM_MAC = "e4:57:40:0b:db:b9"
TEST_DURATION = 120  # 2 minutes max test
REQUIRED_DATA_POINTS = 5  # Must receive at least 5 spectrum data points

class UTSCTester:
    def __init__(self):
        self.ws = None
        self.data_received = []
        self.buffering_complete = False
        self.streaming_started = False
        self.test_start = time.time()
        
    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {msg}")
        
    def test_api_connectivity(self):
        """Test basic API connectivity"""
        self.log("Testing API connectivity...")
        try:
            # Try the main page (should redirect to login but still respond)
            response = requests.get(f"{GUI_BASE_URL}/", timeout=5, allow_redirects=False)
            if response.status_code in [200, 302]:  # 302 is redirect to login
                self.log("✓ API connectivity OK")
                return True
        except Exception as e:
            self.log(f"API connectivity error: {e}")
            
        self.log("✗ API connectivity FAILED")
        return False
        
    def start_utsc(self):
        """Start UTSC via API"""
        self.log("Starting UTSC...")
        payload = {
            "cmts_ip": "172.16.6.212",
            "rf_port_ifindex": 1078534144,
            "community": "Z1gg0Sp3c1@l",
            "tftp_ip": "172.16.6.101",
            "repeat_period_ms": 1000,
            "freerun_duration_ms": 55000,
            "trigger_count": 10
        }
        
        try:
            response = requests.post(
                f"{GUI_BASE_URL}/api/pypnm/upstream/utsc/start/{MODEM_MAC}",
                json=payload,
                timeout=10
            )
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    self.log("✓ UTSC started successfully")
                    return True
                else:
                    self.log(f"✗ UTSC start failed: {result.get('error', 'Unknown error')}")
            else:
                self.log(f"✗ UTSC start HTTP error: {response.status_code}")
        except Exception as e:
            self.log(f"✗ UTSC start exception: {e}")
        return False
        
    def on_message(self, ws, message):
        """WebSocket message handler"""
        try:
            data = json.loads(message)
            msg_type = data.get('type', 'unknown')
            
            if msg_type == 'connected':
                self.log(f"✓ WebSocket connected: {data.get('message', '')}")
                
            elif msg_type == 'buffering':
                buffer_size = data.get('buffer_size', 0)
                target = data.get('target', 0)
                self.log(f"⏳ Buffering: {buffer_size}/{target} samples")
                
            elif msg_type == 'buffering_complete':
                self.buffering_complete = True
                buffer_size = data.get('buffer_size', 0)
                self.log(f"✓ Buffering complete: {buffer_size} samples buffered")
                
            elif msg_type == 'spectrum_data':
                self.streaming_started = True
                self.data_received.append(data)
                amplitudes = data.get('amplitudes', [])
                span_hz = data.get('span_hz', 0)
                center_freq_hz = data.get('center_freq_hz', 0)
                self.log(f"📊 Spectrum data #{len(self.data_received)}: {len(amplitudes)} points, "
                        f"span={span_hz/1e6:.1f}MHz, center={center_freq_hz/1e6:.1f}MHz")
                
            elif msg_type == 'error':
                self.log(f"✗ WebSocket error: {data.get('message', 'Unknown error')}")
                
        except Exception as e:
            self.log(f"✗ Message parse error: {e}")
            
    def on_error(self, ws, error):
        self.log(f"✗ WebSocket error: {error}")
        
    def on_close(self, ws, close_status_code, close_msg):
        self.log(f"WebSocket closed: {close_status_code} - {close_msg}")
        
    def on_open(self, ws):
        self.log("✓ WebSocket opened")
        
    def connect_websocket(self):
        """Connect to UTSC WebSocket"""
        self.log("Connecting to UTSC WebSocket...")
        ws_url = f"ws://localhost:5050/ws/utsc/{MODEM_MAC}?refresh_ms=500&duration_s=60"
        
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        
        # Run WebSocket in thread
        ws_thread = threading.Thread(target=self.ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        return True
        
    def run_test(self):
        """Run complete test suite"""
        self.log("=== UTSC FULL INTEGRATION TEST START ===")
        self.log(f"Target: {REQUIRED_DATA_POINTS} spectrum data points in {TEST_DURATION}s")
        
        # Test 1: API connectivity
        if not self.test_api_connectivity():
            return False
            
        # Test 2: Connect WebSocket
        if not self.connect_websocket():
            return False
            
        # Wait for WebSocket to connect
        time.sleep(2)
        
        # Test 3: Start UTSC
        if not self.start_utsc():
            return False
            
        # Test 4: Monitor for data
        self.log(f"Monitoring for {TEST_DURATION}s...")
        start_time = time.time()
        last_status = time.time()
        
        while time.time() - start_time < TEST_DURATION:
            elapsed = time.time() - start_time
            
            # Status update every 10s
            if time.time() - last_status > 10:
                self.log(f"Status: {elapsed:.0f}s elapsed, {len(self.data_received)} data points received")
                last_status = time.time()
            
            # Check success condition
            if len(self.data_received) >= REQUIRED_DATA_POINTS:
                self.log(f"✓ SUCCESS: Received {len(self.data_received)} spectrum data points!")
                self.analyze_data()
                return True
                
            time.sleep(1)
            
        # Timeout
        self.log(f"✗ TIMEOUT: Only received {len(self.data_received)}/{REQUIRED_DATA_POINTS} data points")
        self.analyze_data()
        return False
        
    def analyze_data(self):
        """Analyze received data"""
        self.log("=== DATA ANALYSIS ===")
        self.log(f"Buffering completed: {'Yes' if self.buffering_complete else 'No'}")
        self.log(f"Streaming started: {'Yes' if self.streaming_started else 'No'}")
        self.log(f"Total data points: {len(self.data_received)}")
        
        if self.data_received:
            first = self.data_received[0]
            last = self.data_received[-1]
            self.log(f"First data: {len(first.get('amplitudes', []))} amplitudes")
            self.log(f"Last data: {len(last.get('amplitudes', []))} amplitudes")
            
            # Check data quality
            valid_data = 0
            for data in self.data_received:
                amplitudes = data.get('amplitudes', [])
                if len(amplitudes) > 0:
                    valid_data += 1
                    
            self.log(f"Valid data points: {valid_data}/{len(self.data_received)}")
        else:
            self.log("No data received - check logs for issues")
            
def main():
    """Main test function"""
    tester = UTSCTester()
    success = tester.run_test()
    
    print("\n=== TEST RESULT ===")
    if success:
        print("✅ UTSC INTEGRATION TEST PASSED")
        print("Graph data is flowing correctly!")
        sys.exit(0)
    else:
        print("❌ UTSC INTEGRATION TEST FAILED")
        print("GUI needs fixing within 10 minute deadline!")
        sys.exit(1)

if __name__ == "__main__":
    main()