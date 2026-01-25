#!/usr/bin/env python3
"""
Simple UTSC test script - direct SNMP control of E6000
Bypasses PyPNM API for testing
"""

import subprocess
import time
import glob
import os
import struct
from datetime import datetime

# Configuration
CMTS_IP = "172.16.6.212"
COMMUNITY = "Z1gg0Sp3c1@l"
RF_PORT = 1074339840  # us-conn 1/0/0
TFTP_PATH = "/var/lib/tftpboot"
FILENAME_PREFIX = "utsc_test"

# SNMP OID bases
UTSC_CFG = "1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1"
UTSC_CTRL = "1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1"
UTSC_STATUS = "1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1"

# Status values
STATUS_INACTIVE = 2
STATUS_BUSY = 3
STATUS_SAMPLE_READY = 4
STATUS_ERROR = 5


def snmp_set(oid, value_type, value):
    """Set SNMP value."""
    cmd = ['snmpset', '-v2c', '-c', COMMUNITY, CMTS_IP, oid, value_type, str(value)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        print(f"  SNMP SET failed: {result.stderr.strip()}")
        return False
    return True


def snmp_get(oid):
    """Get SNMP value."""
    cmd = ['snmpget', '-v2c', '-c', COMMUNITY, CMTS_IP, oid]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def get_utsc_status():
    """Get UTSC measurement status."""
    idx = f"{RF_PORT}.1"
    result = snmp_get(f"{UTSC_STATUS}.1.{idx}")
    if result:
        # Parse "INTEGER: sampleReady(4)" -> 4
        if 'INTEGER:' in result:
            match = result.split('(')[-1].rstrip(')')
            try:
                return int(match)
            except:
                pass
    return None


def configure_utsc():
    """Configure UTSC for FreeRunning mode."""
    print("Configuring UTSC...")
    
    idx = f"{RF_PORT}.1"
    
    # TriggerMode = 2 (FreeRunning)
    print("  Setting TriggerMode=2 (FreeRunning)")
    snmp_set(f"{UTSC_CFG}.3.{idx}", 'i', 2)
    
    # NumBins = 800 (maps to 1024 hardware bins)
    print("  Setting NumBins=800")
    snmp_set(f"{UTSC_CFG}.10.{idx}", 'u', 800)
    
    # CenterFreq = 50 MHz (50000000 Hz)
    print("  Setting CenterFreq=50MHz")
    snmp_set(f"{UTSC_CFG}.8.{idx}", 'u', 50000000)
    
    # Span = 80 MHz (80000000 Hz) 
    print("  Setting Span=80MHz")
    snmp_set(f"{UTSC_CFG}.9.{idx}", 'u', 80000000)
    
    # Filename
    print(f"  Setting Filename={FILENAME_PREFIX}")
    snmp_set(f"{UTSC_CFG}.12.{idx}", 's', f"/pnm/utsc/{FILENAME_PREFIX}")
    
    # RepeatPeriod = 1000000 us (1 second)
    print("  Setting RepeatPeriod=1s")
    snmp_set(f"{UTSC_CFG}.18.{idx}", 'u', 1000000)
    
    # FreeRunDuration = 60000 ms (60 seconds)
    print("  Setting FreeRunDuration=60s")
    snmp_set(f"{UTSC_CFG}.19.{idx}", 'u', 60000)
    
    # TriggerCount - NOT SETTING (notWritable on E6000 in FreeRunning mode)
    # print("  Setting TriggerCount=1")
    # snmp_set(f"{UTSC_CFG}.26.{idx}", 'u', 1)
    
    # DestinationIndex = 1 (use pre-configured TFTP)
    print("  Setting DestinationIndex=1")
    snmp_set(f"{UTSC_CFG}.24.{idx}", 'u', 1)
    
    print("Configuration complete!")


def trigger_utsc():
    """Trigger UTSC test."""
    idx = f"{RF_PORT}.1"
    return snmp_set(f"{UTSC_CTRL}.1.{idx}", 'i', 1)


def parse_utsc_file(filepath):
    """Parse UTSC binary file and return spectrum data."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        
        if len(data) < 328:
            return None
        
        # Header is 328 bytes, then amplitude samples (big-endian int16)
        samples = data[328:]
        amplitudes = []
        for i in range(0, len(samples), 2):
            if i + 1 < len(samples):
                val = struct.unpack('>h', samples[i:i+2])[0]
                amplitudes.append(val / 10.0)  # 0.1 dBmV to dBmV
        
        return amplitudes
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return None


def watch_files(duration=60, min_buffer_size=10):
    """Watch for UTSC files, buffer until threshold, then stream evenly."""
    print(f"\nWatching for files (duration={duration}s)...")
    print(f"Buffering until {min_buffer_size} files collected before streaming")
    print(f"⚠️  E6000 FreeRunning mode generates continuously for {duration}s")
    
    pattern = f"{TFTP_PATH}/{FILENAME_PREFIX}_*"
    processed = set()
    start_time = time.time()
    file_count = 0
    burst_count = 0
    last_status = None
    
    # Buffer for smooth streaming
    file_buffer = []
    last_stream_time = 0
    stream_interval = 1.0  # Stream 1 file per second
    streaming_started = False
    
    # Single trigger for FreeRunning mode
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting FreeRunning capture...")
    trigger_utsc()
    print("  Waiting for files...")
    
    while time.time() - start_time < duration:
        current_time = time.time()
        
        # Poll status
        status = get_utsc_status()
        if status != last_status:
            status_names = {2: 'inactive', 3: 'busy', 4: 'sampleReady', 5: 'error'}
            print(f"  [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Status: {status_names.get(status, status)}")
            last_status = status
        
        # Check for new files
        files = glob.glob(pattern)
        new_files = [f for f in files if f not in processed]
        
        if new_files:
            for filepath in sorted(new_files, key=os.path.getmtime):
                processed.add(filepath)
                # Add to buffer with parsed data
                amplitudes = parse_utsc_file(filepath)
                if amplitudes:
                    file_buffer.append({
                        'filepath': filepath,
                        'amplitudes': amplitudes,
                        'collected_at': current_time
                    })
            
            if new_files:
                burst_count += 1
                print(f"  [BUFFER] Collected {len(new_files)} files (buffer: {len(file_buffer)})")
        
        # Check if we've reached minimum buffer size to start streaming
        if not streaming_started and len(file_buffer) >= min_buffer_size:
            streaming_started = True
            print(f"\n  ✅ Buffer threshold reached ({len(file_buffer)} files) - Starting stream to scigraph!")
            print()
        
        # Stream from buffer at steady rate
        if streaming_started and file_buffer and (current_time - last_stream_time) >= stream_interval:
            item = file_buffer.pop(0)
            file_count += 1
            last_stream_time = current_time
            
            amplitudes = item['amplitudes']
            min_amp = min(amplitudes)
            max_amp = max(amplitudes)
            avg_amp = sum(amplitudes) / len(amplitudes)
            filename = os.path.basename(item['filepath'])
            latency = current_time - item['collected_at']
            
            print(f"  [STREAM #{file_count:3d}] {filename[-23:]}: "
                  f"{len(amplitudes):4d} bins, {min_amp:6.1f}/{avg_amp:6.1f}/{max_amp:5.1f} dBmV "
                  f"(buffer: {len(file_buffer)}, latency: {latency:.1f}s)")
        
        time.sleep(0.05)  # 50ms polling
    
    print(f"\n{'=' * 50}")
    print(f"=== Summary ===")
    print(f"Total files streamed: {file_count}")
    print(f"Total bursts collected: {burst_count}")
    print(f"Files remaining in buffer: {len(file_buffer)}")
    print(f"Duration: {duration}s")
    print(f"Stream rate: {file_count/duration:.2f} files/sec")


def main():
    print("=" * 60)
    print("UTSC Simple Test - E6000")
    print("=" * 60)
    print(f"CMTS: {CMTS_IP}")
    print(f"RF Port: {RF_PORT}")
    print(f"TFTP Path: {TFTP_PATH}")
    print()
    
    # Configure once
    configure_utsc()
    
    # Watch files - single trigger, buffer to 20, then stream
    watch_files(duration=60, min_buffer_size=20)


if __name__ == "__main__":
    main()