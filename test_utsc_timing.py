#!/usr/bin/env python3
"""
Quick test to verify UTSC timing parameters are actually set on CMTS
Triggers UTSC and immediately queries the OIDs before they're deleted
"""
import subprocess
import time
import requests
import json

MAC = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT = 1074339840
COMMUNITY = "Z1gg0Sp3c1@l"

# OID base for UTSC config
BASE_OID = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
REPEAT_PERIOD_OID = f"{BASE_OID}.18.{RF_PORT}"
FREERUN_DURATION_OID = f"{BASE_OID}.19.{RF_PORT}"
TRIGGER_COUNT_OID = f"{BASE_OID}.20.{RF_PORT}"

print("="*80)
print("UTSC Timing Parameter Verification Test")
print("="*80)

# Trigger UTSC
print("\n1. Triggering UTSC...")
url = f"http://localhost:5051/api/pypnm/upstream/utsc/start/{MAC}"
payload = {
    "cmts_ip": CMTS_IP,
    "rf_port_ifindex": RF_PORT,
    "community": COMMUNITY,
    "tftp_ip": "172.16.6.101",
    "repeat_period_ms": 3000,
    "freerun_duration_ms": 60000,
    "trigger_count": 20
}

response = requests.post(url, json=payload, timeout=10)
print(f"   API Response: {response.status_code}")
if response.status_code == 200:
    result = response.json()
    print(f"   Success: {result.get('success')}")
else:
    print(f"   Error: {response.text}")
    exit(1)

# Quick SNMP query via SSH before config is deleted
print("\n2. Querying CMTS OIDs immediately...")
cmd = f'ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab snmpget -v2c -Ov -c \'{COMMUNITY}\' {CMTS_IP} {REPEAT_PERIOD_OID} {FREERUN_DURATION_OID} {TRIGGER_COUNT_OID} 2>&1 | grep -E \'^(Gauge32|INTEGER|Counter|Unsigned32):\'"'

print(f"   Command: {cmd[:100]}...")
result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)

if result.returncode == 0 and result.stdout.strip():
    lines = result.stdout.strip().split('\n')
    print(f"\n   ✅ SNMP Query Results:")
    print(f"      RepeatPeriod (OID .18): {lines[0] if len(lines) > 0 else 'N/A'}")
    print(f"      FreeRunDuration (OID .19): {lines[1] if len(lines) > 1 else 'N/A'}")
    print(f"      TriggerCount (OID .20): {lines[2] if len(lines) > 2 else 'N/A'}")
    
    # Parse values
    if len(lines) >= 2:
        try:
            # Extract numeric values
            repeat_val = lines[0].split(':')[1].strip() if ':' in lines[0] else 'N/A'
            freerun_val = lines[1].split(':')[1].strip() if ':' in lines[1] else 'N/A'
            trigger_val = lines[2].split(':')[1].strip() if ':' in lines[2] else 'N/A'
            
            print(f"\n3. Validation:")
            print(f"   RepeatPeriod: {repeat_val} microseconds (expected: 3,000,000)")
            print(f"   FreeRunDuration: {freerun_val} milliseconds (expected: 60,000)")
            print(f"   TriggerCount: {trigger_val} (expected: 20)")
            
            if repeat_val == '3000000' and freerun_val == '60000' and trigger_val == '20':
                print(f"\n   ✅ ALL PARAMETERS SET CORRECTLY!")
            else:
                print(f"\n   ⚠️  MISMATCH DETECTED!")
        except Exception as e:
            print(f"\n   ⚠️  Error parsing values: {e}")
else:
    print(f"\n   ❌ SNMP query failed or OIDs don't exist")
    print(f"   stdout: {result.stdout}")
    print(f"   stderr: {result.stderr}")

print("\n" + "="*80)
