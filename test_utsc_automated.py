#!/usr/bin/env python3
"""
UTSC Automated Test Script
Tests complete UTSC workflow via API without browser interaction
Must confirm data reaches scigraph within 10 minutes
"""

import requests
import websocket
import json
import time
import threading
import sys
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:5050"  # Back to gui backend
TIMEOUT = 600  # 10 minutes
MAC_ADDRESS = "e4:57:40:0b:db:b9"  # Known working MAC from logs

# Test state
test_results = {
    'api_connection': False,
    'utsc_started': False,
    'websocket_connected': False,
    'data_received': False,
    'graph_data_count': 0,
    'buffering_complete': False,
    'streaming_active': False,
    'errors': []
}

def log(message):
    """Log with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def test_api_connectivity():
    """Test basic API connectivity"""
    log("Testing API connectivity...")
    try:
        # Try multiple endpoints to find working one
        endpoints = [
            f"{BASE_URL}/",
            f"{BASE_URL}/api/health", 
            f"{BASE_URL}/api/pypnm/modems"
        ]
        
        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                log(f"✓ API endpoint {endpoint} responded: {response.status_code}")
                test_results['api_connection'] = True
                return True
            except Exception as e:
                log(f"✗ API endpoint {endpoint} failed: {e}")
        
        return False
        
    except Exception as e:
        test_results['errors'].append(f"API connectivity failed: {e}")
        log(f"✗ API connectivity test failed: {e}")
        return False

def start_utsc_test():
    """Start UTSC test via API"""
    log(f"Starting UTSC test for MAC: {MAC_ADDRESS}")
    try:
        url = f"{BASE_URL}/api/pypnm/upstream/utsc/start/{MAC_ADDRESS}"
        payload = {
            "cmts_ip": "172.16.6.212",
            "rf_port_ifindex": 1078534144,
            "community": "Z1gg0Sp3c1@l",
            "tftp_ip": "172.16.6.101",
            "repeat_period_ms": 1000,
            "freerun_duration_ms": 60000
            # No trigger_count for freerun mode - E6000 should run for 60s
        }
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            log("✓ UTSC test started successfully")
            test_results['utsc_started'] = True
            return True
        else:
            log(f"✗ UTSC start failed: {response.status_code} - {response.text}")
            test_results['errors'].append(f"UTSC start failed: {response.status_code}")
            return False
            
    except Exception as e:
        test_results['errors'].append(f"UTSC start failed: {e}")
        log(f"✗ UTSC start failed: {e}")
        return False

def on_websocket_message(ws, message):
    """Handle WebSocket messages from UTSC stream"""
    try:
        data = json.loads(message)
        msg_type = data.get('type', 'unknown')
        
        if msg_type == 'connected':
            log("✓ WebSocket connected to UTSC stream")
            test_results['websocket_connected'] = True
            
        elif msg_type == 'buffering':
            buffer_size = data.get('buffer_size', 0)
            target = data.get('target', 0)
            log(f"⟳ Buffering: {buffer_size}/{target} samples")
            
        elif msg_type == 'buffering_complete':
            buffer_size = data.get('buffer_size', 0)
            log(f"✓ Buffering complete: {buffer_size} samples ready")
            test_results['buffering_complete'] = True
            
        elif msg_type == 'spectrum_data' or msg_type == 'spectrum':
            test_results['data_received'] = True
            test_results['graph_data_count'] += 1
            test_results['streaming_active'] = True
            
            amplitudes = data.get('amplitudes', [])
            freq_info = f"{data.get('center_freq_hz', 0)/1e6:.1f}MHz ±{data.get('span_hz', 0)/1e6:.1f}MHz"
            log(f"✓ Graph data received: {len(amplitudes)} points, {freq_info} (count: {test_results['graph_data_count']})")
            
            # Success criteria: received graph data
            if test_results['graph_data_count'] >= 3:
                log("🎉 SUCCESS: Multiple graph data points confirmed!")
                ws.close()
                
        elif msg_type == 'status':
            status = data.get('message', 'unknown')
            log(f"ℹ Status: {status}")
            
        else:
            log(f"ℹ WebSocket message: {msg_type}")
            
    except Exception as e:
        log(f"✗ WebSocket message parse error: {e}")
        test_results['errors'].append(f"WebSocket parse error: {e}")

def on_websocket_error(ws, error):
    """Handle WebSocket errors"""
    log(f"✗ WebSocket error: {error}")
    test_results['errors'].append(f"WebSocket error: {error}")

def on_websocket_close(ws, close_status_code, close_msg):
    """Handle WebSocket close"""
    log(f"WebSocket closed: {close_status_code} - {close_msg}")

def test_websocket_stream():
    """Test WebSocket streaming of UTSC data"""
    log("Connecting to UTSC WebSocket stream...")
    try:
        # Connect to UTSC WebSocket
        ws_url = f"ws://localhost:5050/ws/utsc/{MAC_ADDRESS}?refresh_ms=500&duration_s=60"
        
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_websocket_message,
            on_error=on_websocket_error,
            on_close=on_websocket_close
        )
        
        # Start WebSocket in thread
        ws_thread = threading.Thread(target=ws.run_forever)
        ws_thread.daemon = True
        ws_thread.start()
        
        # Wait for results or timeout
        start_time = time.time()
        while time.time() - start_time < TIMEOUT:
            if test_results['graph_data_count'] >= 3:
                log("✓ Graph data streaming confirmed!")
                return True
                
            time.sleep(1)
            
        log("✗ WebSocket test timeout")
        return False
        
    except Exception as e:
        test_results['errors'].append(f"WebSocket test failed: {e}")
        log(f"✗ WebSocket test failed: {e}")
        return False

def print_summary():
    """Print test summary"""
    log("\n" + "="*60)
    log("TEST SUMMARY")
    log("="*60)
    
    status_symbol = "✓" if test_results['api_connection'] else "✗"
    log(f"{status_symbol} API Connection: {test_results['api_connection']}")
    
    status_symbol = "✓" if test_results['utsc_started'] else "✗"
    log(f"{status_symbol} UTSC Started: {test_results['utsc_started']}")
    
    status_symbol = "✓" if test_results['websocket_connected'] else "✗"
    log(f"{status_symbol} WebSocket Connected: {test_results['websocket_connected']}")
    
    status_symbol = "✓" if test_results['buffering_complete'] else "✗"
    log(f"{status_symbol} Buffering Complete: {test_results['buffering_complete']}")
    
    status_symbol = "✓" if test_results['data_received'] else "✗"
    log(f"{status_symbol} Graph Data Received: {test_results['data_received']} ({test_results['graph_data_count']} samples)")
    
    # Overall success
    success = (test_results['api_connection'] and 
               test_results['utsc_started'] and 
               test_results['websocket_connected'] and 
               test_results['data_received'] and
               test_results['graph_data_count'] >= 3)
    
    log("\n" + "="*60)
    if success:
        log("🎉 OVERALL RESULT: SUCCESS - UTSC data reaches scigraph!")
        log("✓ All critical components working")
        log(f"✓ {test_results['graph_data_count']} spectrum data samples confirmed")
    else:
        log("💥 OVERALL RESULT: FAILURE - Issues detected!")
        if test_results['errors']:
            log("Errors encountered:")
            for error in test_results['errors']:
                log(f"  - {error}")
    
    log("="*60)
    return success

def main():
    """Main test execution"""
    log("UTSC Automated Test Starting...")
    log(f"Target: {BASE_URL}")
    log(f"MAC: {MAC_ADDRESS}")
    log(f"Timeout: {TIMEOUT}s")
    log("-" * 60)
    
    # Test sequence
    if not test_api_connectivity():
        log("💥 API test failed, aborting")
        print_summary()
        sys.exit(1)
    
    if not start_utsc_test():
        log("💥 UTSC start failed, aborting")
        print_summary()
        sys.exit(1)
    
    # Small delay for UTSC to initialize
    log("Waiting 3s for UTSC initialization...")
    time.sleep(3)
    
    # Test WebSocket streaming
    success = test_websocket_stream()
    
    # Print results
    overall_success = print_summary()
    
    if overall_success:
        log("🎉 Test completed successfully!")
        sys.exit(0)
    else:
        log("💥 Test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
