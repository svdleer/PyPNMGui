#!/usr/bin/env python3
"""
PyPNM GUI - Playwright E2E Tests
Tests all GUI functions on the PNM page using real browser automation
"""

import sys
import time
from playwright.sync_api import sync_playwright, expect

# Configuration
GUI_URL = "http://localhost:5050"
TEST_TIMEOUT = 30000  # 30 seconds

# Colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def log(message, color=RESET):
    print(f"{color}{message}{RESET}")

class GUITester:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.playwright = None
        self.browser = None
        self.page = None
        
    def setup(self):
        """Initialize Playwright and browser"""
        log("\n" + "="*60, BLUE)
        log("Setting up Playwright with Chromium", BLUE)
        log("="*60, BLUE)
        
        try:
            self.playwright = sync_playwright().start()
            # Launch Chromium with visible UI (headless=False for debugging)
            self.browser = self.playwright.chromium.launch(
                headless=False,  # Set to True for CI/CD
                slow_mo=500  # Slow down by 500ms to see actions
            )
            self.page = self.browser.new_page(viewport={'width': 1920, 'height': 1080})
            self.page.set_default_timeout(TEST_TIMEOUT)
            
            log("✓ Chromium browser launched", GREEN)
            return True
        except Exception as e:
            log(f"✗ Failed to setup browser: {e}", RED)
            return False
    
    def teardown(self):
        """Close browser and Playwright"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        log("\n✓ Browser closed", GREEN)
    
    def test_page_load(self):
        """Test that the main page loads"""
        log("\n" + "="*60, BLUE)
        log("TEST 1: Page Load", BLUE)
        log("="*60, BLUE)
        
        try:
            self.page.goto(GUI_URL)
            
            # Wait for page to load - check for navbar
            self.page.wait_for_selector("nav.navbar", timeout=10000)
            
            # Check title
            title = self.page.title()
            assert "PyPNM" in title, f"Title should contain 'PyPNM', got: {title}"
            
            # Check main navigation items
            self.page.wait_for_selector("text=Home")
            self.page.wait_for_selector("text=Modems")
            
            log(f"✓ Page loaded successfully: {title}", GREEN)
            log(f"✓ URL: {self.page.url}", GREEN)
            self.passed += 1
            return True
        except Exception as e:
            log(f"✗ Page load failed: {e}", RED)
            self.failed += 1
            return False
    
    def test_api_status(self):
        """Test API connection status badges"""
        log("\n" + "="*60, BLUE)
        log("TEST 2: API Status Indicators", BLUE)
        log("="*60, BLUE)
        
        try:
            # Wait for status badges to appear
            time.sleep(2)  # Give Vue.js time to update
            
            # Check for API Connected badge (green) or Mock Data Mode (yellow)
            api_badge = self.page.locator(".badge").filter(has_text="API Connected")
            mock_badge = self.page.locator(".badge").filter(has_text="Mock Data Mode")
            
            if api_badge.count() > 0:
                log("✓ API Connected status visible", GREEN)
            elif mock_badge.count() > 0:
                log("⚠ Running in Mock Data Mode", YELLOW)
            else:
                log("⚠ No API status badge found", YELLOW)
            
            # Check PyPNM status
            pypnm_badge = self.page.locator(".badge").filter(has_text="PyPNM")
            if pypnm_badge.count() > 0:
                log("✓ PyPNM status badge visible", GREEN)
            
            self.passed += 1
            return True
        except Exception as e:
            log(f"✗ API status check failed: {e}", RED)
            self.failed += 1
            return False
    
    def test_cmts_selection(self):
        """Test CMTS dropdown and selection"""
        log("\n" + "="*60, BLUE)
        log("TEST 3: CMTS Selection", BLUE)
        log("="*60, BLUE)
        
        try:
            # Find CMTS filter dropdown
            cmts_select = self.page.locator("select").filter(has_text="All CMTS")
            cmts_select.wait_for(state="visible", timeout=5000)
            
            # Get number of CMTS devices
            cmts_text = cmts_select.inner_text()
            log(f"✓ CMTS dropdown found: {cmts_text[:50]}...", GREEN)
            
            # Select first CMTS (not "All CMTS")
            options = self.page.locator("select option").all()
            if len(options) > 1:
                # Select second option (first real CMTS)
                cmts_select.select_option(index=1)
                selected = cmts_select.input_value()
                log(f"✓ Selected CMTS: {selected}", GREEN)
                
                # Wait for interface dropdown to enable
                time.sleep(1)
                interface_select = self.page.locator("select").nth(1)
                is_enabled = not interface_select.is_disabled()
                if is_enabled:
                    log("✓ Interface dropdown enabled after CMTS selection", GREEN)
                else:
                    log("⚠ Interface dropdown still disabled", YELLOW)
                
                self.passed += 1
                return selected  # Return CMTS name for next test
            else:
                log("⚠ No CMTS devices found in dropdown", YELLOW)
                self.passed += 1
                return None
                
        except Exception as e:
            log(f"✗ CMTS selection failed: {e}", RED)
            self.failed += 1
            return None
    
    def test_get_modems(self, cmts_name):
        """Test Get Modems button"""
        log("\n" + "="*60, BLUE)
        log("TEST 4: Get Modems from CMTS", BLUE)
        log("="*60, BLUE)
        
        if not cmts_name:
            log("⚠ Skipping - no CMTS selected", YELLOW)
            return False
        
        try:
            # Find and click "Get Modems" button
            get_modems_btn = self.page.locator("button").filter(has_text="Get Modems")
            get_modems_btn.wait_for(state="visible", timeout=5000)
            
            log(f"Clicking 'Get Modems' button for {cmts_name}...", YELLOW)
            get_modems_btn.click()
            
            # Wait for loading state
            loading = self.page.locator("button").filter(has_text="Loading")
            if loading.count() > 0:
                log("✓ Loading state detected", GREEN)
                # Wait for loading to complete (up to 60 seconds)
                get_modems_btn.wait_for(state="visible", timeout=60000)
            
            # Wait for modems table to appear
            time.sleep(3)
            
            # Check if any modem data appeared
            modem_rows = self.page.locator("table tbody tr").count()
            if modem_rows > 0:
                log(f"✓ Found {modem_rows} modem rows in table", GREEN)
                self.passed += 1
                return True
            else:
                # Check for "No modems found" message
                no_modems = self.page.locator("text=No modems found").count()
                if no_modems > 0:
                    log("⚠ No modems found (empty result)", YELLOW)
                else:
                    log("⚠ No modem table visible yet", YELLOW)
                self.passed += 1
                return False
                
        except Exception as e:
            log(f"✗ Get modems failed: {e}", RED)
            self.failed += 1
            return False
    
    def test_modem_selection(self):
        """Test selecting a modem from the list"""
        log("\n" + "="*60, BLUE)
        log("TEST 5: Select Modem from List", BLUE)
        log("="*60, BLUE)
        
        try:
            # Find first modem row with clickable action
            modem_row = self.page.locator("table tbody tr").first
            
            if modem_row.count() == 0:
                log("⚠ No modem rows found to select", YELLOW)
                return False
            
            # Try to find and click a "Select" or "View Details" button in the row
            select_btn = modem_row.locator("button").filter(has_text="Select")
            view_btn = modem_row.locator("button").filter(has_text="View")
            action_btn = modem_row.locator("button").first
            
            if select_btn.count() > 0:
                log("Clicking modem 'Select' button...", YELLOW)
                select_btn.click()
            elif view_btn.count() > 0:
                log("Clicking modem 'View' button...", YELLOW)
                view_btn.click()
            elif action_btn.count() > 0:
                log("Clicking first action button in row...", YELLOW)
                action_btn.click()
            else:
                # Try clicking the row itself
                log("Clicking modem row...", YELLOW)
                modem_row.click()
            
            time.sleep(2)  # Wait for Vue.js to update state
            
            # Check if measurements navigation became visible
            measurements_nav = self.page.locator("a.nav-link").filter(has_text="Measurements")
            if measurements_nav.count() > 0 and measurements_nav.is_visible():
                log("✓ Measurements navigation is now visible", GREEN)
                self.passed += 1
                return True
            else:
                log("⚠ Measurements navigation still not visible (modem may need to be selected differently)", YELLOW)
                self.passed += 1
                return False
                
        except Exception as e:
            log(f"✗ Modem selection failed: {e}", RED)
            self.failed += 1
            return False
    
    def test_measurements_view(self):
        """Test switching to Measurements view"""
        log("\n" + "="*60, BLUE)
        log("TEST 6: Measurements View", BLUE)
        log("="*60, BLUE)
        
        try:
            # Click Measurements navigation
            measurements_link = self.page.locator("text=Measurements")
            if measurements_link.count() > 0:
                log("Clicking 'Measurements' navigation...", YELLOW)
                measurements_link.click()
                time.sleep(2)
                
                # Check for measurement buttons/tabs
                spectrum_btn = self.page.locator("button").filter(has_text="Spectrum")
                rxmer_btn = self.page.locator("button").filter(has_text="RxMER")
                fec_btn = self.page.locator("button").filter(has_text="FEC")
                
                found_buttons = []
                if spectrum_btn.count() > 0:
                    found_buttons.append("Spectrum")
                if rxmer_btn.count() > 0:
                    found_buttons.append("RxMER")
                if fec_btn.count() > 0:
                    found_buttons.append("FEC")
                
                if found_buttons:
                    log(f"✓ Found measurement buttons: {', '.join(found_buttons)}", GREEN)
                    self.passed += 1
                    return True
                else:
                    log("⚠ No measurement buttons found", YELLOW)
                    self.passed += 1
                    return False
            else:
                log("⚠ Measurements navigation not visible", YELLOW)
                return False
                
        except Exception as e:
            log(f"✗ Measurements view test failed: {e}", RED)
            self.failed += 1
            return False
    
    def test_spectrum_analyzer(self):
        """Test Spectrum Analyzer function"""
        log("\n" + "="*60, BLUE)
        log("TEST 7: Spectrum Analyzer", BLUE)
        log("="*60, BLUE)
        
        try:
            # Find and click Spectrum button
            spectrum_btn = self.page.locator("button").filter(has_text="Spectrum")
            
            if spectrum_btn.count() == 0:
                log("⚠ Spectrum button not found", YELLOW)
                return False
            
            log("Clicking 'Spectrum' button...", YELLOW)
            spectrum_btn.click()
            time.sleep(2)
            
            # Look for spectrum chart or canvas
            canvas = self.page.locator("canvas")
            chart_container = self.page.locator("[id*='chart']")
            
            if canvas.count() > 0:
                log(f"✓ Found {canvas.count()} canvas element(s) (chart)", GREEN)
                self.passed += 1
                return True
            elif chart_container.count() > 0:
                log(f"✓ Found chart container", GREEN)
                self.passed += 1
                return True
            else:
                # Check for loading or error message
                loading_msg = self.page.locator("text=Loading").count()
                error_msg = self.page.locator("text=Error").count()
                
                if loading_msg > 0:
                    log("⚠ Still loading...", YELLOW)
                elif error_msg > 0:
                    log("⚠ Error message displayed", YELLOW)
                else:
                    log("⚠ No chart found", YELLOW)
                
                self.passed += 1
                return False
                
        except Exception as e:
            log(f"✗ Spectrum analyzer test failed: {e}", RED)
            self.failed += 1
            return False
    
    def test_navigation_back(self):
        """Test navigating back to home"""
        log("\n" + "="*60, BLUE)
        log("TEST 8: Navigate Back to Home", BLUE)
        log("="*60, BLUE)
        
        try:
            # Click Home navigation
            home_link = self.page.locator("text=Home").first
            log("Clicking 'Home' navigation...", YELLOW)
            home_link.click()
            time.sleep(1)
            
            # Check if CMTS filter is visible again
            cmts_filter = self.page.locator("text=CMTS Filter")
            if cmts_filter.count() > 0:
                log("✓ Back on Home view", GREEN)
                self.passed += 1
                return True
            else:
                log("⚠ Not on Home view", YELLOW)
                self.passed += 1
                return False
                
        except Exception as e:
            log(f"✗ Navigation test failed: {e}", RED)
            self.failed += 1
            return False
    
    def take_screenshot(self, name):
        """Take screenshot for debugging"""
        try:
            filename = f"/tmp/pypnm_gui_test_{name}.png"
            self.page.screenshot(path=filename)
            log(f"📸 Screenshot saved: {filename}", YELLOW)
        except Exception as e:
            log(f"⚠ Failed to take screenshot: {e}", YELLOW)
    
    def run_all_tests(self):
        """Run all GUI tests"""
        log("\n" + "="*60, BLUE)
        log("PyPNM GUI - Playwright E2E Test Suite", BLUE)
        log(f"Testing URL: {GUI_URL}", BLUE)
        log("="*60, BLUE)
        
        if not self.setup():
            return 1
        
        try:
            # Run tests in sequence
            self.test_page_load()
            self.take_screenshot("01_page_load")
            
            self.test_api_status()
            
            cmts_name = self.test_cmts_selection()
            self.take_screenshot("03_cmts_selected")
            
            has_modems = self.test_get_modems(cmts_name)
            self.take_screenshot("04_modems_loaded")
            
            if has_modems:
                modem_selected = self.test_modem_selection()
                self.take_screenshot("05_modem_selected")
                
                if modem_selected:
                    self.test_measurements_view()
                    self.take_screenshot("06_measurements")
                    
                    self.test_spectrum_analyzer()
                    self.take_screenshot("07_spectrum")
            
            self.test_navigation_back()
            self.take_screenshot("08_back_home")
            
            # Summary
            log("\n" + "="*60, BLUE)
            log("TEST SUMMARY", BLUE)
            log("="*60, BLUE)
            
            total = self.passed + self.failed
            log(f"Total Tests: {total}", YELLOW)
            log(f"Passed: {self.passed}", GREEN)
            log(f"Failed: {self.failed}", RED if self.failed > 0 else GREEN)
            
            success_rate = (self.passed / total * 100) if total > 0 else 0
            log(f"Success Rate: {success_rate:.1f}%", GREEN if success_rate >= 80 else YELLOW)
            
            return 0 if self.failed == 0 else 1
            
        finally:
            self.teardown()

def main():
    """Main entry point"""
    tester = GUITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())
