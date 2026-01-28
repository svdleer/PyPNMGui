#!/usr/bin/env python3
"""Test constellation capture and show debug output automatically."""

import requests
import subprocess
import time
import json

# Configuration
API_URL = "http://149.210.167.40:8000/docs/pnm/ds/ofdm/constellationDisplay/getCapture"
MODEM_MAC = "90:32:4b:c8:13:73"
OFDM_CHANNEL = 159

def trigger_capture():
    """Trigger constellation capture via API."""
    print(f"\n{'='*60}")
    print(f"Triggering constellation capture for {MODEM_MAC}...")
    print(f"{'='*60}\n")
    
    payload = {
        "mac": MODEM_MAC,
        "ofdm_channel_id": OFDM_CHANNEL
    }
    
    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Success: {data.get('success', False)}")
            if 'data' in data:
                print(f"Plots generated: {len(data.get('data', {}).get('plots', []))}")
        else:
            print(f"Error: {response.text}")
            
        return response.status_code == 200
        
    except Exception as e:
        print(f"Request failed: {e}")
        return False

def get_debug_logs():
    """Fetch debug logs from remote server."""
    print(f"\n{'='*60}")
    print("Fetching debug logs from pypnm-api container...")
    print(f"{'='*60}\n")
    
    cmd = [
        "ssh", "access-engineering.nl",
        "sudo docker logs --tail 200 pypnm-api 2>&1 | grep -A 30 'CONSTELLATION DEBUG'"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.stdout:
            print(result.stdout)
        else:
            print("No constellation debug output found in logs")
            print("\nShowing last 50 lines of logs:")
            cmd2 = ["ssh", "access-engineering.nl", "sudo docker logs --tail 50 pypnm-api 2>&1"]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
            print(result2.stdout)
    except Exception as e:
        print(f"Failed to get logs: {e}")

def main():
    print("\n" + "="*60)
    print("CONSTELLATION CAPTURE DEBUG TEST")
    print("="*60)
    
    # Trigger the capture
    success = trigger_capture()
    
    # Wait a moment for logs to be written
    time.sleep(2)
    
    # Get and display debug logs
    get_debug_logs()
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
