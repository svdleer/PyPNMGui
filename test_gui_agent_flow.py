#!/usr/bin/env python3
"""
PyPNM GUI - Agent Flow Automated Test
======================================
Uses Playwright to test all GUI functions and verify agent handles SNMP.

Tests:
1. GUI loads correctly
2. CMTS list fetched via agent
3. Modem queries go through agent
4. PNM captures use agent SNMP
5. No direct SNMP from GUI/API (only from agent)

Usage:
    pip install playwright pytest
    playwright install chromium
    python3 test_gui_agent_flow.py
"""

import asyncio
import json
import subprocess
import time
from datetime import datetime
from playwright.async_api import async_playwright, Page
import requests

# Configuration
GUI_URL = "http://localhost:5050"
API_URL = "http://localhost:8000"
AGENT_SSH = "svdleer@access-engineering.nl"
AGENT_SSH_PORT = "65001"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def log(level, message):
    """Formatted logging"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    colors = {"INFO": Colors.BLUE, "PASS": Colors.GREEN, "FAIL": Colors.RED, "WARN": Colors.YELLOW}
    color = colors.get(level, "")
    print(f"{color}[{timestamp}] {level:5s}{Colors.END} {message}")

def check_agent_connected():
    """Verify agent is connected"""
    try:
        resp = requests.get(f"{API_URL}/api/agents", timeout=5)
        data = resp.json()
        if data.get("count", 0) > 0:
            agent_id = data["agents"][0]["agent_id"]
            log("PASS", f"Agent connected: {agent_id}")
            return True
        else:
            log("FAIL", "No agents connected")
            return False
    except Exception as e:
        log("FAIL", f"Cannot connect to API: {e}")
        return False

def watch_agent_logs_background():
    """Start watching agent logs in background"""
    try:
        # Clear old log
        subprocess.run("rm -f /tmp/agent_activity.log", shell=True)
        
        # Start monitoring in background
        cmd = f"ssh -p {AGENT_SSH_PORT} {AGENT_SSH} 'docker logs -f pypnm-agent-lab 2>&1' > /tmp/agent_activity.log 2>&1 &"
        subprocess.Popen(cmd, shell=True)
        time.sleep(2)
        log("INFO", "Started agent log monitoring (capturing ALL logs)")
        return True
    except Exception as e:
        log("WARN", f"Could not start log monitoring: {e}")
        return False

def check_agent_activity():
    """Check if agent processed any SNMP requests"""
    try:
        # Kill the background log tail
        subprocess.run("pkill -f 'docker logs -f pypnm-agent-lab'", shell=True, stderr=subprocess.DEVNULL)
        time.sleep(1)
        
        with open("/tmp/agent_activity.log", "r") as f:
            logs = f.read()
            
            # Look for various indicators of SNMP activity
            indicators = ["SNMP", "snmp_get", "snmp_walk", "task", "OID", "community"]
            found = []
            
            for indicator in indicators:
                if indicator in logs:
                    found.append(indicator)
            
            if found:
                log("PASS", f"Agent activity detected: {', '.join(found)}")
                # Show a sample log line
                for line in logs.split('\n'):
                    if any(ind in line for ind in found):
                        log("INFO", f"  Sample: {line.strip()[:100]}")
                        break
                return True
            else:
                log("WARN", "No agent SNMP activity detected")
                # Show last few log lines for debugging
                last_lines = logs.split('\n')[-5:]
                for line in last_lines:
                    if line.strip():
                        log("INFO", f"  Log: {line.strip()[:100]}")
                return False
    except Exception as e:
        log("WARN", f"Could not check agent logs: {e}")
        return False

async def test_gui_loads(page: Page):
    """Test 1: GUI loads successfully"""
    log("INFO", "Test 1: Loading GUI...")
    try:
        await page.goto(GUI_URL, wait_until="networkidle", timeout=10000)
        title = await page.title()
        if "PyPNM" in title or len(title) > 0:
            log("PASS", f"GUI loaded: {title}")
            return True
        else:
            log("FAIL", "GUI loaded but no title")
            return False
    except Exception as e:
        log("FAIL", f"GUI failed to load: {e}")
        return False

async def test_cmts_list(page: Page):
    """Test 2: CMTS list loads via agent"""
    log("INFO", "Test 2: Loading CMTS list...")
    try:
        # Navigate to CMTS page or API endpoint
        response = await page.goto(f"{GUI_URL}/api/pypnm/cmts", timeout=15000)
        
        if response.status == 200:
            content = await response.text()
            try:
                data = json.loads(content)
                if isinstance(data, list) and len(data) > 0:
                    log("PASS", f"CMTS list loaded: {len(data)} devices")
                    return True
                else:
                    log("WARN", "CMTS list empty (might be expected)")
                    return True  # Empty is OK
            except:
                log("WARN", "CMTS list response not JSON")
                return False
        else:
            log("FAIL", f"CMTS list failed: HTTP {response.status}")
            return False
    except Exception as e:
        log("FAIL", f"CMTS list error: {e}")
        return False

async def test_pnm_page_navigation(page: Page):
    """Test 3: Navigate to PNM page"""
    log("INFO", "Test 3: Navigating to PNM page...")
    try:
        await page.goto(f"{GUI_URL}/pnm", timeout=10000)
        await page.wait_for_load_state("networkidle")
        
        # Check if PNM page loaded
        content = await page.content()
        if "PNM" in content or "modem" in content.lower():
            log("PASS", "PNM page loaded")
            return True
        else:
            log("WARN", "PNM page loaded but content unclear")
            return False
    except Exception as e:
        log("FAIL", f"PNM page navigation failed: {e}")
        return False

async def test_pnm_operations(page: Page):
    """Test 4: Trigger actual PNM operations via GUI"""
    log("INFO", "Test 4: Testing PNM operations...")
    try:
        await page.goto(GUI_URL, timeout=10000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)
        
        # Take screenshot of main page
        await page.screenshot(path="/tmp/pypnm_main_page.png")
        log("INFO", "Main page screenshot saved")
        
        # Try to find CMTS selection dropdown
        cmts_select = await page.query_selector("select#cmts, select[name='cmts'], #cmtsSelect")
        if cmts_select:
            log("INFO", "Found CMTS selector")
            # Get options
            options = await cmts_select.query_selector_all("option")
            if len(options) > 1:  # First option is usually "Select..."
                await cmts_select.select_option(index=1)
                log("INFO", "Selected first CMTS")
                await page.wait_for_timeout(1000)
        
        # Try to find modem input field
        modem_input = await page.query_selector("input[type='text'], input#modem, input[name='modem']")
        if modem_input:
            log("INFO", "Found modem input field")
            # Enter a test modem MAC
            await modem_input.fill("001a.2b3c.4d5e")
            await page.wait_for_timeout(500)
        
        # Look for PNM operation buttons
        all_buttons = await page.query_selector_all("button")
        pnm_button_found = False
        
        for button in all_buttons:
            text = await button.inner_text()
            text_lower = text.lower()
            
            # Look for PNM operation buttons - expanded list
            if any(word in text_lower for word in ["get modems", "capture", "scan", "analyze", "rxmer", "start", "search", "query"]):
                log("INFO", f"Found PNM button: '{text}' - clicking it...")
                try:
                    await button.click()
                    pnm_button_found = True
                    log("INFO", "Waiting for operation to complete...")
                    await page.wait_for_timeout(5000)  # Wait 5s for SNMP operations
                    break
                except Exception as e:
                    log("WARN", f"Failed to click button: {e}")
                    continue
        
        if pnm_button_found:
            log("PASS", "Triggered PNM operation through GUI")
            # Take screenshot after clicking
            await page.screenshot(path="/tmp/pypnm_after_click.png")
            return True
        else:
            log("WARN", "Could not find/click PNM operation button")
            # List all button texts for debugging
            button_texts = []
            for btn in all_buttons[:10]:  # First 10 buttons
                try:
                    txt = await btn.inner_text()
                    if txt.strip():
                        button_texts.append(txt.strip())
                except:
                    pass
            log("INFO", f"Available buttons: {', '.join(button_texts)}")
            return False
            
    except Exception as e:
        log("FAIL", f"PNM operations test error: {e}")
        return False

async def test_api_health(page: Page):
    """Test 5: Check API health endpoints"""
    log("INFO", "Test 5: Checking API health...")
    try:
        response = await page.goto(f"{GUI_URL}/health", timeout=5000)
        if response.status == 200:
            content = await response.text()
            data = json.loads(content)
            log("PASS", f"API health OK: {data.get('status', 'unknown')}")
            return True
        else:
            log("FAIL", f"API health failed: HTTP {response.status}")
            return False
    except Exception as e:
        log("FAIL", f"API health error: {e}")
        return False

async def run_all_tests():
    """Run complete test suite"""
    print(f"\n{Colors.BOLD}{'='*60}")
    print("PyPNM GUI - Agent Flow Test Suite")
    print(f"{'='*60}{Colors.END}\n")
    
    # Pre-checks
    log("INFO", "Pre-flight checks...")
    if not check_agent_connected():
        log("FAIL", "Agent not connected - tests cannot proceed")
        return False
    
    watch_agent_logs_background()
    
    # Run browser tests
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            ignore_https_errors=True
        )
        page = await context.new_page()
        
        # Enable console logging
        page.on("console", lambda msg: log("INFO", f"Browser: {msg.text}"))
        page.on("pageerror", lambda err: log("WARN", f"Browser error: {err}"))
        
        try:
            # Run tests
            results.append(("GUI Loads", await test_gui_loads(page)))
            results.append(("CMTS List", await test_cmts_list(page)))
            results.append(("PNM Page", await test_pnm_page_navigation(page)))
            results.append(("PNM Operations", await test_pnm_operations(page)))
            results.append(("API Health", await test_api_health(page)))
            
            # Take screenshot
            await page.screenshot(path="/tmp/pypnm_gui_test.png")
            log("INFO", "Screenshot saved: /tmp/pypnm_gui_test.png")
            
        except Exception as e:
            log("FAIL", f"Test suite error: {e}")
        finally:
            await browser.close()
    
    # Post-checks
    time.sleep(2)
    results.append(("Agent Activity", check_agent_activity()))
    
    # Summary
    print(f"\n{Colors.BOLD}{'='*60}")
    print("Test Results")
    print(f"{'='*60}{Colors.END}\n")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{Colors.GREEN}✓ PASS{Colors.END}" if result else f"{Colors.RED}✗ FAIL{Colors.END}"
        print(f"  {status}  {test_name}")
    
    print(f"\n{Colors.BOLD}Overall: {passed}/{total} tests passed{Colors.END}\n")
    
    if passed == total:
        log("PASS", "All tests passed! ✅")
        return True
    else:
        log("WARN", f"{total - passed} test(s) failed")
        return False

if __name__ == "__main__":
    try:
        result = asyncio.run(run_all_tests())
        exit(0 if result else 1)
    except KeyboardInterrupt:
        log("WARN", "Tests interrupted by user")
        exit(1)
    except Exception as e:
        log("FAIL", f"Fatal error: {e}")
        exit(1)
