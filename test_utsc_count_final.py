#!/usr/bin/env python3
"""
UTSC Count Test - FINAL VERSION
Runs from HOST, triggers via API, monitors files via docker exec
"""
import time
import subprocess
import requests
import json

MAC = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT = 1074339840
COMMUNITY = "Z1gg0Sp3c1@l"
FILENAME_PREFIX = "utsc_count_test"
API_URL = "http://localhost:8000"

def count_files():
    """Count UTSC files via docker exec"""
    cmd = f'docker exec pypnm-gui-lab ls /app/data/{FILENAME_PREFIX}_* 2>/dev/null | wc -l'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0

def clear_files():
    """Remove old test files"""
    cmd = f'docker exec pypnm-gui-lab rm -f /app/data/{FILENAME_PREFIX}_* 2>/dev/null'
    subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
    time.sleep(1)

def trigger_utsc(repeat_period_ms, freerun_duration_ms, trigger_count):
    """Trigger UTSC via API"""
    url = f"{API_URL}/api/pypnm/upstream/utsc/start/{MAC}"
    payload = {
        "cmts_ip": CMTS_IP,
        "rf_port_ifindex": RF_PORT,
        "community": COMMUNITY,
        "tftp_ip": "172.16.6.101",
        "trigger_mode": 2,  # FreeRunning
        "center_freq_hz": 30000000,
        "span_hz": 80000000,
        "num_bins": 800,
        "filename": FILENAME_PREFIX,
        "repeat_period_ms": repeat_period_ms,
        "freerun_duration_ms": freerun_duration_ms,
        "trigger_count": trigger_count
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            success = result.get('success', False)
            if not success:
                error = result.get('message') or result.get('error', 'Unknown')
                print(f"      ⚠️  API returned success=False: {error}")
            return success
        else:
            print(f"      ❌ HTTP {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"      ❌ API Error: {e}")
        return False

def run_test(name, repeat_period_ms, freerun_duration_ms, trigger_count, wait_time):
    """Run a single test scenario"""
    print(f"\n{'='*80}")
    print(f"{name}")
    print(f"{'='*80}")
    print(f"Parameters:")
    print(f"  repeat_period: {repeat_period_ms}ms")
    print(f"  freerun_duration: {freerun_duration_ms}ms")
    print(f"  trigger_count: {trigger_count}")
    
    theoretical = freerun_duration_ms // repeat_period_ms
    print(f"  Expected: {theoretical} files (by duration/period)")
    print(f"           OR {min(trigger_count, 10)} files (if trigger_count enforced)")
    
    # Clear old files
    print(f"\n1. Clearing old files...")
    clear_files()
    initial_count = count_files()
    print(f"   Files before test: {initial_count}")
    
    # Trigger
    print(f"\n2. Triggering UTSC via API...")
    if not trigger_utsc(repeat_period_ms, freerun_duration_ms, trigger_count):
        print(f"   ❌ Failed to trigger")
        return None
    print(f"   ✅ Triggered")
    
    # Wait and monitor
    print(f"\n3. Monitoring for {wait_time}s...")
    for i in range(wait_time):
        time.sleep(1)
        if (i + 1) % 5 == 0:
            count = count_files()
            print(f"   [{i+1:2d}s] Files: {count}")
    
    # Final count
    time.sleep(2)
    final_count = count_files()
    
    print(f"\n4. Results:")
    print(f"   Files generated: {final_count}")
    print(f"   Theoretical (by duration): {theoretical}")
    print(f"   Trigger count limit: {min(trigger_count, 10)}")
    
    if final_count == theoretical:
        print(f"   ✅ MATCHES duration/period (E6000 follows spec)")
    elif final_count == min(trigger_count, 10):
        print(f"   ⚠️  MATCHES trigger_count limit (E6000 firmware bug)")
    else:
        print(f"   ❓ Unexpected result")
    
    return {
        'name': name,
        'theoretical': theoretical,
        'actual': final_count,
        'trigger_count': trigger_count
    }

# Main test
print("="*80)
print("E6000 FreeRunning Mode Test - FINAL VERSION")
print("Question: Does it respect freerun_duration or enforce trigger_count=10?")
print("="*80)

results = []

# Test 1: 20 seconds with count=10
results.append(run_test(
    "TEST 1: 20s freerun, trigger_count=10",
    1000, 20000, 10, 22
))

time.sleep(5)

# Test 2: 20 seconds with count=30
results.append(run_test(
    "TEST 2: 20s freerun, trigger_count=30", 
    1000, 20000, 30, 22
))

# Summary
print(f"\n{'='*80}")
print("SUMMARY")
print(f"{'='*80}")

for r in results:
    if r:
        print(f"\n{r['name']}")
        print(f"  Theoretical: {r['theoretical']} files")
        print(f"  Actual: {r['actual']} files")
        print(f"  Trigger count: {r['trigger_count']}")

if results[0] and results[1]:
    if results[0]['actual'] == results[0]['theoretical'] and results[1]['actual'] == results[1]['theoretical']:
        print(f"\n✅ CONCLUSION: E6000 respects freerun_duration as documented")
    elif results[0]['actual'] <= 10 and results[1]['actual'] <= 10:
        print(f"\n❌ CONCLUSION: E6000 has 10-file hard limit (firmware bug)")
    else:
        print(f"\n❓ CONCLUSION: Inconclusive - needs manual investigation")

print(f"\n{'='*80}")
