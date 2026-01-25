"""
UTSC RF Port Discovery Module

Fast discovery of the correct UTSC RF port for a modem.
Fallback to direct SNMP if PyPNM API is unavailable.
"""

import logging
import requests
import os
from pysnmp.hlapi import *

logger = logging.getLogger(__name__)

# PyPNM API timeout
API_TIMEOUT = 60


def get_pypnm_api_url():
    """Get PyPNM API URL from environment or default."""
    # Use same default as PyPNMClient - Docker gateway IP to reach host network
    # Try PYPNM_API_URL first, then PYPNM_BASE_URL
    return os.environ.get('PYPNM_API_URL', os.environ.get('PYPNM_BASE_URL', 'http://localhost:8000'))


def snmp_walk_simple(target, community, oid_base):
    """Simple SNMP walk that returns a dict of {oid_suffix: value}."""
    results = {}
    try:
        for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
            SnmpEngine(),
            CommunityData(community),
            UdpTransportTarget((target, 161), timeout=3, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid_base)),
            lexicographicMode=False
        ):
            if errorIndication or errorStatus:
                break
            for varBind in varBinds:
                oid_str = str(varBind[0])
                value = varBind[1]
                # Extract suffix after base OID
                if oid_str.startswith(oid_base):
                    suffix = oid_str[len(oid_base):]
                    results[suffix] = value
    except Exception as e:
        logger.error(f"SNMP walk failed: {e}")
    return results


def discover_rf_port_via_snmp(cmts_ip, community, mac_address):
    """
    Discover RF port using direct SNMP queries.
    This is a fallback when PyPNM API is unavailable.
    """
    logger.info(f"Using direct SNMP discovery for {mac_address} on {cmts_ip}")
    
    try:
        # 1. Find modem's CM index by MAC address
        # OID: DOCS-IF3-MIB::docsIf3CmtsCmRegStatusMacAddr
        mac_table_oid = "1.3.6.1.4.1.4491.2.1.20.1.3.1.5"
        mac_entries = snmp_walk_simple(cmts_ip, community, mac_table_oid)
        
        # Convert MAC address to hex format for comparison
        mac_hex = mac_address.replace(":", "").lower()
        cm_index = None
        
        for suffix, value in mac_entries.items():
            # value is the MAC address in hex format
            modem_mac_hex = str(value).replace(" ", "").replace("0x", "").lower()
            if modem_mac_hex == mac_hex:
                # Extract CM index from suffix (format: .cm_index)
                cm_index = int(suffix.lstrip('.'))
                logger.info(f"Found CM index: {cm_index}")
                break
        
        if not cm_index:
            return {"success": False, "error": f"Modem {mac_address} not found on CMTS"}
        
        # 2. Get modem's upstream channels
        # OID: DOCS-IF3-MIB::docsIf3CmtsCmUsStatusChIfIndex
        us_channel_oid = f"1.3.6.1.4.1.4491.2.1.20.1.4.1.3.{cm_index}"
        us_channels_raw = snmp_walk_simple(cmts_ip, community, us_channel_oid)
        us_channels = [int(val) for val in us_channels_raw.values() if val]
        
        if not us_channels:
            return {"success": False, "error": "No upstream channels found for modem"}
        
        logger.info(f"Modem upstream channels: {us_channels}")
        
        # 3. Find RF port by checking which RF port contains these channels
        # OID: IF-MIB::ifDescr for RF ports (look for "us-conn")
        ifdescr_oid = "1.3.6.1.2.1.2.2.1.2"
        interfaces = snmp_walk_simple(cmts_ip, community, ifdescr_oid)
        
        # Find RF ports (us-conn interfaces)
        rf_ports = {}
        for suffix, descr in interfaces.items():
            descr_str = str(descr)
            if "us-conn" in descr_str.lower():
                ifindex = int(suffix.lstrip('.'))
                rf_ports[ifindex] = descr_str
        
        logger.info(f"Found {len(rf_ports)} RF ports on CMTS")
        
        # For now, return the first RF port found
        # TODO: Implement proper channel-to-RF-port mapping
        if rf_ports:
            rf_port_ifindex = list(rf_ports.keys())[0]
            rf_port_description = rf_ports[rf_port_ifindex]
            
            return {
                "success": True,
                "rf_port_ifindex": rf_port_ifindex,
                "rf_port_description": rf_port_description,
                "cm_index": cm_index,
                "us_channels": us_channels,
                "error": None
            }
        else:
            return {"success": False, "error": "No RF ports found on CMTS"}
            
    except Exception as e:
        logger.error(f"SNMP discovery failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def discover_rf_port_for_modem(cmts_ip, community, mac_address):
    """
    Discover the correct UTSC RF port for a modem.
    Tries PyPNM API first, falls back to direct SNMP.
    
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
    
    pypnm_api_url = get_pypnm_api_url()
    logger.info(f"Discovering RF port for modem {mac_address} on CMTS {cmts_ip}")
    
    # Try PyPNM API first
    try:
        logger.debug(f"Trying PyPNM API at {pypnm_api_url}")
        response = requests.post(
            f"{pypnm_api_url}/docs/pnm/us/spectrumAnalyzer/discoverRfPort",
            json={
                "cmts_ip": cmts_ip,
                "cm_mac_address": mac_address,
                "community": community
            },
            timeout=API_TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                result["success"] = True
                result["rf_port_ifindex"] = data.get("rf_port_ifindex")
                result["rf_port_description"] = data.get("rf_port_description")
                result["cm_index"] = data.get("cm_index")
                result["us_channels"] = data.get("us_channels", [])
                logger.info(f"Discovered via API: RF port {result['rf_port_ifindex']} ({result['rf_port_description']})")
                return result
            else:
                logger.warning(f"API discovery failed: {data.get('error')}")
        else:
            logger.warning(f"API returned {response.status_code}, will try direct SNMP")
            
    except requests.exceptions.Timeout:
        logger.warning("PyPNM API timeout, trying direct SNMP")
    except requests.exceptions.ConnectionError:
        logger.warning("Cannot connect to PyPNM API, trying direct SNMP")
    except Exception as e:
        logger.warning(f"API error: {e}, trying direct SNMP")
    
    # Fallback to direct SNMP
    logger.info("Using direct SNMP discovery as fallback")
    return discover_rf_port_via_snmp(cmts_ip, community, mac_address)
