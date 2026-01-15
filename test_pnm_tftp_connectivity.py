#!/usr/bin/env python3
"""
Test PNM TFTP Connectivity
Tests if a cable modem can upload PNM files to hop-access1-sh.ext.oss.local via TFTP.
"""

import asyncio
import sys
import time
import requests

# Test modem
TEST_MODEM_MAC = "20:b8:2b:53:c5:e8"
TEST_MODEM_IP = "10.214.157.17"

# TFTP server (public VPS)
TFTP_SERVER_HOST = "vps.serial.nl"
TFTP_SERVER_IP = None  # Will be resolved
TFTP_PATH = "/tmp/pnm-test"

# PyPNM GUI API (use localhost via SSH tunnel)
API_BASE = "http://localhost:5050/api"

# DOCSIS PNM OIDs for triggering spectrum analysis
DOCSIS_PNM_BULK_DEST_IP_TYPE = "1.3.6.1.4.1.4491.2.1.27.1.2.4.1.2.1"  # IPv4
DOCSIS_PNM_BULK_DEST_IP = "1.3.6.1.4.1.4491.2.1.27.1.2.4.1.3.1"
DOCSIS_PNM_BULK_DEST_PATH = "1.3.6.1.4.1.4491.2.1.27.1.2.4.1.4.1"
DOCSIS_PNM_BULK_UPLOAD_CTRL = "1.3.6.1.4.1.4491.2.1.27.1.2.4.1.6.1"

# PNM Control OIDs
DOCSIS_PNM_CM_CTL_TEST = "1.3.6.1.4.1.4491.2.1.27.1.2.6.1.2.1"
DOCSIS_PNM_CM_CTL_STATUS = "1.3.6.1.4.1.4491.2.1.27.1.2.6.1.5.1"


def snmp_set_via_agent(modem_ip, oid, value, value_type='i'):
    """Send SNMP SET via agent WebSocket."""
    # This would use your WebSocket API
    # For now, using HTTP POST to backend which forwards to agent
    
    response = requests.post(
        f"{API_BASE}/snmp/set",
        json={
            'modem_ip': modem_ip,
            'oid': oid,
            'value': value,
            'type': value_type,
            'community': 'm0d3m1nf0'  # modem community
        },
        timeout=30
    )
    return response.json()


def snmp_get_via_agent(modem_ip, oid):
    """Send SNMP GET via agent WebSocket."""
    response = requests.post(
        f"{API_BASE}/snmp/get",
        json={
            'modem_ip': modem_ip,
            'oid': oid,
            'community': 'm0d3m1nf0'
        },
        timeout=30
    )
    return response.json()


def test_pnm_tftp_connectivity():
    """Test if modem can upload PNM file to TFTP server."""
    
    # Resolve TFTP server IP
    import socket
    global TFTP_SERVER_IP
    try:
        TFTP_SERVER_IP = socket.gethostbyname(TFTP_SERVER_HOST)
        print(f"Resolved {TFTP_SERVER_HOST} to {TFTP_SERVER_IP}")
    except Exception as e:
        print(f"Failed to resolve {TFTP_SERVER_HOST}: {e}")
        return False
    
    print("=" * 70)
    print("PNM TFTP Connectivity Test")
    print("=" * 70)
    print(f"Modem: {TEST_MODEM_MAC} ({TEST_MODEM_IP})")
    print(f"TFTP Server: {TFTP_SERVER_HOST} ({TFTP_SERVER_IP})")
    print(f"TFTP Path: {TFTP_PATH}")
    print()
    
    try:
        # Step 1: Configure TFTP destination
        print("Step 1: Configuring TFTP destination...")
        
        # Set IP type to IPv4
        result = snmp_set_via_agent(TEST_MODEM_IP, DOCSIS_PNM_BULK_DEST_IP_TYPE, '1', 'i')
        print(f"  IP Type: {result.get('success', False)}")
        
        # Set TFTP server IP (convert to hex octets)
        ip_octets = '.'.join([f"{int(octet):02x}" for octet in TFTP_SERVER_IP.split('.')])
        result = snmp_set_via_agent(TEST_MODEM_IP, DOCSIS_PNM_BULK_DEST_IP, ip_octets, 'x')
        print(f"  TFTP IP ({TFTP_SERVER_IP} -> {ip_octets}): {result.get('success', False)}")
        
        # Set destination path
        result = snmp_set_via_agent(TEST_MODEM_IP, DOCSIS_PNM_BULK_DEST_PATH, TFTP_PATH, 's')
        print(f"  TFTP Path: {result.get('success', False)}")
        
        # Enable upload
        result = snmp_set_via_agent(TEST_MODEM_IP, DOCSIS_PNM_BULK_UPLOAD_CTRL, '1', 'i')
        print(f"  Upload Control: {result.get('success', False)}")
        print()
        
        # Step 2: Trigger a simple PNM test (spectrum analyzer)
        print("Step 2: Triggering spectrum analysis test...")
        result = snmp_set_via_agent(TEST_MODEM_IP, DOCSIS_PNM_CM_CTL_TEST, '4', 'i')  # 4 = spectrum
        print(f"  Trigger: {result.get('success', False)}")
        print()
        
        # Step 3: Monitor test status
        print("Step 3: Monitoring test status...")
        for i in range(30):  # Wait up to 30 seconds
            time.sleep(1)
            result = snmp_get_via_agent(TEST_MODEM_IP, DOCSIS_PNM_CM_CTL_STATUS)
            status_value = result.get('output', 'unknown')
            print(f"  Status ({i+1}s): {status_value}")
            
            if 'success' in str(status_value).lower() or '4' in str(status_value):
                print("\n✅ Test completed successfully!")
                print(f"\nNow check if file appeared on {TFTP_SERVER_HOST}:")
                print(f"  ssh {TFTP_SERVER_HOST} 'ls -la {TFTP_PATH}/'")
                return True
            elif 'failed' in str(status_value).lower() or '3' in str(status_value):
                print("\n❌ Test failed - modem could not upload file")
                print(f"This means modem CANNOT reach {TFTP_SERVER_HOST} for TFTP")
                return False
        
        print("\n⏱️ Test timed out waiting for completion")
        return False
        
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n⚠️  PREREQUISITES:")
    print("1. PyPNM GUI backend must be running with agent connected")
    print("2. vps.serial.nl must have TFTP service running")
    print("3. vps.serial.nl must allow TFTP uploads to /tmp/pnm-test")
    print("4. Backend API endpoints /api/snmp/set and /api/snmp/get must be available")
    print()
    
    print("Testing connectivity to vps.serial.nl...")
    import socket
    try:
        ip = socket.gethostbyname('vps.serial.nl')
        print(f"✅ Resolved vps.serial.nl to {ip}")
    except Exception as e:
        print(f"❌ Cannot resolve vps.serial.nl: {e}")
        sys.exit(1)
    
    print()
    input("Press Enter to continue or Ctrl+C to abort...")
    
    success = test_pnm_tftp_connectivity()
    sys.exit(0 if success else 1)
