#!/usr/bin/env python3
import requests
import time
import sys

PYPNM_URL = "http://127.0.0.1:8000"
session = requests.Session()
session.headers.update({"Content-Type": "application/json"})

def get_upstream_data(mac, ip, community="public"):
    payload = {
        "cable_modem": {
            "mac_address": mac,
            "ip_address": ip,
            "snmp": {"snmpV2C": {"community": community}}
        }
    }
    try:
        resp = session.post(f"{PYPNM_URL}/docs/if30/us/channelTable", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None

def analyze_upstream(mac, ip, num_samples=100, delay=2):
    for i in range(num_samples):
        print(f"Sample {i+1}/{num_samples}")
        data = get_upstream_data(mac, ip)
        if data:
            print(f"  Success: {len(data.get('data', []))} channels")
        time.sleep(delay)

if __name__ == "__main__":
    analyze_upstream("AA:BB:CC:DD:EE:FF", "192.168.100.1", num_samples=100)
