#!/usr/bin/env python3
"""
Test UTSC with modem's logical port discovery.

The idea: Instead of discovering which RF port a modem is on by walking all channels,
we can potentially use the modem's upstream channel ifIndex directly.
"""

import subprocess
import re
import sys

# Configuration
CMTS_IP = "172.16.6.212"
COMMUNITY = "Z1gg0Sp3c1@l"
MODEM_MAC = "e4:57:40:f7:13:20"  # Test modem


def snmp_get(oid):
    """Get SNMP value."""
    cmd = ['snmpget', '-v2c', '-c', COMMUNITY, CMTS_IP, oid]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def snmp_walk(oid):
    """Walk SNMP tree."""
    cmd = ['snmpwalk', '-v2c', '-c', COMMUNITY, CMTS_IP, oid]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return result.stdout.strip().split('\n')
    return []


def get_modem_index(mac):
    """Get modem's index from MAC address."""
    # Walk docsIf3CmtsCmRegStatusMacAddr to find the modem
    lines = snmp_walk('1.3.6.1.4.1.4491.2.1.20.1.3.1.2')
    mac_lower = mac.lower().replace('-', ':')
    
    for line in lines:
        if mac_lower in line.lower():
            # Parse: DOCS-IF3-MIB::docsIf3CmtsCmRegStatusMacAddr.3 = STRING: e4:57:40:f7:13:20
            match = re.search(r'\.(\d+)\s*=', line)
            if match:
                return int(match.group(1))
    return None


def get_modem_upstream_channels(cm_index):
    """Get modem's upstream channel ifIndexes from DOCS-IF3-MIB."""
    # Walk the parent table (docsIf3CmtsCmUsStatusTable) and filter by CM index
    # docsIf3CmtsCmUsStatusModulationType.cmIndex.usChIfIndex
    lines = snmp_walk('1.3.6.1.4.1.4491.2.1.20.1.4')
    channels = []
    
    for line in lines:
        # Parse: docsIf3CmtsCmUsStatusModulationType.3.843071811 = INTEGER: atdma(2)
        # We're looking for entries where first index is our cm_index
        pattern = rf'docsIf3CmtsCmUsStatusModulationType\.{cm_index}\.(\d+)\s*='
        match = re.search(pattern, line)
        if match:
            ifindex = int(match.group(1))
            if ifindex not in channels:
                channels.append(ifindex)
    
    return channels


def get_interface_info(ifindex):
    """Get interface name and type."""
    name = snmp_get(f'IF-MIB::ifName.{ifindex}')
    iftype = snmp_get(f'IF-MIB::ifType.{ifindex}')
    descr = snmp_get(f'IF-MIB::ifDescr.{ifindex}')
    return {
        'ifindex': ifindex,
        'name': name.split('=')[-1].strip() if name else 'unknown',
        'type': iftype.split('=')[-1].strip() if iftype else 'unknown',
        'descr': descr.split('=')[-1].strip() if descr else 'unknown'
    }


def find_rf_port_for_channel(ch_ifindex):
    """Find which RF port this logical channel belongs to.
    
    The channel name like 'cable-upstream 1/scq/160.0' indicates:
    - 1 = slot/module
    - scq = SC-QAM
    - 160.0 = channel
    
    We need to map this to an RF port ifIndex.
    """
    # Get the channel name
    name_result = snmp_get(f'IF-MIB::ifName.{ch_ifindex}')
    if not name_result:
        return None
    
    # Parse: cable-upstream 1/scq/160.0
    name = name_result.split('=')[-1].strip()
    match = re.search(r'cable-upstream\s+(\d+)/', name)
    if match:
        slot = int(match.group(1))
        print(f"  Channel is on slot {slot}")
        
        # Now find RF ports on this slot
        # Walk IF-MIB::ifDescr looking for RPS0x-{slot-1} or similar pattern
        # Actually on E6000, the naming is different
        
    return None


def discover_utsc_ports():
    """Discover available UTSC ports."""
    lines = snmp_walk('1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.3')
    ports = []
    
    for line in lines:
        # Parse: docsPnmCmtsUtscCfgTriggerMode.1074339840.1 = INTEGER: freeRunning(2)
        match = re.search(r'\.(\d+)\.(\d+)\s*=', line)
        if match:
            ifindex = int(match.group(1))
            logical_idx = int(match.group(2))
            ports.append((ifindex, logical_idx))
    
    return ports


def check_utsc_with_logical_channel(rf_port, logical_ch_ifindex):
    """Try to configure UTSC with a logical channel."""
    # Try to set docsPnmCmtsUtscCfgLogicalChIfIndex
    print(f"  Trying to set logical channel {logical_ch_ifindex} on RF port {rf_port}...")
    
    cmd = ['snmpset', '-v2c', '-c', COMMUNITY, CMTS_IP,
           f'1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{rf_port}.1', 'i', str(logical_ch_ifindex)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    
    if result.returncode == 0:
        print(f"  ✓ Success!")
        return True
    else:
        print(f"  ✗ Failed: {result.stderr.strip()}")
        return False


def main():
    print("=" * 60)
    print("UTSC Logical Port Discovery Test")
    print("=" * 60)
    print(f"CMTS: {CMTS_IP}")
    print(f"Modem MAC: {MODEM_MAC}")
    print()
    
    # Step 1: Find modem index
    print("Step 1: Find modem index...")
    cm_index = get_modem_index(MODEM_MAC)
    if not cm_index:
        print("  ✗ Modem not found!")
        sys.exit(1)
    print(f"  ✓ Modem index: {cm_index}")
    
    # Step 2: Get modem's upstream channels
    print("\nStep 2: Get modem's upstream channels...")
    us_channels = get_modem_upstream_channels(cm_index)
    print(f"  Found {len(us_channels)} upstream channels:")
    
    for ch in us_channels[:4]:  # Show first 4
        info = get_interface_info(ch)
        print(f"    - ifIndex {ch}: {info['name']}")
    
    # Step 3: Discover available UTSC RF ports
    print("\nStep 3: Available UTSC RF ports...")
    utsc_ports = discover_utsc_ports()
    print(f"  Found {len(utsc_ports)} UTSC ports")
    
    for ifindex, logical_idx in utsc_ports[:5]:
        info = get_interface_info(ifindex)
        print(f"    - ifIndex {ifindex}: {info['descr']}")
    
    # Step 4: Try to set logical channel on UTSC
    print("\nStep 4: Test logical channel assignment...")
    
    if us_channels and utsc_ports:
        # Get the first modem channel
        modem_ch = us_channels[0]
        modem_info = get_interface_info(modem_ch)
        print(f"  Using modem channel: {modem_ch} ({modem_info['name']})")
        
        # Try each UTSC port
        for rf_port, _ in utsc_ports[:2]:
            rf_info = get_interface_info(rf_port)
            print(f"\n  Testing RF port {rf_port} ({rf_info['descr']})...")
            
            if check_utsc_with_logical_channel(rf_port, modem_ch):
                print(f"  ✓ Successfully assigned logical channel!")
                
                # Reset back to 0
                cmd = ['snmpset', '-v2c', '-c', COMMUNITY, CMTS_IP,
                       f'1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{rf_port}.1', 'i', '0']
                subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                break
    
    # Step 5: Alternative - Use docsPnmBulkDestCmMacAddr approach?
    print("\n" + "=" * 60)
    print("Summary:")
    print("  - Modem discovery via MAC is fast (single SNMP walk)")
    print("  - Modem's upstream channels are easily retrieved")
    print("  - Logical channel to RF port mapping may be E6000-specific")
    print("  - Consider using RF port directly from modem's MD-CM-SG")


if __name__ == "__main__":
    main()
