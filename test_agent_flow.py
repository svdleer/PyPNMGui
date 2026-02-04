#!/usr/bin/env python3
"""
PyPNM Agent Flow Test - Simple & Clean
=======================================
Automated Chromium test to verify:
1. GUI loads
2. Click "Get Modems" button
3. Agent performs SNMP (not GUI/API)
4. Results display in GUI

Usage:
    python3 test_agent_flow.py
"""

import asyncio
import time
from playwright.async_api import async_playwright
import subprocess
import sys

GUI_URL = "http://localhost:5050"

class TestResult:
    def __init__(self):
        self.passed = []
        self.failed = []
    
    def add_pass(self, name):
        self.passed.append(name)
        print(f"✓ PASS: {name}")
    
    def add_fail(self, name, reason=""):
        self.failed.append((name, reason))
        print(f"✗ FAIL: {name}" + (f" - {reason}" if reason else ""))
    
    def summary(self):
        total = len(self.passed) + len(self.failed)
        print(f"\n{'='*60}")
        print(f"Results: {len(self.passed)}/{total} tests passed")
        print(f"{'='*60}\n")
        return len(self.failed) == 0

def start_agent_monitor():
    """Start monitoring agent logs"""
    print("Starting agent log monitor...")
    cmd = 'ssh -p 65001 svdleer@access-engineering.nl "docker logs -f pypnm-agent-lab 2>&1" > /tmp/agent_test.log 2>&1 &'
    subprocess.Popen(cmd, shell=True)
    time.sleep(2)

def check_agent_activity():
    """Check if agent performed SNMP"""
    try:
        with open("/tmp/agent_test.log", "r") as f:
            logs = f.read()
            # Look for SNMP activity after we started monitoring
            recent = logs.split("Starting agent log monitor")[-1] if "Starting" in logs else logs
            has_snmp = any(word in recent.lower() for word in ["snmp", "task received", "executing"])
            return has_snmp, recent[-500:] if recent else "No logs"
    except:
        return False, "Could not read logs"

async def run_test():
    result = TestResult()
    
    print(f"\n{'='*60}")
    print("PyPNM Agent Flow Test")
    print(f"{'='*60}\n")
    
    # Clear old logs
    subprocess.run("rm -f /tmp/agent_test.log", shell=True)
    start_agent_monitor()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # Show browser so you can see it work
            slow_mo=1000     # Slow down so you can see actions
        )
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        try:
            # Test 1: Load GUI
            print("\nTest 1: Loading GUI...")
            await page.goto(GUI_URL, timeout=15000)
            await page.wait_for_load_state("networkidle")
            title = await page.title()
            if title:
                result.add_pass(f"GUI loads ({title})")
            else:
                result.add_fail("GUI loads", "No title")
            
            # Test 2: Find CMTS dropdown
            print("\nTest 2: Finding CMTS selector...")
            cmts_select = await page.query_selector("#cmts")
            if cmts_select:
                result.add_pass("CMTS selector found")
                # Select first CMTS
                await cmts_select.select_option(index=1)
                print("  → Selected first CMTS")
            else:
                result.add_fail("CMTS selector found", "Element #cmts not found")
            
            # Test 3: Click Get Modems button
            print("\nTest 3: Clicking 'Get Modems' button...")
            await page.wait_for_timeout(1000)
            
            # Try to find and click the Get Modems button
            get_modems_btn = await page.query_selector("button:has-text('Get Modems')")
            if get_modems_btn:
                result.add_pass("Get Modems button found")
                print("  → Clicking button...")
                await get_modems_btn.click()
                result.add_pass("Get Modems button clicked")
                
                # Wait for operation
                print("  → Waiting for results (10 seconds)...")
                await page.wait_for_timeout(10000)
                
            else:
                result.add_fail("Get Modems button found")
            
            # Test 4: Check if results appeared
            print("\nTest 4: Checking for modem results...")
            await page.wait_for_timeout(2000)
            
            # Look for modem table or results
            modem_table = await page.query_selector("table")
            if modem_table:
                rows = await modem_table.query_selector_all("tr")
                if len(rows) > 1:  # Header + data
                    result.add_pass(f"Modem results displayed ({len(rows)-1} rows)")
                else:
                    result.add_fail("Modem results displayed", "Table empty")
            else:
                result.add_fail("Modem results displayed", "No table found")
            
            # Take screenshot
            await page.screenshot(path="/tmp/agent_test_final.png")
            print("\n📸 Screenshot saved: /tmp/agent_test_final.png")
            
            # Keep browser open for 5 seconds so you can see
            print("\nKeeping browser open for 5 seconds...")
            await page.wait_for_timeout(5000)
            
        except Exception as e:
            result.add_fail("Test execution", str(e))
        finally:
            await browser.close()
    
    # Test 5: Check agent activity
    print("\nTest 5: Checking agent SNMP activity...")
    time.sleep(2)
    has_activity, log_sample = check_agent_activity()
    if has_activity:
        result.add_pass("Agent performed SNMP operations")
        print(f"  → Recent logs: ...{log_sample[-200:]}")
    else:
        result.add_fail("Agent performed SNMP operations", "No SNMP detected")
        print(f"  → Logs: {log_sample}")
    
    # Summary
    return result.summary()

if __name__ == "__main__":
    try:
        success = asyncio.run(run_test())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Fatal error: {e}")
        sys.exit(1)
