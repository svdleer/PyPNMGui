#!/usr/bin/env python3
"""
Test RxMER measurement endpoint directly.
"""
import requests
import json
import sys

# Configuration
API_BASE = "http://localhost:5050/api/pypnm"
MAC_ADDRESS = "90:32:4b:c8:13:73"
MODEM_IP = "10.206.234.3"
COMMUNITY = "z1gg0m0n1t0r1ng"
TFTP_IP = "172.22.147.18"

def test_rxmer():
    """Test RxMER measurement."""
    url = f"{API_BASE}/measurements/rxmer/{MAC_ADDRESS}"
    
    payload = {
        "modem_ip": MODEM_IP,
        "community": COMMUNITY,
        "tftp_ip": TFTP_IP,
        "output_type": "json"
    }
    
    print(f"Testing RxMER for {MAC_ADDRESS}")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print("\nSending request...")
    
    try:
        response = requests.post(url, json=payload, timeout=120)
        
        print(f"\nStatus Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print("\n✓ Response received successfully!")
                print(f"Status: {data.get('status')}")
                print(f"Message: {data.get('message')}")
                
                if data.get('status') == 0:
                    print("\n✓✓ RxMER measurement SUCCESS!")
                    
                    # Show some data
                    if 'data' in data:
                        print(f"\nData keys: {list(data['data'].keys())}")
                        if 'rxmer_per_subcarrier' in data['data']:
                            rxmer = data['data']['rxmer_per_subcarrier']
                            print(f"RxMER subcarriers: {len(rxmer)} values")
                            if rxmer:
                                print(f"First few values: {rxmer[:5]}")
                    
                    # Check for plots
                    if 'plots' in data:
                        print(f"\nPlots: {len(data['plots'])} images")
                        for plot in data['plots']:
                            print(f"  - {plot.get('filename')}")
                else:
                    print(f"\n✗ Measurement failed with status {data.get('status')}")
                    print(f"Full response:\n{json.dumps(data, indent=2)}")
            except json.JSONDecodeError as e:
                print(f"\n✗ Failed to parse JSON response: {e}")
                print(f"Response text: {response.text[:500]}")
        else:
            print(f"\n✗ HTTP Error {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
    except requests.exceptions.Timeout:
        print("\n✗ Request timed out after 120 seconds")
    except requests.exceptions.ConnectionError as e:
        print(f"\n✗ Connection error: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_rxmer()
