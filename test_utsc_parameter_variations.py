#!/usr/bin/env python3
"""
Test UTSC with various parameter combinations to understand E6000 behavior
Based on E6000 CER User Guide which states:
- FreeRunning mode: Uses freerun_duration + repeat_period
- IdleSID/CM_MAC modes: Uses trigger_count (max 10)

Testing hypothesis: Does E6000 incorrectly apply trigger_count to FreeRunning mode?
"""
import subprocess
import time
import requests
import json
import sys

MAC = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT = 1074339840
COMMUNITY = "Z1gg0Sp3c1@l"
BACKEND_URL = "http://localhost:8000"

# OID base for UTSC config
BASE_OID = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"

# Test scenarios
TEST_SCENARIOS = [
    {
        "name": "Baseline: 1s repeat, 10s freerun, trigger_count=10",
        "repeat_period_ms": 1000,
        "freerun_duration_ms": 10000,
        "trigger_count": 10,
        "expected_files": "10 (based on 10s/1s)",
        "wait_time": 12
    },
    {
        "name": "Test A: 1s repeat, 20s freerun, trigger_count=10",
        "repeat_period_ms": 1000,
        "freerun_duration_ms": 20000,
        "trigger_count": 10,
        "expected_files": "20 if count ignored, 10 if count enforced",
        "wait_time": 22
    },
    {
        "name": "Test B: 3s repeat, 60s freerun, trigger_count=20",
        "repeat_period_ms": 3000,
        "freerun_duration_ms": 60000,
        "trigger_count": 20,
        "expected_files": "20 if count ignored, 10 if count enforced",
        "wait_time": 65
    },
    {
        "name": "Test C: 2s repeat, 30s freerun, trigger_count=50",
        "repeat_period_ms": 2000,
        "freerun_duration_ms": 30000,
        "trigger_count": 50,
        "expected_files": "15 if count ignored, 10 if count enforced",
        "wait_time": 32
    },
    {
        "name": "Test D: 1s repeat, 5s freerun, trigger_count=3",
        "repeat_period_ms": 1000,
        "freerun_duration_ms": 5000,
        "trigger_count": 3,
        "expected_files": "5 if duration used, 3 if count used",
        "wait_time": 7
    }
]

def get_file_count():
    """Count UTSC files on TFTP server via SSH"""
    cmd = 'ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab ls -1 /var/lib/tftpboot/utsc_test_* 2>/dev/null | wc -l"'
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return int(result.stdout.strip())
        return 0
    except:
        return 0

def clear_utsc_files():
    """Remove old UTSC files"""
    cmd = 'ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab rm -f /var/lib/tftpboot/utsc_test_* 2>/dev/null"'
    subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
    time.sleep(1)

def query_cmts_oids(scenario_name):
    """Query CMTS to verify what was actually set"""
    repeat_oid = f"{BASE_OID}.18.{RF_PORT}"
    freerun_oid = f"{BASE_OID}.19.{RF_PORT}"
    trigger_oid = f"{BASE_OID}.20.{RF_PORT}"
    
    cmd = f'ssh -p 65001 access-engineering.nl "docker exec pypnm-agent-lab snmpget -v2c -Ov -c \'{COMMUNITY}\' {CMTS_IP} {repeat_oid} {freerun_oid} {trigger_oid} 2>&1 | grep -E \'^(Gauge32|INTEGER|Counter|Unsigned32):\'"'
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    
    if result.returncode == 0 and result.stdout.strip():
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 3:
            repeat_val = lines[0].split(':')[1].strip() if ':' in lines[0] else 'N/A'
            freerun_val = lines[1].split(':')[1].strip() if ':' in lines[1] else 'N/A'
            trigger_val = lines[2].split(':')[1].strip() if ':' in lines[2] else 'N/A'
            print(f"      CMTS OIDs: RepeatPeriod={repeat_val}us, FreeRunDuration={freerun_val}ms, TriggerCount={trigger_val}")
            return repeat_val, freerun_val, trigger_val
    
    print(f"      ⚠️  Could not read CMTS OIDs")
    return None, None, None

def trigger_utsc(scenario):
    """Trigger UTSC with specific parameters"""
    url = f"{BACKEND_URL}/api/pypnm/upstream/utsc/start/{MAC}"
    payload = {
        "cmts_ip": CMTS_IP,
        "rf_port_ifindex": RF_PORT,
        "community": COMMUNITY,
        "tftp_ip": "172.16.6.101",
        "trigger_mode": 2,  # FreeRunning
        "repeat_period_ms": scenario["repeat_period_ms"],
        "freerun_duration_ms": scenario["freerun_duration_ms"],
        "trigger_count": scenario["trigger_count"]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            success = result.get('success', False)
            if not success:
                print(f"      ⚠️  API returned success=False: {result.get('message', result.get('error', 'Unknown'))}")
            return success
        else:
            print(f"      ❌ HTTP {response.status_code}: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"      ❌ API Error: {e}")
        return False

def run_test_scenario(scenario, scenario_num, total):
    """Execute a single test scenario"""
    print(f"\n{'='*80}")
    print(f"TEST {scenario_num}/{total}: {scenario['name']}")
    print(f"{'='*80}")
    print(f"Parameters:")
    print(f"  - repeat_period_ms: {scenario['repeat_period_ms']}")
    print(f"  - freerun_duration_ms: {scenario['freerun_duration_ms']}")
    print(f"  - trigger_count: {scenario['trigger_count']}")
    print(f"Expected: {scenario['expected_files']} files")
    
    # Clear old files
    print(f"\n1. Clearing old UTSC files...")
    clear_utsc_files()
    initial_count = get_file_count()
    print(f"   Files before test: {initial_count}")
    
    # Trigger UTSC
    print(f"\n2. Triggering UTSC...")
    success = trigger_utsc(scenario)
    if not success:
        print(f"   ❌ Failed to trigger UTSC")
        return None
    print(f"   ✅ UTSC triggered")
    
    # Wait a moment then query OIDs
    time.sleep(0.5)
    print(f"\n3. Verifying CMTS configuration...")
    repeat_val, freerun_val, trigger_val = query_cmts_oids(scenario['name'])
    
    # Wait for test to complete
    print(f"\n4. Waiting {scenario['wait_time']}s for test to complete...")
    for i in range(scenario['wait_time']):
        time.sleep(1)
        if (i + 1) % 5 == 0:
            count = get_file_count()
            print(f"   [{i+1}s] Files so far: {count}")
    
    # Final count
    time.sleep(2)
    final_count = get_file_count()
    
    print(f"\n5. Results:")
    print(f"   Files generated: {final_count}")
    print(f"   Expected: {scenario['expected_files']}")
    
    # Analysis
    theoretical_by_duration = scenario['freerun_duration_ms'] // scenario['repeat_period_ms']
    print(f"\n   Analysis:")
    print(f"   - Theoretical by duration/period: {theoretical_by_duration} files")
    print(f"   - Trigger count limit: {scenario['trigger_count']} files")
    print(f"   - Actual result: {final_count} files")
    
    if final_count == min(10, scenario['trigger_count']):
        print(f"   ⚠️  Result matches trigger_count (or 10-file limit)")
    elif final_count == theoretical_by_duration:
        print(f"   ✅ Result matches duration/period calculation")
    elif final_count < theoretical_by_duration:
        print(f"   ⚠️  Result is less than expected - possible limit at 10 files")
    else:
        print(f"   ❓ Unexpected result")
    
    return {
        'scenario': scenario['name'],
        'repeat_period_ms': scenario['repeat_period_ms'],
        'freerun_duration_ms': scenario['freerun_duration_ms'],
        'trigger_count': scenario['trigger_count'],
        'theoretical_files': theoretical_by_duration,
        'actual_files': final_count,
        'cmts_repeat': repeat_val,
        'cmts_freerun': freerun_val,
        'cmts_trigger': trigger_val
    }

def main():
    print("="*80)
    print("UTSC Parameter Variation Testing")
    print("Testing E6000 FreeRunning mode behavior")
    print("="*80)
    
    # Check backend is running
    try:
        response = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if response.status_code != 200:
            print("❌ Backend not responding. Start with: ./start.sh")
            sys.exit(1)
    except:
        print("❌ Backend not running. Start with: ./start.sh")
        sys.exit(1)
    
    results = []
    
    for i, scenario in enumerate(TEST_SCENARIOS, 1):
        result = run_test_scenario(scenario, i, len(TEST_SCENARIOS))
        if result:
            results.append(result)
        
        if i < len(TEST_SCENARIOS):
            print(f"\n{'='*80}")
            print(f"Waiting 10 seconds before next test...")
            print(f"{'='*80}")
            time.sleep(10)
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY OF ALL TESTS")
    print(f"{'='*80}\n")
    
    print(f"{'Test':<8} {'Repeat(ms)':<12} {'Freerun(ms)':<14} {'TrigCount':<11} {'Theory':<8} {'Actual':<8} {'Behavior'}")
    print(f"{'-'*8} {'-'*12} {'-'*14} {'-'*11} {'-'*8} {'-'*8} {'-'*40}")
    
    for r in results:
        behavior = ""
        if r['actual_files'] == min(10, r['trigger_count']):
            behavior = "Limited by trigger_count/10"
        elif r['actual_files'] == r['theoretical_files']:
            behavior = "Matches duration/period"
        else:
            behavior = "Unexpected"
        
        print(f"{results.index(r)+1:<8} {r['repeat_period_ms']:<12} {r['freerun_duration_ms']:<14} "
              f"{r['trigger_count']:<11} {r['theoretical_files']:<8} {r['actual_files']:<8} {behavior}")
    
    print(f"\n{'='*80}")
    print("CONCLUSION:")
    
    # Check if all results hit 10-file limit
    all_limited_to_10 = all(r['actual_files'] <= 10 for r in results)
    some_match_theory = any(r['actual_files'] == r['theoretical_files'] for r in results)
    
    if all_limited_to_10 and not some_match_theory:
        print("❌ E6000 appears to have a 10-file hard limit in FreeRunning mode")
        print("   This contradicts the user guide which says trigger_count is only")
        print("   used for IdleSID and CM_MAC modes.")
    elif some_match_theory:
        print("✅ E6000 respects freerun_duration and repeat_period as documented")
    else:
        print("❓ Results are inconclusive - manual investigation needed")
    
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
