#!/usr/bin/env python3
"""
FIXED - Find physical upstream port using docsIfCmtsCmPtr table
"""

import subprocess
import re
import sys

def run_cmd(cmd):
    """Run shell command"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()

def mac_to_decimal(mac):
    """Convert MAC address to decimal format for SNMP OID"""
    # Remove any separators and convert to lowercase
    clean_mac = mac.replace(':', '').replace('-', '').replace('.', '').lower()
    
    # Validate MAC length
    if len(clean_mac) != 12:
        raise ValueError(f"Invalid MAC address length: {mac}")
    
    # Convert each hex pair to decimal
    decimal_parts = []
    for i in range(0, 12, 2):
        hex_pair = clean_mac[i:i+2]
        try:
            decimal_parts.append(str(int(hex_pair, 16)))
        except ValueError:
            raise ValueError(f"Invalid hex in MAC: {hex_pair}")
    
    return '.'.join(decimal_parts)

def get_cmindex_from_cmptr(cmts, community, mac):
    """Get cmIndex from docsIfCmtsCmPtr table"""
    print(f"Getting cmIndex for modem {mac}...")
    
    try:
        mac_decimal = mac_to_decimal(mac)
    except ValueError as e:
        print(f"✗ MAC address error: {e}")
        return None
    
    # Query docsIfCmtsCmPtr
    oid = f".1.3.6.1.2.1.10.127.1.3.7.1.2.{mac_decimal}"
    cmd = f"snmpget -v2c -c {community} {cmts} {oid}"
    output = run_cmd(cmd)
    
    if 'INTEGER:' in output:
        # Extract cmIndex
        cmindex = output.split('INTEGER:')[-1].strip()
        print(f"✓ cmIndex found: {cmindex}")
        return cmindex
    else:
        print(f"✗ Could not get cmIndex: {output}")
        return None

def find_upstream_channels(cmts, community, cmindex):
    """Find upstream channels using cmIndex"""
    print(f"\nSearching for upstream channels with cmIndex {cmindex}...")
    
    upstream_channels = []
    
    # 1. Check DOCSIS 3.0 ATDMA channels
    print("1. Checking DOCSIS 3.0 ATDMA table...")
    cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.4.1.4491.2.1.20.1.4"
    output = run_cmd(cmd)
    
    for line in output.split('\n'):
        if f'.{cmindex}.' in line:
            try:
                # Extract upstream ifIndex from OID
                parts = line.split('=')
                oid_part = parts[0].strip()
                oid_parts = oid_part.split('.')
                
                for i, part in enumerate(oid_parts):
                    if part == cmindex and i + 1 < len(oid_parts):
                        upstream = int(oid_parts[i + 1])
                        if upstream > 0:
                            upstream_channels.append(upstream)
                            print(f"   Found ATDMA channel: ifIndex {upstream}")
            except:
                pass
    
    # 2. Check DOCSIS 3.1 OFDMA channels
    print("\n2. Checking DOCSIS 3.1 OFDMA table...")
    cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.4.1.4491.2.1.28.1.5.1"
    output = run_cmd(cmd)
    
    for line in output.split('\n'):
        if f'.{cmindex}.' in line:
            try:
                parts = line.split('=')
                oid_part = parts[0].strip()
                oid_parts = oid_part.split('.')
                
                for i, part in enumerate(oid_parts):
                    if part == cmindex and i + 1 < len(oid_parts):
                        upstream = int(oid_parts[i + 1])
                        if upstream > 800000000:  # OFDMA ifIndexes are large
                            upstream_channels.append(upstream)
                            print(f"   Found OFDMA channel: ifIndex {upstream}")
            except:
                pass
    
    # Remove duplicates and sort
    return sorted(set(upstream_channels))

def get_interface_info(cmts, community, ifindex):
    """Get interface description"""
    cmd = f"snmpget -v2c -c {community} -Ovq {cmts} .1.3.6.1.2.1.2.2.1.2.{ifindex}"
    return run_cmd(cmd)

def find_physical_port(cmts, community, upstream_ifindex):
    """Find physical port for upstream channel"""
    print(f"\nFinding physical port for upstream ifIndex {upstream_ifindex}...")
    
    # Get upstream description
    descr = get_interface_info(cmts, community, upstream_ifindex)
    print(f"   Upstream description: {descr}")
    
    # Try Cisco MIB first
    cmd = f"snmpget -v2c -c {community} -Ovq {cmts} .1.3.6.1.4.1.9.9.116.1.4.1.1.2.{upstream_ifindex}"
    physical = run_cmd(cmd)
    
    if physical and 'No Such' not in physical and physical.strip().isdigit():
        phys_descr = get_interface_info(cmts, community, int(physical))
        print(f"   ✓ Found via Cisco MIB!")
        print(f"   Physical ifIndex: {physical}")
        print(f"   Description: {phys_descr}")
        return {
            'physical_ifindex': int(physical),
            'description': phys_descr,
            'method': 'cisco_mib'
        }
    
    # Try to extract slot from description
    slot = None
    patterns = [
        r'(\d+)/',          # 1/scq/20.0
        r'slot\s*(\d+)',    # slot 1
        r'(RPS\d+-\d+)',    # RPS01-1
    ]
    
    for pattern in patterns:
        match = re.search(pattern, descr, re.IGNORECASE)
        if match:
            slot = match.group(1) if match.groups() else match.group(0)
            break
    
    if slot:
        print(f"   Extracted slot/blade: {slot}")
        
        # Find us-conn ports
        cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.2.1.2.2.1.2"
        output = run_cmd(cmd)
        
        for line in output.split('\n'):
            if 'us-conn' in line.lower() and slot in line:
                try:
                    parts = line.split('=')
                    oid_part = parts[0].strip()
                    phys_ifindex = int(oid_part.split('.')[-1])
                    phys_descr = parts[1].split(':', 1)[-1].strip().strip('"')
                    
                    print(f"   ✓ Found matching us-conn port!")
                    print(f"   Physical ifIndex: {phys_ifindex}")
                    print(f"   Description: {phys_descr}")
                    return {
                        'physical_ifindex': phys_ifindex,
                        'description': phys_descr,
                        'method': 'slot_match'
                    }
                except:
                    continue
    
    return None

def main():
    if len(sys.argv) < 4:
        print("Usage: python find_physical_final.py <cmts_ip> <community> <mac>")
        print("Example: python find_physical_final.py 172.16.6.212 public e4:57:40:f7:12:99")
        sys.exit(1)
    
    cmts = sys.argv[1]
    community = sys.argv[2]
    mac = sys.argv[3]
    
    print("=" * 80)
    print(f"FINDING PHYSICAL PORT FROM docsIfCmtsCmPtr")
    print(f"CMTS: {cmts}")
    print(f"MAC: {mac}")
    print("=" * 80)
    
    # Step 1: Get cmIndex from docsIfCmtsCmPtr
    cmindex = get_cmindex_from_cmptr(cmts, community, mac)
    
    if not cmindex:
        print("\nTrying alternative: Checking if modem is in status table...")
        
        # Try to find in status table directly
        mac_search = mac.replace(':', '').lower()
        cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.2.1.10.127.1.3.3.1.2 | grep -i '{mac_search}'"
        output = run_cmd(cmd)
        
        if output:
            print(f"✓ Found in docsIfCmtsCmStatusTable:")
            print(f"  {output}")
            
            # Parse downstream from output
            lines = output.split('\n')
            for line in lines:
                if '=' in line:
                    parts = line.split('=')
                    oid_part = parts[0].strip()
                    oid_parts = oid_part.split('.')
                    
                    # Find column 2 position
                    for i, part in enumerate(oid_parts):
                        if part == '2' and i + 1 < len(oid_parts):
                            downstream = oid_parts[i + 1]
                            print(f"  Downstream ifIndex: {downstream}")
        else:
            print("✗ Modem not found in any tables")
            sys.exit(1)
    
    # Step 2: Find upstream channels
    upstream_channels = find_upstream_channels(cmts, community, cmindex)
    
    if not upstream_channels:
        print(f"\n✗ No upstream channels found for this modem")
        
        # Try direct approach: Check all upstreams on CMTS
        print("\nChecking all upstream interfaces on CMTS...")
        cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.2.1.2.2.1.2 | grep -i upstream"
        output = run_cmd(cmd)
        
        if output:
            print(f"Upstream interfaces found:")
            for line in output.split('\n')[:10]:
                if line:
                    print(f"  {line}")
        
        sys.exit(1)
    
    print(f"\n✓ Found {len(upstream_channels)} upstream channel(s): {upstream_channels}")
    
    # Step 3: Find physical ports
    print("\n" + "=" * 80)
    print("PHYSICAL PORT DETECTION")
    print("=" * 80)
    
    physical_ports = []
    
    for upstream in upstream_channels:
        print(f"\nProcessing upstream channel ifIndex {upstream}:")
        
        port_info = find_physical_port(cmts, community, upstream)
        
        if port_info:
            physical_ports.append({
                'upstream_ifindex': upstream,
                **port_info
            })
        else:
            print(f"  ✗ Physical port not found")
    
    # Step 4: Results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    if physical_ports:
        print(f"\n✓ PHYSICAL PORTS FOUND:")
        for i, port in enumerate(physical_ports, 1):
            print(f"\n{i}. Logical Upstream:")
            print(f"   ifIndex: {port['upstream_ifindex']}")
            
            print(f"\n   Physical Port:")
            print(f"   ifIndex: {port['physical_ifindex']}")
            print(f"   Description: {port['description']}")
            print(f"   Method: {port['method']}")
    else:
        print(f"\n✗ No physical ports identified")
        
        # Show all us-conn ports
        print(f"\nAll us-conn ports on CMTS:")
        cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.2.1.2.2.1.2 | grep -i us-conn"
        output = run_cmd(cmd)
        
        if output:
            for line in output.split('\n'):
                if line:
                    print(f"  {line}")
        else:
            print("  No us-conn ports found")
            
            # Try alternative names
            print(f"\nLooking for any physical upstream ports...")
            cmd = f"snmpwalk -v2c -c {community} {cmts} .1.3.6.1.2.1.2.2.1.2 | grep -i -E '(rf|port.*[0-9]|connector)'"
            output = run_cmd(cmd)
            for line in output.split('\n')[:10]:
                if line:
                    print(f"  {line}")

if __name__ == "__main__":
    main()