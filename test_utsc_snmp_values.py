#!/usr/bin/env python3
"""
Test to verify PyPNM actually sets the UTSC timing parameters on the CMTS
"""
import subprocess
import time
import requests
import json

MAC = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT = 1074339840
COMMUNITY = "Z1gg0Sp3c1@l"
SERVER_HOST = "access-engineering.nl"  # Remote server

print("="*80)
print("UTSC SNMP Parameter Verification Test")
print("="*80)

# Step 1: Trigger UTSC
print("\n1. Triggering UTSC FreeRunning mode (trigger_mode=2)...")
print("   - repeat_period_ms: 1000 (should be 1,000,000 microseconds)")
print("   - freerun_duration_ms: 60000")
print("   - trigger_count: NOT SET (ignored in FreeRunning mode)")

url = f"http://{SERVER_HOST}:5050/api/pypnm/upstream/utsc/start/{MAC}"
payload = {
    "cmts_ip": CMTS_IP,
    "rf_port_ifindex": RF_PORT,
    "community": COMMUNITY,
    "tftp_ip": "172.16.6.101",
    "trigger_mode": 2,  # FreeRunning
    "repeat_period_ms": 1000,
    "freerun_duration_ms": 60000
    # trigger_count omitted - not used in FreeRunning mode
}

try:
    response = requests.post(url, json=payload, timeout=10)
    if response.status_code == 200:
        result = response.json()
        print(f"   ✅ API Success: {result.get('success')}")
    else:
        print(f"   ❌ API Error: {response.text}")
        exit(1)
except Exception as e:
    print(f"   ❌ Request failed: {e}")
    exit(1)

# Step 2: Query SNMP immediately to check values BEFORE CMTS deletes the row
print("\n2. Querying CMTS SNMP values (RepeatPeriod and FreeRunDuration only)...")
time.sleep(0.5)  # Small delay to let SNMP sets complete

# Using numeric OIDs - only checking RepeatPeriod and FreeRunDuration (not TriggerCount for FreeRunning)
cmd = f"""ssh {SERVER_HOST} "snmpget -v2c -Ov -c '{COMMUNITY}' {CMTS_IP} \\
  1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.18.{RF_PORT}.1 \\
  1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.19.{RF_PORT}.1 \\
  2>&1" """

result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

print("\n3. Results:")
print("-" * 80)

if "No Such Instance" in result.stdout or "No Such Object" in result.stdout:
    print("   ❌ FAIL: UTSC row doesn't exist or was immediately deleted")
    print("   This means PyPNM might not be setting the values, or CMTS deletes them instantly")
    print(f"\n   Raw output:\n{result.stdout}")
elif result.stdout.strip():
    lines = result.stdout.strip().split('\n')
    print(f"   Raw SNMP output:")
    for line in lines:
        print(f"      {line}")
    
    # Try to parse values
    try:
        if len(lines) >= 2:
            repeat_period = lines[0].split(':')[-1].strip() if ':' in lines[0] else 'N/A'
            freerun_duration = lines[1].split(':')[-1].strip() if ':' in lines[1] else 'N/A'
            
            print(f"\n   Parsed values:")
            print(f"      RepeatPeriod: {repeat_period} (expected: 1000000 microseconds)")
            print(f"      FreeRunDuration: {freerun_duration} (expected: 60000 Milliseconds)")
            print(f"      TriggerCount: NOT SET (correctly omitted for FreeRunning mode)")
            
            # Validate
            if '1000000' in repeat_period and '60000' in freerun_duration:
                print(f"\n   ✅ SUCCESS: Timing parameters SET CORRECTLY by PyPNM!")
                print(f"   ✅ TriggerCount correctly omitted for FreeRunning mode")
                print(f"   The CMTS received and stored the values.")
            else:
                print(f"\n   ⚠️  MISMATCH: Values don't match what we sent")
                print(f"      Expected: RepeatPeriod=1000000 µs, FreeRunDuration=60000 ms")
    except Exception as e:
        print(f"\n   ⚠️  Error parsing: {e}")
else:
    print(f"   ❌ No output from SNMP query")
    print(f"   stderr: {result.stderr}")

print("\n" + "="*80)
