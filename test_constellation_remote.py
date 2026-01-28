#!/usr/bin/env python3
"""
Test script to trigger constellation capture and show debug output.
Run this ON THE REMOTE SERVER (access-engineering.nl).
"""
import requests
import json
import time

# API endpoint on LOCALHOST (runs on same server as this script)
API_BASE = "http://localhost:8000"

# Modem to test
MAC = "90:32:4b:c8:13:73"

def test_constellation():
    """Trigger constellation capture and show results."""
    
    print(f"\n{'='*60}")
    print(f"Testing Constellation Capture for {MAC}")
    print(f"{'='*60}\n")
    
    # Payload for constellation capture (correct API format)
    payload = {
        "cable_modem": {
            "mac_address": MAC,
            "snmp": {
                "community": "z1gg0m0n1t0r1ng",
                "snmpV2C": {
                    "community": "z1gg0m0n1t0r1ng"
                }
            },
            "pnm_parameters": {
                "tftp": {
                    "ipv4": "172.22.147.18",
                    "ipv6": None
                }
            }
        },
        "analysis": {
            "type": "basic",
            "output": {"type": "json"},
            "plot": {
                "ui": {"theme": "dark"},
                "options": {"display_cross_hair": True}
            }
        },
        "capture_settings": {
            "modulation_order_offset": 0,
            "number_sample_symbol": 8192
        }
    }
    
    url = f"{API_BASE}/docs/pnm/ds/ofdm/constellationDisplay/getCapture"
    
    print(f"POST {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}\n")
    
    try:
        # Trigger capture (no MAC param in URL to avoid ping check)
        response = requests.post(
            url,
            json=payload,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ SUCCESS\n")
            print(f"Response keys: {list(data.keys())}")
            
            if 'payload' in data:
                payload_data = data['payload']
                if isinstance(payload_data, list):
                    print(f"Payload: List with {len(payload_data)} items")
                    if len(payload_data) > 0:
                        print(f"First item: {payload_data[0]}")
                    else:
                        print("⚠️  Payload list is EMPTY")
                elif isinstance(payload_data, dict):
                    print(f"Payload: Dict with keys: {list(payload_data.keys())}")
                    if 'measurements' in payload_data:
                        print(f"Measurements: {len(payload_data['measurements'])}")
                else:
                    print(f"Payload type: {type(payload_data)}")
            
            # Check plots
            if 'plots' in data:
                print(f"\nPlots generated: {len(data['plots'])}")
                if len(data['plots']) == 0:
                    print("⚠️  NO PLOTS - constellation data is empty")
                else:
                    for plot in data['plots']:
                        print(f"  - {plot.get('channel_id')}: {plot.get('title')}")
        else:
            print(f"\n❌ FAILED: {response.status_code}")
            print(response.text[:500])
            
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Request failed: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    
    print(f"\n{'='*60}")
    print("Check PyPNM API logs for CONSTELLATION DEBUG output:")
    print("sudo docker logs --tail 100 pypnm-api 2>&1 | grep -A 30 'CONSTELLATION DEBUG'")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    test_constellation()
