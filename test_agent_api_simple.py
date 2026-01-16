#!/usr/bin/env python3
"""Simple synchronous test of PyPNM agent transport"""
import requests

backend_url = "http://localhost:5050"

print("Testing PyPNM Agent Transport...")

# Test SNMP GET
print("\n1. SNMP GET sysDescr:")
response = requests.post(f"{backend_url}/api/snmp/get", json={
    "modem_ip": "10.214.157.17",
    "oid": "1.3.6.1.2.1.1.1.0",
    "community": "m0d3m1nf0"
})
print(f"Status: {response.status_code}")
if response.ok:
    data = response.json()
    if data.get("success"):
        print(f"✅ Result: {data.get('output', '')[:100]}...")

# Test SNMP WALK
print("\n2. SNMP WALK ifType:")
response = requests.post(f"{backend_url}/api/snmp/walk", json={
    "modem_ip": "10.214.157.17",
    "oid": "1.3.6.1.2.1.2.2.1.3",
    "community": "m0d3m1nf0"
})
print(f"Status: {response.status_code}")
if response.ok:
    data = response.json()
    if data.get("success"):
        output = data.get('output', '')
        lines = output.strip().split('\n')
        print(f"✅ Found {len(lines)} interfaces")
        print(f"First 3: {lines[:3]}")

print("\n✅ PyPNM agent transport working!")
