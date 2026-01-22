"""
UTSC RF Port Discovery Module

Fast discovery of the correct UTSC RF port for a modem using SNMP.
Uses the modem's upstream logical channel to find the correct RF port.
"""

import subprocess
import logging

logger = logging.getLogger(__name__)

# SNMP timeout for fast queries
SNMP_TIMEOUT = 5


def snmp_get(cmts_ip, community, oid):
    """Get SNMP value with timeout."""
    cmd = ['snmpget', '-v2c', '-c', community, '-t', str(SNMP_TIMEOUT), cmts_ip, oid]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SNMP_TIMEOUT + 2)
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception as e:
        logger.debug(f"SNMP get error: {e}")
        return None


def snmp_walk(cmts_ip, community, oid):
    """Walk SNMP OID with timeout."""
    cmd = ['snmpwalk', '-v2c', '-c', community, '-t', str(SNMP_TIMEOUT), cmts_ip, oid]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip().split('\n') if result.returncode == 0 else []
    except Exception as e:
        logger.debug(f"SNMP walk error: {e}")
        return []


def snmp_set(cmts_ip, community, oid, value_type, value):
    """Set SNMP value - returns True if successful."""
    cmd = ['snmpset', '-v2c', '-c', community, '-t', str(SNMP_TIMEOUT), cmts_ip, oid, value_type, str(value)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SNMP_TIMEOUT + 2)
        return result.returncode == 0
    except Exception as e:
        logger.debug(f"SNMP set error: {e}")
        return False


def mac_to_snmp_index(mac):
    """Convert MAC address to SNMP OID index format (dot-separated decimals)."""
    mac_clean = mac.replace(':', '').replace('-', '').lower()
    return '.'.join(str(int(mac_clean[i:i+2], 16)) for i in range(0, 12, 2))


def find_cm_index(cmts_ip, community, mac):
    """Find CM index from MAC address by walking docsIf3CmtsCmRegStatusMacAddr."""
    mac_upper = mac.upper().replace('-', ':')
    lines = snmp_walk(cmts_ip, community, '1.3.6.1.4.1.4491.2.1.20.1.3.1.2')
    
    for line in lines:
        if mac_upper in line.upper():
            # Extract index from OID: ...MacAddr.3 = STRING: e4:57:40:f7:13:20
            parts = line.split('.')
            idx = parts[-1].split()[0]
            try:
                return int(idx)
            except:
                pass
    return None


def get_modem_us_channels(cmts_ip, community, cm_idx):
    """Get modem's upstream channel ifIndexes from docsIf3CmtsCmUsStatusTable."""
    channels = []
    # Walk UsStatus table and find entries for this CM index
    lines = snmp_walk(cmts_ip, community, '1.3.6.1.4.1.4491.2.1.20.1.4.1.2')  # RxPower column
    
    for line in lines:
        # Parse: ...RxPower.3.843071811 = INTEGER: ...
        if f'.{cm_idx}.' in line:
            parts = line.split('.')
            for i, p in enumerate(parts):
                if p == str(cm_idx) and i+1 < len(parts):
                    ch_part = parts[i+1].split()[0]
                    if ch_part.isdigit():
                        channels.append(int(ch_part))
                    break
    return list(set(channels))


def get_rf_ports(cmts_ip, community):
    """Get all UTSC RF ports from docsPnmCmtsUtscCfgTable."""
    rf_ports = []
    lines = snmp_walk(cmts_ip, community, '1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2')
    
    for line in lines:
        # Parse: ...LogicalChIfIndex.1074339840.1 = INTEGER: 0
        if 'LogicalChIfIndex' in line and '=' in line:
            oid_part = line.split('=')[0]
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


def get_rf_port_info(cmts_ip, community, rf_port):
    """Get RF port description (e.g., 'RPS01-0 us-conn 0')."""
    result = snmp_get(cmts_ip, community, f'ifDescr.{rf_port}')
    if result and 'STRING:' in result:
        return result.split('STRING:')[1].strip()
    return f"RF Port {rf_port}"


def test_logical_channel_on_rf_port(cmts_ip, community, rf_port, logical_ch):
    """Test if logical channel can be set on RF port (validates channel belongs to port)."""
    oid = f'1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{rf_port}.1'
    success = snmp_set(cmts_ip, community, oid, 'i', logical_ch)
    if success:
        # Reset to 0 after successful test
        snmp_set(cmts_ip, community, oid, 'i', 0)
    return success


def discover_rf_port_for_modem(cmts_ip, community, mac_address):
    """
    Discover the correct UTSC RF port for a modem.
    
    Returns dict with:
        - success: bool
        - rf_port_ifindex: int (the correct RF port)
        - rf_port_description: str
        - cm_index: int
        - us_channels: list of upstream channel ifIndexes
        - error: str (if failed)
    """
    result = {
        "success": False,
        "rf_port_ifindex": None,
        "rf_port_description": None,
        "cm_index": None,
        "us_channels": [],
        "error": None
    }
    
    logger.info(f"Discovering RF port for modem {mac_address} on CMTS {cmts_ip}")
    
    # Step 1: Find CM index from MAC
    cm_idx = find_cm_index(cmts_ip, community, mac_address)
    if not cm_idx:
        result["error"] = f"Modem {mac_address} not found on CMTS"
        logger.warning(result["error"])
        return result
    result["cm_index"] = cm_idx
    logger.info(f"Found CM index: {cm_idx}")
    
    # Step 2: Get modem's upstream channels
    us_channels = get_modem_us_channels(cmts_ip, community, cm_idx)
    if not us_channels:
        result["error"] = f"No upstream channels found for modem (CM index {cm_idx})"
        logger.warning(result["error"])
        return result
    result["us_channels"] = us_channels
    logger.info(f"Found {len(us_channels)} upstream channels: {us_channels[:3]}...")
    
    # Step 3: Get all RF ports
    rf_ports = get_rf_ports(cmts_ip, community)
    if not rf_ports:
        result["error"] = "No UTSC RF ports found on CMTS"
        logger.warning(result["error"])
        return result
    logger.info(f"Found {len(rf_ports)} RF ports")
    
    # Step 4: Test which RF port accepts the logical channel
    first_ch = us_channels[0]
    for rf_port in rf_ports:
        if test_logical_channel_on_rf_port(cmts_ip, community, rf_port, first_ch):
            result["success"] = True
            result["rf_port_ifindex"] = rf_port
            result["rf_port_description"] = get_rf_port_info(cmts_ip, community, rf_port)
            logger.info(f"Found matching RF port: {rf_port} ({result['rf_port_description']})")
            return result
    
    # Fallback: couldn't find matching RF port
    result["error"] = f"No RF port found for upstream channel {first_ch}"
    logger.warning(result["error"])
    return result
