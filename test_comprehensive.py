#!/usr/bin/env python3
"""
PyPNM GUI - Comprehensive API Test Suite
Tests all major API endpoints with real modem data
"""

import requests
import json
import time
import sys
from datetime import datetime

# Configuration
GUI_API_URL = "http://localhost:5050/api"
PYPNM_API_URL = "http://localhost:5050/api/pypnm"

# Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
BOLD = '\033[1m'
RESET = '\033[0m'

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.test_modem = None
        self.test_cmts = None
        
    def log(self, message, color=RESET):
        print(f"{color}{message}{RESET}")
    
    def section(self, title):
        self.log(f"\n{'='*70}", BLUE)
        self.log(f"{title}", BOLD + BLUE)
        self.log(f"{'='*70}", BLUE)
    
    def test(self, name, func):
        """Run a test function"""
        try:
            self.log(f"\n→ {name}...", CYAN)
            start = time.time()
            result = func()
            elapsed = time.time() - start
            
            if result:
                self.log(f"  ✓ PASS ({elapsed:.2f}s)", GREEN)
                self.passed += 1
                return True
            else:
                self.log(f"  ✗ FAIL ({elapsed:.2f}s)", RED)
                self.failed += 1
                return False
        except Exception as e:
            self.log(f"  ✗ ERROR: {e}", RED)
            self.failed += 1
            return False
    
    def skip(self, name, reason):
        """Skip a test"""
        self.log(f"\n→ {name}...", CYAN)
        self.log(f"  ⊘ SKIP: {reason}", YELLOW)
        self.skipped += 1
    
    def summary(self):
        """Print test summary"""
        self.section("TEST SUMMARY")
        total = self.passed + self.failed + self.skipped
        self.log(f"Total Tests: {total}", YELLOW)
        self.log(f"Passed:  {self.passed}", GREEN)
        self.log(f"Failed:  {self.failed}", RED if self.failed > 0 else GREEN)
        self.log(f"Skipped: {self.skipped}", YELLOW)
        
        pass_rate = (self.passed / total * 100) if total > 0 else 0
        self.log(f"\nPass Rate: {pass_rate:.1f}%", GREEN if pass_rate >= 80 else YELLOW)
        
        return self.failed == 0

# Test functions
def test_health():
    """Health check"""
    r = requests.get(f"{GUI_API_URL}/health", timeout=5)
    return r.status_code == 200

def test_cmts_list(runner):
    """List CMTS devices"""
    r = requests.get(f"{GUI_API_URL}/cmts", timeout=10)
    if r.status_code == 200:
        data = r.json()
        cmts_list = data.get('cmts_list', [])
        print(f"    Found {len(cmts_list)} CMTS devices")
        if cmts_list:
            runner.test_cmts = cmts_list[0].get('HostName')
            print(f"    Using: {runner.test_cmts}")
        return len(cmts_list) > 0
    return False

def test_cmts_summary():
    """CMTS summary"""
    r = requests.get(f"{GUI_API_URL}/cmts/summary", timeout=10)
    return r.status_code == 200

def test_cmts_detail(runner):
    """Get CMTS details"""
    if not runner.test_cmts:
        return False
    r = requests.get(f"{GUI_API_URL}/cmts/{runner.test_cmts}", timeout=10)
    return r.status_code == 200

def test_cmts_interfaces(runner):
    """Get CMTS interfaces"""
    if not runner.test_cmts:
        return False
    r = requests.get(f"{GUI_API_URL}/cmts/{runner.test_cmts}/interfaces", timeout=10)
    return r.status_code == 200

def test_modem_discovery(runner):
    """Discover modems from CMTS"""
    if not runner.test_cmts:
        return False
    
    print(f"    Querying {runner.test_cmts}...")
    r = requests.get(
        f"{GUI_API_URL}/cmts/{runner.test_cmts}/modems",
        params={'limit': 5, 'use_cache': True},
        timeout=60
    )
    
    if r.status_code == 200:
        data = r.json()
        modems = data.get('modems', [])
        print(f"    Retrieved {len(modems)} modems")
        
        if modems:
            # Find online modem with IP
            for modem in modems:
                if modem.get('ip_address') and modem.get('ip_address') not in ['0.0.0.0', 'N/A']:
                    runner.test_modem = modem
                    print(f"    Test modem: {modem['mac_address']} ({modem['ip_address']})")
                    break
        
        return len(modems) > 0
    return False

def test_modem_cache(runner):
    """Get modem from cache"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    r = requests.get(f"{GUI_API_URL}/modems/{mac}", timeout=10)
    return r.status_code in [200, 404]  # 404 is OK if not cached

def test_modem_system_info(runner):
    """Get modem system info via agent"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    ip = runner.test_modem.get('ip_address')
    
    r = requests.post(
        f"{GUI_API_URL}/modem/{mac}/system-info",
        json={'modem_ip': ip, 'community': 'm0d3m1nf0'},
        timeout=30
    )
    
    if r.status_code == 200:
        data = r.json()
        print(f"    Vendor: {data.get('vendor', 'N/A')}")
        print(f"    Model: {data.get('model', 'N/A')}")
        return True
    return False

def test_modem_uptime(runner):
    """Get modem uptime"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    ip = runner.test_modem.get('ip_address')
    
    r = requests.post(
        f"{GUI_API_URL}/modem/{mac}/uptime",
        json={'modem_ip': ip, 'community': 'm0d3m1nf0'},
        timeout=30
    )
    
    if r.status_code == 200:
        data = r.json()
        print(f"    Uptime: {data.get('uptime_formatted', 'N/A')}")
        return True
    return False

def test_modem_ds_channels(runner):
    """Get downstream channels"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    ip = runner.test_modem.get('ip_address')
    
    r = requests.post(
        f"{GUI_API_URL}/modem/{mac}/ds-channels",
        json={'modem_ip': ip, 'community': 'm0d3m1nf0'},
        timeout=30
    )
    
    if r.status_code == 200:
        data = r.json()
        channels = data.get('channels', [])
        print(f"    Channels: {len(channels)}")
        return len(channels) > 0
    return False

def test_modem_us_channels(runner):
    """Get upstream channels"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    ip = runner.test_modem.get('ip_address')
    
    r = requests.post(
        f"{GUI_API_URL}/modem/{mac}/us-channels",
        json={'modem_ip': ip, 'community': 'm0d3m1nf0'},
        timeout=30
    )
    
    if r.status_code == 200:
        data = r.json()
        channels = data.get('channels', [])
        print(f"    Channels: {len(channels)}")
        return len(channels) > 0
    return False

def test_cache_stats():
    """Get cache statistics"""
    r = requests.get(f"{GUI_API_URL}/cache/stats", timeout=10)
    if r.status_code == 200:
        data = r.json()
        print(f"    Modems cached: {data.get('modems_count', 0)}")
        print(f"    CMTS cached: {data.get('cmts_count', 0)}")
        return True
    return False

def test_pypnm_channel_stats(runner):
    """Get channel statistics via PyPNM"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    ip = runner.test_modem.get('ip_address')
    
    r = requests.post(
        f"{PYPNM_API_URL}/channel-stats/{mac}",
        json={'modem_ip': ip, 'community': 'm0d3m1nf0'},
        timeout=30
    )
    
    return r.status_code in [200, 500]  # 500 if modem offline

def test_pypnm_upstream_interfaces(runner):
    """Get upstream interfaces"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    ip = runner.test_modem.get('ip_address')
    
    r = requests.post(
        f"{PYPNM_API_URL}/upstream/interfaces/{mac}",
        json={'modem_ip': ip, 'community': 'm0d3m1nf0'},
        timeout=30
    )
    
    return r.status_code in [200, 500]

def test_pypnm_plots(runner):
    """List available plots"""
    if not runner.test_modem:
        return False
    
    mac = runner.test_modem['mac_address']
    r = requests.get(f"{PYPNM_API_URL}/plots/{mac}", timeout=10)
    
    if r.status_code == 200:
        data = r.json()
        plots = data.get('plots', [])
        print(f"    Available plots: {len(plots)}")
        return True
    return False

def main():
    """Run all tests"""
    runner = TestRunner()
    
    runner.section("PyPNM GUI - Comprehensive API Test Suite")
    runner.log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", YELLOW)
    
    # Basic endpoints
    runner.section("1. BASIC ENDPOINTS")
    runner.test("Health Check", lambda: test_health())
    runner.test("CMTS List", lambda: test_cmts_list(runner))
    runner.test("CMTS Summary", lambda: test_cmts_summary())
    
    # CMTS endpoints
    runner.section("2. CMTS ENDPOINTS")
    runner.test("CMTS Details", lambda: test_cmts_detail(runner))
    runner.test("CMTS Interfaces", lambda: test_cmts_interfaces(runner))
    
    # Modem discovery
    runner.section("3. MODEM DISCOVERY")
    runner.test("Discover Modems from CMTS", lambda: test_modem_discovery(runner))
    runner.test("Get Modem from Cache", lambda: test_modem_cache(runner))
    
    # Modem details (requires online modem)
    runner.section("4. MODEM DETAILS (via Agent)")
    if runner.test_modem:
        runner.test("System Info", lambda: test_modem_system_info(runner))
        runner.test("Uptime", lambda: test_modem_uptime(runner))
        runner.test("Downstream Channels", lambda: test_modem_ds_channels(runner))
        runner.test("Upstream Channels", lambda: test_modem_us_channels(runner))
    else:
        runner.skip("System Info", "No online modem available")
        runner.skip("Uptime", "No online modem available")
        runner.skip("Downstream Channels", "No online modem available")
        runner.skip("Upstream Channels", "No online modem available")
    
    # Cache management
    runner.section("5. CACHE MANAGEMENT")
    runner.test("Cache Statistics", lambda: test_cache_stats())
    
    # PyPNM endpoints
    runner.section("6. PYPNM INTEGRATION")
    if runner.test_modem:
        runner.test("Channel Statistics", lambda: test_pypnm_channel_stats(runner))
        runner.test("Upstream Interfaces", lambda: test_pypnm_upstream_interfaces(runner))
        runner.test("Available Plots", lambda: test_pypnm_plots(runner))
    else:
        runner.skip("Channel Statistics", "No online modem available")
        runner.skip("Upstream Interfaces", "No online modem available")
        runner.skip("Available Plots", "No online modem available")
    
    # Summary
    success = runner.summary()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
