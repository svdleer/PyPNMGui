#!/usr/bin/env python3
"""
Debug RxMER API endpoint by calling it directly and inspecting the response.
"""
import requests
import json
import time

API_URL = "http://localhost:8000/docs/pnm/ds/ofdm/rxMer/getCapture"
MAC = "90:32:4b:c8:13:73"
IP = "10.206.234.3"
COMMUNITY = "z1gg0m0n1t0r1ng"
TFTP_IP = "172.22.147.18"

payload = {
    "cable_modem": {
        "mac_address": MAC,
        "ip_address": IP,
        "snmp": {
            "snmpV2C": {
                "community": COMMUNITY
            }
        },
        "pnm_parameters": {
            "tftp": {
                "ipv4": TFTP_IP
            }
        }
    },
    "analysis": {
        "type": "basic",
        "output": {
            "type": "json"
        },
        "plot": {
            "ui": {
                "theme": "dark"
            }
        }
    }
}

print("=" * 60)
print("TESTING PyPNM RxMER API DIRECTLY")
print("=" * 60)
print(f"URL: {API_URL}")
print(f"MAC: {MAC}")
print(f"Modem IP: {IP}")
print()

try:
    print("Sending request...")
    start = time.time()
    response = requests.post(API_URL, json=payload, timeout=120)
    elapsed = time.time() - start
    
    print(f"Response time: {elapsed:.2f}s")
    print(f"Status code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type')}")
    print()
    
    try:
        data = response.json()
        print("Response JSON:")
        print(json.dumps(data, indent=2)[:2000])  # First 2000 chars
        print()
        
        if "status" in data:
            print(f"Status: {data['status']}")
            print(f"Message: {data.get('message', 'N/A')}")
            
            if data['status'] == 0:
                print("✓ SUCCESS!")
                if 'data' in data:
                    print(f"Data keys: {list(data['data'].keys())}")
            else:
                print(f"✗ FAILED with status {data['status']}")
                
    except json.JSONDecodeError as e:
        print(f"✗ JSON decode error: {e}")
        print(f"Raw response: {response.text[:500]}")
        
except requests.exceptions.Timeout:
    print("✗ Request timed out")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
