#!/usr/bin/env python3
"""
PyPNM GUI API Test Suite
Tests all API endpoints to verify functionality
"""

import requests
import json
import time
import sys
from datetime import datetime
from typing import Dict, List, Any

# Configuration
GUI_BASE_URL = "http://localhost:5050"
GUI_API_URL = "http://localhost:5050/api"
PYPNM_BASE_URL = "http://localhost:8000"

# Test data
TEST_MAC = "00:11:22:33:44:55"
TEST_IP = "10.1.1.100"
TEST_COMMUNITY = "private"
TEST_CMTS = "testcmts"

# Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

class APITester:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results = []
        
    def log(self, message, color=RESET):
        print(f"{color}{message}{RESET}")
        
    def test_endpoint(self, name: str, method: str, url: str, **kwargs) -> Dict:
        """Test a single endpoint"""
        self.log(f"\n{'='*60}", BLUE)
        self.log(f"Testing: {name}", BLUE)
        self.log(f"Method: {method} {url}", BLUE)
        
        try:
            start_time = time.time()
            
            if method == "GET":
                response = requests.get(url, timeout=30, **kwargs)
            elif method == "POST":
                response = requests.post(url, timeout=30, **kwargs)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            elapsed = time.time() - start_time
            
            result = {
                'name': name,
                'method': method,
                'url': url,
                'status_code': response.status_code,
                'elapsed': elapsed,
                'success': response.status_code in [200, 201],
                'response': None
            }
            
            # Try to parse JSON response
            try:
                result['response'] = response.json()
            except:
                result['response'] = response.text[:200]
            
            # Log result
            if result['success']:
                self.log(f"✓ PASS - Status: {response.status_code} - Time: {elapsed:.2f}s", GREEN)
                self.passed += 1
            else:
                self.log(f"✗ FAIL - Status: {response.status_code}", RED)
                self.log(f"Response: {result['response']}", RED)
                self.failed += 1
            
            self.results.append(result)
            return result
            
        except requests.exceptions.ConnectionError:
            self.log(f"✗ FAIL - Connection Error (is the service running?)", RED)
            self.failed += 1
            return {'name': name, 'success': False, 'error': 'Connection Error'}
            
        except Exception as e:
            self.log(f"✗ FAIL - {str(e)}", RED)
            self.failed += 1
            return {'name': name, 'success': False, 'error': str(e)}
    
    def skip_test(self, name: str, reason: str):
        """Skip a test"""
        self.log(f"\n{'='*60}", BLUE)
        self.log(f"Skipping: {name}", YELLOW)
        self.log(f"Reason: {reason}", YELLOW)
        self.skipped += 1
        self.results.append({'name': name, 'success': None, 'skipped': True, 'reason': reason})
    
    def test_health_endpoints(self):
        """Test health/status endpoints"""
        self.log("\n" + "="*60, BLUE)
        self.log("TESTING: Health & Status Endpoints", BLUE)
        self.log("="*60, BLUE)
        
        # GUI health
        self.test_endpoint(
            "GUI Health Check",
            "GET",
            f"{GUI_API_URL}/health"
        )
        
        # PyPNM API health
        self.test_endpoint(
            "PyPNM API Health Check",
            "GET",
            f"{PYPNM_BASE_URL}/"
        )
        
        # PyPNM API docs
        self.test_endpoint(
            "PyPNM API Documentation",
            "GET",
            f"{PYPNM_BASE_URL}/docs"
        )
    
    def test_cmts_endpoints(self):
        """Test CMTS management endpoints"""
        self.log("\n" + "="*60, BLUE)
        self.log("TESTING: CMTS Management Endpoints", BLUE)
        self.log("="*60, BLUE)
        
        # List all CMTS
        self.test_endpoint(
            "List All CMTS",
            "GET",
            f"{GUI_API_URL}/cmts"
        )
        
        # CMTS summary
        self.test_endpoint(
            "CMTS Summary",
            "GET",
            f"{GUI_API_URL}/cmts/summary"
        )
    
    def test_modem_endpoints(self):
        """Test modem-related endpoints"""
        self.log("\n" + "="*60, BLUE)
        self.log("TESTING: Modem Endpoints", BLUE)
        self.log("="*60, BLUE)
        
        # List modems
        self.test_endpoint(
            "List Modems",
            "GET",
            f"{GUI_API_URL}/modems"
        )
        
        # Get specific modem
        self.test_endpoint(
            "Get Specific Modem",
            "GET",
            f"{GUI_API_URL}/modems/{TEST_MAC}"
        )
        
        # System info (needs real modem)
        self.skip_test(
            "Modem System Info",
            "Requires real modem IP and SNMP access"
        )
    
    def test_pypnm_proxy_endpoints(self):
        """Test PyPNM proxy endpoints"""
        self.log("\n" + "="*60, BLUE)
        self.log("TESTING: PyPNM Proxy Endpoints", BLUE)
        self.log("="*60, BLUE)
        
        # These endpoints proxy to PyPNM API
        # They require a real cable modem with SNMP access
        
        endpoints = [
            ("Spectrum Analyzer", f"/pypnm/modem/{TEST_MAC}/spectrum"),
            ("FEC Summary", f"/pypnm/modem/{TEST_MAC}/fec"),
            ("Channel Stats", f"/pypnm/modem/{TEST_MAC}/channel-stats"),
        ]
        
        for name, path in endpoints:
            self.skip_test(
                name,
                "Requires real cable modem with SNMP access"
            )
    
    def test_pypnm_api_direct(self):
        """Test PyPNM API directly"""
        self.log("\n" + "="*60, BLUE)
        self.log("TESTING: PyPNM API Direct Endpoints", BLUE)
        self.log("="*60, BLUE)
        
        # Check agent status
        self.test_endpoint(
            "PyPNM Agent Status",
            "GET",
            f"{PYPNM_BASE_URL}/api/agents"
        )
        
        # OpenAPI spec
        self.test_endpoint(
            "PyPNM OpenAPI Spec",
            "GET",
            f"{PYPNM_BASE_URL}/openapi.json"
        )
    
    def test_data_endpoints(self):
        """Test data/configuration endpoints"""
        self.log("\n" + "="*60, BLUE)
        self.log("TESTING: Data & Configuration Endpoints", BLUE)
        self.log("="*60, BLUE)
        
        # These would test endpoints that return configuration data
        # Add any config endpoints here
        pass
    
    def run_all_tests(self):
        """Run all test suites"""
        self.log("\n" + "="*60, GREEN)
        self.log("PyPNM GUI API Test Suite", GREEN)
        self.log(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", GREEN)
        self.log("="*60, GREEN)
        
        self.log(f"\nGUI Base URL: {GUI_BASE_URL}", BLUE)
        self.log(f"PyPNM Base URL: {PYPNM_BASE_URL}", BLUE)
        
        # Run test suites
        self.test_health_endpoints()
        self.test_cmts_endpoints()
        self.test_modem_endpoints()
        self.test_pypnm_proxy_endpoints()
        self.test_pypnm_api_direct()
        self.test_data_endpoints()
        
        # Summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        self.log("\n" + "="*60, BLUE)
        self.log("TEST SUMMARY", BLUE)
        self.log("="*60, BLUE)
        
        total = self.passed + self.failed + self.skipped
        self.log(f"Total Tests: {total}", BLUE)
        self.log(f"Passed: {self.passed}", GREEN)
        self.log(f"Failed: {self.failed}", RED if self.failed > 0 else RESET)
        self.log(f"Skipped: {self.skipped}", YELLOW)
        
        if self.failed > 0:
            self.log("\nFailed Tests:", RED)
            for result in self.results:
                if result.get('success') == False:
                    self.log(f"  - {result['name']}", RED)
                    if 'error' in result:
                        self.log(f"    Error: {result['error']}", RED)
        
        # Save results to file
        self.save_results()
        
        # Exit code
        sys.exit(1 if self.failed > 0 else 0)
    
    def save_results(self):
        """Save test results to JSON file"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"test_results_{timestamp}.json"
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'gui_url': GUI_BASE_URL,
            'pypnm_url': PYPNM_BASE_URL,
            'total': self.passed + self.failed + self.skipped,
            'passed': self.passed,
            'failed': self.failed,
            'skipped': self.skipped,
            'results': self.results
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.log(f"\nResults saved to: {filename}", GREEN)

def main():
    """Main entry point"""
    # Check if services are reachable
    print(f"{BLUE}Checking if services are running...{RESET}")
    
    try:
        requests.get(GUI_BASE_URL, timeout=2)
        print(f"{GREEN}✓ GUI is reachable at {GUI_BASE_URL}{RESET}")
    except:
        print(f"{RED}✗ GUI is not reachable at {GUI_BASE_URL}{RESET}")
        print(f"{YELLOW}Make sure the GUI is running before running tests{RESET}")
        sys.exit(1)
    
    try:
        requests.get(PYPNM_BASE_URL, timeout=2)
        print(f"{GREEN}✓ PyPNM API is reachable at {PYPNM_BASE_URL}{RESET}")
    except:
        print(f"{YELLOW}⚠ PyPNM API is not reachable at {PYPNM_BASE_URL}{RESET}")
        print(f"{YELLOW}Some tests will be skipped{RESET}")
    
    # Run tests
    tester = APITester()
    tester.run_all_tests()

if __name__ == "__main__":
    main()
