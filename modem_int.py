#!/usr/bin/env python3
"""
Lookup a registered cable modem on a CMTS by MAC and print:
- cmIndex (docsIfCmtsCmPtr)
- DOCSIS 3.0 ATDMA upstream channels (docsIf3CmtsCmUsStatusTable)
- DOCSIS 3.1 OFDMA upstream channels (docsIf31CmtsCmUsOfdmaProfileTable)
- ifDescr for each upstream ifIndex

Requires Net-SNMP CLI tools: snmpget, snmpwalk
"""

import argparse
import re
import subprocess
import sys

# DOCS-IF-MIB
DOCSIF_CMTS_CMPTR_OID = "1.3.6.1.2.1.10.127.1.3.7.1.2"  # docsIfCmtsCmPtr (indexed by MAC)

# DOCS-IF3-MIB - DOCSIS 3.0 ATDMA upstream status
DOCSIF3_CM_US_STATUS_OID = "1.3.6.1.4.1.4491.2.1.20.1.4.1"  # docsIf3CmtsCmUsStatusTable

# DOCS-IF31-MIB - DOCSIS 3.1 OFDMA upstream 
DOCSIF31_CM_US_OFDMA_OID = "1.3.6.1.4.1.4491.2.1.28.1.5.1.1"  # docsIf31CmtsCmUsOfdmaProfileTotalCodewords

# IF-MIB
IFDESCR_OID = "1.3.6.1.2.1.2.2.1.2"  # ifDescr.<ifIndex>

MAC_RE = re.compile(r"^([0-9a-fA-F]{2}([:\-]?)){5}[0-9a-fA-F]{2}$")


def mac_to_decimal_oid_suffix(mac: str) -> str:
    mac = mac.strip()
    if not MAC_RE.match(mac):
        raise ValueError(f"Invalid MAC address: {mac}")

    mac = mac.replace("-", ":").lower()
    parts = mac.split(":")
    if len(parts) != 6:
        mac_hex = re.sub(r"[^0-9a-fA-F]", "", mac)
        if len(mac_hex) != 12:
            raise ValueError(f"Invalid MAC address: {mac}")
        parts = [mac_hex[i:i+2] for i in range(0, 12, 2)]

    return ".".join(str(int(p, 16)) for p in parts)


def run_snmpget(cmts: str, community: str, oid: str, version: str, timeout: int, retries: int) -> str:
    cmd = [
        "snmpget",
        f"-v{version}",
        "-c", community,
        "-t", str(timeout),
        "-r", str(retries),
        "-Ovq",
        cmts,
        oid,
    ]
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
    except FileNotFoundError:
        raise RuntimeError("snmpget not found. Install Net-SNMP tools.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.output.strip() or f"snmpget failed for OID {oid}")


def run_snmpwalk(cmts: str, community: str, oid: str, version: str, timeout: int, retries: int) -> str:
    cmd = [
        "snmpwalk",
        f"-v{version}",
        "-c", community,
        "-t", str(timeout),
        "-r", str(retries),
        cmts,
        oid,
    ]
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
    except FileNotFoundError:
        raise RuntimeError("snmpwalk not found. Install Net-SNMP tools.")
    except subprocess.CalledProcessError as e:
        return ""  # Empty result is OK for optional tables


def snmpget_cm_index(cmts: str, community: str, mac: str, version: str, timeout: int, retries: int) -> int:
    mac_suffix = mac_to_decimal_oid_suffix(mac)
    full_oid = f"{DOCSIF_CMTS_CMPTR_OID}.{mac_suffix}"
    out = run_snmpget(cmts, community, full_oid, version, timeout, retries)
    try:
        return int(out)
    except ValueError:
        raise RuntimeError(f"Unexpected cmIndex output: {out}")


def get_atdma_channels(cmts: str, community: str, cm_index: int, version: str, timeout: int, retries: int) -> list:
    """Get DOCSIS 3.0 ATDMA upstream channels for this CM."""
    output = run_snmpwalk(cmts, community, DOCSIF3_CM_US_STATUS_OID, version, timeout, retries)
    
    channels = set()
    for line in output.split('\n'):
        if f'.{cm_index}.' in line:
            # Extract ifIndex from OID: ...docsIf3CmtsCmUsStatusXxx.<cmIndex>.<usIfIndex>
            try:
                parts = line.split('=')[0].strip().split('.')
                for i, p in enumerate(parts):
                    if p == str(cm_index) and i + 1 < len(parts):
                        ifindex = int(parts[i + 1])
                        if ifindex > 0:
                            channels.add(ifindex)
                        break
            except:
                pass
    return sorted(channels)


def get_ofdma_channels(cmts: str, community: str, cm_index: int, version: str, timeout: int, retries: int) -> list:
    """Get DOCSIS 3.1 OFDMA upstream channels for this CM."""
    output = run_snmpwalk(cmts, community, DOCSIF31_CM_US_OFDMA_OID, version, timeout, retries)
    
    channels = set()
    for line in output.split('\n'):
        if f'.{cm_index}.' in line:
            # Extract ifIndex from OID: ...docsIf31CmtsCmUsOfdmaXxx.<cmIndex>.<ofdmaIfIndex>.<profileId>
            try:
                parts = line.split('=')[0].strip().split('.')
                for i, p in enumerate(parts):
                    if p == str(cm_index) and i + 1 < len(parts):
                        ifindex = int(parts[i + 1])
                        if ifindex > 800000000:  # OFDMA ifindexes are typically > 843M
                            channels.add(ifindex)
                        break
            except:
                pass
    return sorted(channels)


def get_ifdescr(cmts: str, community: str, ifindex: int, version: str, timeout: int, retries: int) -> str:
    try:
        return run_snmpget(cmts, community, f"{IFDESCR_OID}.{ifindex}", version, timeout, retries)
    except:
        return "N/A"


def get_us_conn_ports(cmts: str, community: str, version: str, timeout: int, retries: int) -> dict:
    """Get all us-conn physical ports and their ifIndex."""
    output = run_snmpwalk(cmts, community, IFDESCR_OID, version, timeout, retries)
    
    ports = {}  # blade_id -> [(ifindex, descr), ...]
    for line in output.split('\n'):
        if 'us-conn' in line.lower():
            try:
                # Parse: IF-MIB::ifDescr.1074339840 = STRING: MNDGT0002RPS01-0 us-conn 0
                parts = line.split('=', 1)
                oid_part = parts[0].strip()
                ifindex = int(oid_part.split('.')[-1])
                descr = parts[1].split(':', 1)[-1].strip().strip('"')
                
                # Extract blade ID (e.g., "RPS01-1" from "MNDGT0002RPS01-1 us-conn 0")
                match = re.search(r'(RPS\d+-\d+)', descr)
                if match:
                    blade_id = match.group(1)
                    if blade_id not in ports:
                        ports[blade_id] = []
                    ports[blade_id].append((ifindex, descr))
            except:
                pass
    return ports


def find_physical_port(channel_descr: str, us_conn_ports: dict) -> tuple:
    """Find the physical us-conn port for a logical channel.
    
    channel_descr: e.g., "cable-upstream 1/ofd/4.0" or "cable-upstream 1/scq/20.0"
    Returns: (ifindex, descr) or None
    """
    # Extract slot number from channel description (e.g., "1" from "cable-upstream 1/ofd/4.0")
    match = re.search(r'cable-upstream\s+(\d+)/', channel_descr)
    if not match:
        match = re.search(r'cable-us-ofdma\s+(\d+)/', channel_descr)
    
    if match:
        slot = int(match.group(1))
        # Find matching blade (slot 1 = RPS01-1, slot 0 = RPS01-0, etc.)
        for blade_id, ports in us_conn_ports.items():
            # Extract blade number from blade_id (e.g., "1" from "RPS01-1")
            blade_match = re.search(r'RPS\d+-(\d+)', blade_id)
            if blade_match:
                blade_slot = int(blade_match.group(1))
                if blade_slot == slot and ports:
                    # Return first us-conn on this blade (typically us-conn 0)
                    return ports[0]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmts", required=True, help="CMTS management IP/hostname")
    ap.add_argument("--community", required=True, help="SNMP community string")
    ap.add_argument("--mac", required=True, help="Cable modem MAC (e.g. 00:11:22:AA:BB:CC)")
    ap.add_argument("--version", default="2c", choices=["1", "2c"], help="SNMP version (default: 2c)")
    ap.add_argument("--timeout", type=int, default=5, help="SNMP timeout seconds (default: 5)")
    ap.add_argument("--retries", type=int, default=1, help="SNMP retries (default: 1)")
    args = ap.parse_args()

    try:
        cm_index = snmpget_cm_index(args.cmts, args.community, args.mac, args.version, args.timeout, args.retries)
        print(f"cmIndex: {cm_index}")
        
        # Get all us-conn physical ports
        us_conn_ports = get_us_conn_ports(args.cmts, args.community, args.version, args.timeout, args.retries)
        
        physical_ports_found = set()
        
        # Get ATDMA channels (DOCSIS 3.0)
        atdma = get_atdma_channels(args.cmts, args.community, cm_index, args.version, args.timeout, args.retries)
        if atdma:
            print(f"\nATDMA Upstream Channels ({len(atdma)}):")
            for ifidx in atdma:
                descr = get_ifdescr(args.cmts, args.community, ifidx, args.version, args.timeout, args.retries)
                print(f"  ifIndex: {ifidx}  -  {descr}")
                
                # Find physical port
                phys = find_physical_port(descr, us_conn_ports)
                if phys:
                    physical_ports_found.add(phys)
        
        # Get OFDMA channels (DOCSIS 3.1)
        ofdma = get_ofdma_channels(args.cmts, args.community, cm_index, args.version, args.timeout, args.retries)
        if ofdma:
            print(f"\nOFDMA Upstream Channels ({len(ofdma)}):")
            for ifidx in ofdma:
                descr = get_ifdescr(args.cmts, args.community, ifidx, args.version, args.timeout, args.retries)
                print(f"  ifIndex: {ifidx}  -  {descr}")
                
                # Find physical port
                phys = find_physical_port(descr, us_conn_ports)
                if phys:
                    physical_ports_found.add(phys)
        
        # Print physical ports
        if physical_ports_found:
            print(f"\nPhysical RF Ports (us-conn) for UTSC:")
            for ifidx, descr in sorted(physical_ports_found):
                print(f"  ifIndex: {ifidx}  -  {descr}")
        
        if not atdma and not ofdma:
            print("\nNo upstream channels found for this CM")
            
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
