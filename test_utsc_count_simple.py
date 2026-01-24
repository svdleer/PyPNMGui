#!/usr/bin/env python3
"""
Simple test: Does E6000 respect freerun_duration or enforce trigger_count=10 limit?
Uses direct SNMP commands to avoid API endpoint issues
"""
import subprocess
import time
import os

MAC = "e4:57:40:f0:3a:14"
CMTS_IP = "172.16.6.212"
RF_PORT = "1074339840"
COMMUNITY = "Z1gg0Sp3c1@l"
TFTP_PATH = "/app/data/tftp"  # GUI container's TFTP mount point
FILENAME_PREFIX = "utsc_count_test"

# OID bases
UTSC_CFG = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
UTSC_CTRL = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1"

def snmp_set(oid, type_flag, value):
    """Set SNMP value via agent container"""
    cmd = f'docker exec pypnm-agent-lab snmpset -v2c -c \'{COMMUNITY}\' {CMTS_IP} {oid} {type_flag} {value}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    return result.returncode == 0

def trigger_utsc():
    """Trigger UTSC via SNMP"""
    oid = f"{UTSC_CTRL}.1.{RF_PORT}.1"
    return snmp_set(oid, 'i', '1')

def count_files():
    """Count UTSC files - check both possible locations"""
    # Try GUI container's TFTP mount
    try:
        files = [f for f in os.listdir(TFTP_PATH) if f.startswith(FILENAME_PREFIX)]
        return len(files)
    except:
        pass
    
    # Fallback: check agent container
    cmd = f'docker exec pypnm-agent-lab ls -1 /var/lib/tftpboot/{FILENAME_PREFIX}_* 2>/dev/null | wc -l'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0

def clear_files():
    """Remove old test files from both locations"""
    # Clear from GUI container's mount
    try:
        for f in os.listdir(TFTP_PATH):
            if f.startswith(FILENAME_PREFIX):
                os.remove(os.path.join(TFTP_PATH, f))
    except:
        pass
    
    # Also clear from agent container
    cmd = f'docker exec pypnm-agent-lab rm -f /var/lib/tftpboot/{FILENAME_PREFIX}_* 2>/dev/null'
    subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
    time.sleep(1)

def configure_utsc(repeat_period_us, freerun_duration_ms, trigger_count):
    """Configure UTSC parameters"""
    idx = f".{RF_PORT}.1"
    
    print(f"  Setting TriggerMode=2 (FreeRunning)")
    snmp_set(f"{UTSC_CFG}.3{idx}", 'i', '2')
    
    print(f"  Setting CenterFreq=30MHz")
    snmp_set(f"{UTSC_CFG}.4{idx}", 'u', '30000000')
    
    print(f"  Setting Span=80MHz")
    snmp_set(f"{UTSC_CFG}.5{idx}", 'u', '80000000')
    
    print(f"  Setting NumBins=800")
    snmp_set(f"{UTSC_CFG}.6{idx}", 'u', '800')
    
    print(f"  Setting Filename={FILENAME_PREFIX}")
    snmp_set(f"{UTSC_CFG}.12{idx}", 's', f'/pnm/utsc/{FILENAME_PREFIX}')
    
    print(f"  Setting RepeatPeriod={repeat_period_us}us ({repeat_period_us/1000}ms)")
    snmp_set(f"{UTSC_CFG}.18{idx}", 'u', str(repeat_period_us))
    
    print(f"  Setting FreeRunDuration={freerun_duration_ms}ms")
    snmp_set(f"{UTSC_CFG}.19{idx}", 'u', str(freerun_duration_ms))
    
    print(f"  Setting TriggerCount={trigger_count}")
    snmp_set(f"{UTSC_CFG}.20{idx}", 'u', str(trigger_count))
    
    print(f"  Setting DestinationIndex=1")
    snmp_set(f"{UTSC_CFG}.24{idx}", 'u', '1')

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
    
    # Configure
    print(f"\n2. Configuring UTSC...")
    configure_utsc(repeat_period_ms * 1000, freerun_duration_ms, trigger_count)
    
    # Trigger
    print(f"\n3. Triggering UTSC...")
    if trigger_utsc():
        print(f"   ✅ Triggered")
    else:
        print(f"   ❌ Failed to trigger")
        return None
    
    # Wait and monitor
    print(f"\n4. Monitoring for {wait_time}s...")
    for i in range(wait_time):
        time.sleep(1)
        if (i + 1) % 5 == 0:
            count = count_files()
            print(f"   [{i+1:2d}s] Files: {count}")
    
    # Final count
    time.sleep(2)
    final_count = count_files()
    
    print(f"\n5. Results:")
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
print("E6000 FreeRunning Mode Test")
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
