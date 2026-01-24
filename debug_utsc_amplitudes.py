#!/usr/bin/env python3
"""
Debug UTSC - Parse files and show amplitudes
"""

import subprocess
import time
import struct
import os
from datetime import datetime

TFTP_PATH = "/var/lib/tftpboot"
FILENAME_PREFIX = "utsc_e45740f71320"


def parse_utsc_file(filepath):
    """Parse UTSC binary file and return spectrum data."""
    try:
        # Use SSH to read the remote file
        cmd = ['ssh', 'access-engineering.nl', f'cat {filepath}']
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        
        if result.returncode != 0:
            print(f"Error reading {filepath}: {result.stderr.decode()}")
            return None
        
        data = result.stdout
        
        if len(data) < 328:
            print(f"File too short: {len(data)} bytes (need at least 328)")
            return None
        
        # Parse header
        print(f"\n{'='*80}")
        print(f"File: {os.path.basename(filepath)}")
        print(f"Total size: {len(data)} bytes")
        print(f"Header: {len(data[:328])} bytes")
        print(f"Data: {len(data[328:])} bytes")
        
        # Header is 328 bytes, then amplitude samples (big-endian int16)
        samples = data[328:]
        amplitudes = []
        
        for i in range(0, len(samples), 2):
            if i + 1 < len(samples):
                val = struct.unpack('>h', samples[i:i+2])[0]
                amplitudes.append(val / 10.0)  # 0.1 dBmV to dBmV
        
        if amplitudes:
            min_amp = min(amplitudes)
            max_amp = max(amplitudes)
            avg_amp = sum(amplitudes) / len(amplitudes)
            
            print(f"Bins: {len(amplitudes)}")
            print(f"Min amplitude: {min_amp:.1f} dBmV")
            print(f"Max amplitude: {max_amp:.1f} dBmV")
            print(f"Avg amplitude: {avg_amp:.1f} dBmV")
            
            # Show first 20 and last 20 values
            print(f"\nFirst 20 bins:")
            for i in range(min(20, len(amplitudes))):
                print(f"  Bin {i:4d}: {amplitudes[i]:7.1f} dBmV")
            
            if len(amplitudes) > 40:
                print(f"\nLast 20 bins:")
                for i in range(len(amplitudes)-20, len(amplitudes)):
                    print(f"  Bin {i:4d}: {amplitudes[i]:7.1f} dBmV")
            
            # Show distribution
            print(f"\nAmplitude distribution:")
            ranges = [
                (-100, -50, "Very low"),
                (-50, -25, "Low"),
                (-25, 0, "Below avg"),
                (0, 15, "Normal"),
                (15, 30, "High"),
                (30, 100, "Very high")
            ]
            for min_r, max_r, label in ranges:
                count = sum(1 for a in amplitudes if min_r <= a < max_r)
                if count > 0:
                    pct = (count / len(amplitudes)) * 100
                    print(f"  {label:12s} ({min_r:4d} to {max_r:4d} dBmV): {count:4d} bins ({pct:5.1f}%)")
        
        return amplitudes
    
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("=" * 80)
    print("UTSC File Debug - Amplitude Analysis")
    print("=" * 80)
    
    # Get list of UTSC files
    cmd = ['ssh', 'access-engineering.nl', f'ls -t {TFTP_PATH}/{FILENAME_PREFIX}_* 2>/dev/null | head -10']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("No UTSC files found")
        return
    
    files = result.stdout.strip().split('\n')
    print(f"\nFound {len(files)} files")
    
    for filepath in files:
        if filepath:
            parse_utsc_file(filepath)
            time.sleep(0.5)


if __name__ == "__main__":
    main()
