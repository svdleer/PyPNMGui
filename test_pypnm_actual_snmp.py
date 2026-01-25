#!/usr/bin/env python3
"""
Test what PyPNM API actually sends to the CMTS for FreeRunDuration
"""
import requests
import time
import subprocess

MAC = "fc:01:7c:bf:73:e3"
CMTS_IP = "172.16.6.212"
RF_PORT = 1079058432
COMMUNITY = "Z1gg0Sp3c1@l"

print("="*80)
print("PyPNM API SNMP Parameter Test")
print("="*80)

# Step 1: Clear any existing value first
print("\n1. Clearing existing UTSC config...")
oid = f"1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.19.{RF_PORT}.1"
cmd = f'ssh access-engineering.nl "snmpset -v2c -c {COMMUNITY} {CMTS_IP} {oid} u 1000"'
subprocess.run(cmd, shell=True, capture_output=True)

# Step 2: Trigger via PyPNM with 120000 ms
print(f"\n2. Triggering UTSC via PyPNM API with freerun_duration_ms=120000...")
url = f"http://localhost:5051/api/pypnm/upstream/utsc/start/{MAC}"
payload = {
    "cmts_ip": CMTS_IP,
    "rf_port_ifindex": RF_PORT,
    "community": COMMUNITY,
    "tftp_ip": "172.16.6.101",
    "trigger_mode": 2,
    "center_freq_hz": 50000000,
    "span_hz": 80000000,
    "num_bins": 3200,
    "repeat_period_ms": 1000,
    "freerun_duration_ms": 120000,  # <-- This should reach CMTS
    "filename": f"utsc_{MAC.replace(':', '')}"
}

print(f"   Payload: freerun_duration_ms={payload['freerun_duration_ms']}")

try:
    response = requests.post(url, json=payload, timeout=30)
    if response.status_code == 200:
        result = response.json()
        print(f"   ✅ API returned: {result.get('success')}")
    else:
        print(f"   ❌ API Error: {response.text}")
except Exception as e:
    print(f"   ❌ Request failed: {e}")

# Step 3: Wait a moment for PyPNM to finish SNMP operations
time.sleep(2)

# Step 4: Query what's actually on the CMTS
print(f"\n3. Reading back from CMTS...")
cmd = f'ssh access-engineering.nl "snmpget -v2c -Ov -c {COMMUNITY} {CMTS_IP} {oid}"'
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

if result.returncode == 0:
    output = result.stdout.strip()
    print(f"   Raw output: {output}")
    
    # Extract value
    if "Gauge32:" in output or "Milliseconds" in output:
        parts = output.split(":")
        if len(parts) >= 2:
            value = parts[-1].strip().split()[0]
            print(f"\n   📊 CMTS has: {value} Milliseconds")
            print(f"   📤 We sent: 120000 Milliseconds")
            
            if value == "120000":
                print(f"\n   ✅✅✅ SUCCESS! PyPNM correctly sent 120000 ms to CMTS!")
            else:
                print(f"\n   ❌ BUG FOUND! PyPNM sent {value} instead of 120000")
                print(f"   The value was modified somewhere in the PyPNM code path")
else:
    print(f"   ❌ SNMP query failed: {result.stderr}")

print("\n" + "="*80)
