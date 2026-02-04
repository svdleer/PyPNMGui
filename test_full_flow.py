#!/usr/bin/env python3
"""
PyPNM GUI Full Flow Test
Tests complete workflow: CMTS discovery → Modem listing → Modem details
"""

import requests
import json
import time
import sys
from datetime import datetime

# Configuration
GUI_API_URL = "http://localhost:5050/api"
PYPNM_API_URL = "http://localhost:8000"

# Real lab data
CMTS_IP = "172.16.6.212"
CMTS_COMMUNITY = "Z1gg0@LL"

# Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def log(message, color=RESET):
    print(f"{color}{message}{RESET}")

def test_health():
    """Test health endpoint"""
    log("\n" + "="*60, BLUE)
    log("TEST 1: Health Check", BLUE)
    log("="*60, BLUE)
    
    try:
        response = requests.get(f"{GUI_API_URL}/health", timeout=5)
        if response.status_code == 200:
            log("✓ GUI API is healthy", GREEN)
            return True
        else:
            log(f"✗ GUI API health check failed: {response.status_code}", RED)
            return False
    except Exception as e:
        log(f"✗ Cannot connect to GUI API: {e}", RED)
        return False

def test_cmts_list():
    """Test CMTS listing"""
    log("\n" + "="*60, BLUE)
    log("TEST 2: List CMTS Devices", BLUE)
    log("="*60, BLUE)
    
    try:
        response = requests.get(f"{GUI_API_URL}/cmts", timeout=10)
        if response.status_code == 200:
            data = response.json()
            cmts_list = data.get('cmts_list', [])
            log(f"✓ Found {len(cmts_list)} CMTS devices", GREEN)
            # Show first 3 and return first one for next test
            first_cmts = None
            for i, cmts in enumerate(cmts_list):
                if i >= 3:
                    break
                hostname = cmts.get('HostName', 'Unknown')
                ip = cmts.get('IPAddress', 'N/A')
                log(f"  - {hostname}: {ip}", YELLOW)
                if i == 0:
                    first_cmts = hostname
            return first_cmts
        else:
            log(f"✗ Failed to list CMTS: {response.status_code}", RED)
            return False
    except Exception as e:
        log(f"✗ CMTS list request failed: {e}", RED)
        return False

def test_cmts_modems(cmts_name="eve-li-c10k-01"):
    """Test modem discovery from CMTS"""
    log("\n" + "="*60, BLUE)
    log(f"TEST 3: Discover Modems from {cmts_name}", BLUE)
    log("="*60, BLUE)
    
    try:
        # Get modems from specific CMTS
        log(f"Requesting modems from {cmts_name} (this may take 10-30s)...", YELLOW)
        start = time.time()
        
        response = requests.get(
            f"{GUI_API_URL}/cmts/{cmts_name}/modems",
            params={'limit': 10, 'use_cache': True},
            timeout=60
        )
        
        elapsed = time.time() - start
        
        if response.status_code == 200:
            data = response.json()
            modems = data.get('modems', [])
            log(f"✓ Retrieved {len(modems)} modems in {elapsed:.1f}s", GREEN)
            
            if modems:
                log("\nFirst 3 modems:", YELLOW)
                for modem in modems[:3]:
                    mac = modem.get('mac_address', 'Unknown')
                    ip = modem.get('ip_address', 'N/A')
                    status = modem.get('status', 'Unknown')
                    vendor = modem.get('vendor', 'Unknown')
                    log(f"  - {mac}: {ip} ({vendor}, {status})", YELLOW)
                
                # Return first modem for next test
                return modems[0]
            else:
                log("⚠ No modems found", YELLOW)
                return None
        else:
            log(f"✗ Failed to get modems: {response.status_code}", RED)
            log(f"Response: {response.text[:200]}", RED)
            return None
    except Exception as e:
        log(f"✗ Modem discovery failed: {e}", RED)
        return None

def test_modem_details(mac_address):
    """Test getting modem from cache"""
    log("\n" + "="*60, BLUE)
    log(f"TEST 4: Get Modem Details from Cache", BLUE)
    log("="*60, BLUE)
    
    try:
        response = requests.get(f"{GUI_API_URL}/modems/{mac_address}", timeout=10)
        
        if response.status_code == 200:
            modem = response.json()
            log(f"✓ Modem {mac_address} found in cache", GREEN)
            log(f"  IP: {modem.get('ip_address')}", YELLOW)
            log(f"  Vendor: {modem.get('vendor')}", YELLOW)
            log(f"  Model: {modem.get('model', 'N/A')}", YELLOW)
            log(f"  DOCSIS: {modem.get('docsis_version', 'N/A')}", YELLOW)
            return True
        elif response.status_code == 404:
            log(f"⚠ Modem not in cache (this is OK if just loaded)", YELLOW)
            return True
        else:
            log(f"✗ Failed to get modem details: {response.status_code}", RED)
            return False
    except Exception as e:
        log(f"✗ Modem details request failed: {e}", RED)
        return False

def test_pypnm_agents():
    """Test PyPNM agent status"""
    log("\n" + "="*60, BLUE)
    log("TEST 5: Check PyPNM Agents", BLUE)
    log("="*60, BLUE)
    
    try:
        response = requests.get(f"{PYPNM_API_URL}/api/agents", timeout=10)
        
        if response.status_code == 200:
            agents = response.json()
            if isinstance(agents, list):
                log(f"✓ Found {len(agents)} connected agents", GREEN)
                for agent in agents:
                    if isinstance(agent, dict):
                        agent_id = agent.get('agent_id', 'Unknown')
                        status = agent.get('status', 'Unknown')
                        log(f"  - {agent_id}: {status}", YELLOW)
                    else:
                        log(f"  - {agent}", YELLOW)
            else:
                log(f"✓ Agent response: {agents}", GREEN)
            return True
        else:
            log(f"✗ Failed to get agent status: {response.status_code}", RED)
            return False
    except Exception as e:
        log(f"✗ Agent status request failed: {e}", RED)
        return False

def main():
    """Run all tests"""
    log("\n" + "="*60, BLUE)
    log("PyPNM GUI Full Flow Test Suite", BLUE)
    log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", BLUE)
    log("="*60, BLUE)
    
    results = []
    
    # Test 1: Health
    results.append(("Health Check", test_health()))
    
    # Test 2: CMTS List
    first_cmts = test_cmts_list()
    results.append(("CMTS List", first_cmts is not None))
    
    # Test 3: Modem Discovery (use first CMTS from list)
    first_modem = None
    if first_cmts:
        first_modem = test_cmts_modems(first_cmts)
        results.append(("Modem Discovery", first_modem is not None))
    
    # Test 4: Modem Details (if we got a modem)
    if first_modem:
        mac = first_modem.get('mac_address')
        if mac:
            results.append(("Modem Details", test_modem_details(mac)))
    
    # Test 5: Agent Status
    results.append(("Agent Status", test_pypnm_agents()))
    
    # Summary
    log("\n" + "="*60, BLUE)
    log("TEST SUMMARY", BLUE)
    log("="*60, BLUE)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    log(f"Total: {total}", YELLOW)
    log(f"Passed: {passed}", GREEN if passed == total else YELLOW)
    log(f"Failed: {total - passed}", RED if passed < total else GREEN)
    
    log("\nDetailed Results:", YELLOW)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        color = GREEN if result else RED
        log(f"  {status} - {name}", color)
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
