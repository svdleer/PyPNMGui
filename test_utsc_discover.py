#!/usr/bin/env python3
"""
Test script to discover UTSC RF port from modem MAC address.
Uses the modem's upstream logical channel to find the correct RF port.
"""

import subprocess
import sys

CMTS_IP = "172.16.6.212"
COMMUNITY = "Z1gg0Sp3c1@l"


def snmp_get(oid):
    """Get SNMP value."""
    cmd = ['snmpget', '-v2c', '-c', COMMUNITY, CMTS_IP, oid]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout.strip() if result.returncode == 0 else None


def snmp_walk(oid):
    """Walk SNMP OID."""
    cmd = ['snmpwalk', '-v2c', '-c', COMMUNITY, CMTS_IP, oid]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip().split('\n') if result.returncode == 0 else []


def snmp_set(oid, value_type, value):
    """Set SNMP value."""
    cmd = ['snmpset', '-v2c', '-c', COMMUNITY, CMTS_IP, oid, value_type, str(value)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.returncode == 0, result.stderr


def mac_to_ints(mac):
    """Convert MAC to SNMP index format."""
    mac_clean = mac.replace(':', '').replace('-', '').lower()
    return '.'.join(str(int(mac_clean[i:i+2], 16)) for i in range(0, 12, 2))


def find_cm_index(mac):
    """Find CM index from MAC address."""
    mac_upper = mac.upper().replace('-', ':')
    lines = snmp_walk('1.3.6.1.4.1.4491.2.1.20.1.3.1.2')  # docsIf3CmtsCmRegStatusMacAddr
    
    for line in lines:
        if mac_upper in line.upper():
            # Extract index from OID
            parts = line.split('.')
            idx = parts[-1].split()[0]
            return int(idx)
    return None


def get_modem_us_channels(cm_idx):
    """Get modem's upstream channel ifIndexes."""
    channels = []
    lines = snmp_walk(f'1.3.6.1.4.1.4491.2.1.20.1.4.1')  # docsIf3CmtsCmUsStatusTable
    
    for line in lines:
        if f'.{cm_idx}.' in line and 'RxPower' in line:
            # Parse: ...RxPower.3.843071811 = ...
            parts = line.split('.')
            for i, p in enumerate(parts):
                if p.startswith(str(cm_idx)) and i+1 < len(parts):
                    ch_ifidx = parts[i+1].split()[0]
                    if ch_ifidx.isdigit():
                        channels.append(int(ch_ifidx))
                    break
    return channels


def get_rf_ports():
    """Get all UTSC RF ports."""
    rf_ports = []
    lines = snmp_walk('1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2')  # docsPnmCmtsUtscCfgLogicalChIfIndex
    
    for line in lines:
        # Parse: ...LogicalChIfIndex.1074339840.1 = INTEGER: 0
        if 'LogicalChIfIndex' in line and '=' in line:
            # Get the OID part before '='
            oid_part = line.split('=')[0]
            # Find the large number which is the RF port ifindex
            parts = oid_part.split('.')
            for p in parts:
                try:
                    ifidx = int(p)
                    if ifidx > 1000000000:  # RF port ifindex is large
                        rf_ports.append(ifidx)
                        break
                except:
                    pass
    return list(set(rf_ports))


def get_rf_port_info(rf_port):
    """Get RF port description."""
    result = snmp_get(f'ifDescr.{rf_port}')
    if result:
        # Parse: IF-MIB::ifDescr.1074339840 = STRING: MNDGT0002RPS01-0 us-conn 0
        if 'STRING:' in result:
            return result.split('STRING:')[1].strip()
    return f"Unknown ({rf_port})"


def test_logical_channel_on_rf_port(rf_port, logical_ch):
    """Test if logical channel can be set on RF port."""
    oid = f'1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{rf_port}.1'
    success, err = snmp_set(oid, 'i', logical_ch)
    return success


def find_rf_port_for_channel(logical_ch, rf_ports):
    """Find which RF port accepts this logical channel."""
    for rf_port in rf_ports:
        if test_logical_channel_on_rf_port(rf_port, logical_ch):
            return rf_port
    return None


def main():
    if len(sys.argv) < 2:
        mac = "e4:57:40:f7:13:20"  # Default test modem
    else:
        mac = sys.argv[1]
    
    print(f"=" * 60)
    print(f"UTSC RF Port Discovery from Modem MAC")
    print(f"=" * 60)
    print(f"CMTS: {CMTS_IP}")
    print(f"MAC:  {mac}")
    
    # Step 1: Find CM index
    print(f"\n[1] Finding CM index...")
    cm_idx = find_cm_index(mac)
    if not cm_idx:
        print(f"    ERROR: Modem not found!")
        return
    print(f"    CM Index: {cm_idx}")
    
    # Step 2: Get modem's upstream channels
    print(f"\n[2] Getting upstream channels...")
    us_channels = get_modem_us_channels(cm_idx)
    if not us_channels:
        print(f"    ERROR: No upstream channels found!")
        return
    print(f"    Channels: {us_channels}")
    
    # Get first channel info
    first_ch = us_channels[0]
    ch_name = snmp_get(f'ifDescr.{first_ch}')
    if ch_name and 'STRING:' in ch_name:
        ch_name = ch_name.split('STRING:')[1].strip()
    print(f"    First channel: {first_ch} ({ch_name})")
    
    # Get frequency
    freq = snmp_get(f'1.3.6.1.2.1.10.127.1.1.2.1.2.{first_ch}')
    if freq and 'INTEGER:' in freq:
        freq_hz = int(freq.split('INTEGER:')[1].split()[0])
        print(f"    Frequency: {freq_hz/1000000:.1f} MHz")
    
    # Step 3: Get available RF ports
    print(f"\n[3] Getting UTSC RF ports...")
    rf_ports = get_rf_ports()
    print(f"    Found {len(rf_ports)} RF ports")
    for rf_port in rf_ports[:5]:  # Show first 5
        info = get_rf_port_info(rf_port)
        print(f"      {rf_port}: {info}")
    if len(rf_ports) > 5:
        print(f"      ... and {len(rf_ports) - 5} more")
    
    # Step 4: Find which RF port accepts the logical channel
    print(f"\n[4] Testing RF ports for logical channel {first_ch}...")
    matching_rf = find_rf_port_for_channel(first_ch, rf_ports)
    
    if matching_rf:
        info = get_rf_port_info(matching_rf)
        print(f"    FOUND! RF Port: {matching_rf}")
        print(f"    Description: {info}")
        
        # Reset logical channel to 0
        snmp_set(f'1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{matching_rf}.1', 'i', 0)
        
        print(f"\n[RESULT] To run UTSC for modem {mac}:")
        print(f"         Use RF Port ifIndex: {matching_rf}")
    else:
        print(f"    No matching RF port found!")
        print(f"\n    Trying to find RF port by slot/connector pattern...")
        
        # Parse slot from channel name (e.g., "cable-upstream 1/scq/160.0" -> slot 1)
        if ch_name and '/' in ch_name:
            parts = ch_name.split()
            for part in parts:
                if '/' in part:
                    slot = part.split('/')[0]
                    print(f"    Channel slot: {slot}")
                    
                    # Find RF ports matching this slot
                    for rf_port in rf_ports:
                        rf_info = get_rf_port_info(rf_port)
                        # RPS01-1 = slot 1
                        if f"RPS01-{slot}" in rf_info:
                            print(f"    Matching RF port: {rf_port} ({rf_info})")
                    break


if __name__ == '__main__':
    main()
