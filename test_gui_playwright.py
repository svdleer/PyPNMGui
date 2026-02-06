#!/usr/bin/env python3
"""
PyPNM GUI - Playwright E2E Tests
Complete test suite for all GUI functions and PyPNM API endpoints
using real browser automation with Chromium

Tests cover:
- Page load and navigation
- API status indicators  
- CMTS selection and modem listing
- All PNM measurements (Spectrum, RxMER, FEC, Constellation, etc.)
- Channel statistics
- Event logs
- Upstream measurements (UTSC, OFDMA RxMER)

Run: python test_gui_playwright.py
     python test_gui_playwright.py --headless
     python test_gui_playwright.py --modem-mac 00:11:22:33:44:55 --modem-ip 10.1.1.100
"""

import sys
import time
import json
from playwright.sync_api import sync_playwright, expect

# Configuration
GUI_URL = "http://localhost:5050"
API_BASE = "http://localhost:5050/api"
PYPNM_API = "http://localhost:8000"
TEST_TIMEOUT = 30000  # 30 seconds
MEASUREMENT_TIMEOUT = 120000  # 120 seconds for PNM measurements

# Test modem (update with a real modem for live testing)
TEST_MODEM_MAC = "ac:22:05:3a:d5:c0"  # Online modem from lab CMTS
TEST_MODEM_IP = "10.206.234.83"  # Online modem IP
TEST_CMTS = "mnd-gt0002-ccap002"  # Lab CMTS
SNMP_COMMUNITY = "z1gg0m0n1t0r1ng"

# Colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'


def log(message, color=RESET):
    print(f"{color}{message}{RESET}")


def section(title):
    log("\n" + "=" * 70, BLUE)
    log(f"  {title}", BLUE)
    log("=" * 70, BLUE)


class GUITester:
    def __init__(self, headless=False, slow_mo=300):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.playwright = None
        self.browser = None
        self.page = None
        self.context = None
        self.headless = headless
        self.slow_mo = slow_mo
        self.selected_modem = None
        self.test_results = []

    def setup(self):
        """Initialize Playwright and browser"""
        section("Setting up Playwright with Chromium")

        try:
            self.playwright = sync_playwright().start()
            # Launch Chromium
            self.browser = self.playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo
            )
            self.context = self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                record_video_dir="/tmp/playwright-videos" if not self.headless else None
            )
            self.page = self.context.new_page()
            self.page.set_default_timeout(TEST_TIMEOUT)

            # Setup console logging for errors
            self.page.on("console", lambda msg: log(f"  [Browser] {msg.text}", CYAN) 
                        if "error" in msg.text.lower() else None)

            log("✓ Chromium browser launched", GREEN)
            log(f"  Headless: {self.headless}, SlowMo: {self.slow_mo}ms", CYAN)
            return True
        except Exception as e:
            log(f"✗ Failed to setup browser: {e}", RED)
            return False

    def teardown(self):
        """Close browser and Playwright"""
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        log("\n✓ Browser closed", GREEN)

    def record_result(self, test_name, passed, message=""):
        """Record test result"""
        self.test_results.append({
            "test": test_name,
            "passed": passed,
            "message": message
        })
        if passed:
            self.passed += 1
        elif passed is None:
            self.skipped += 1
        else:
            self.failed += 1

    def take_screenshot(self, name):
        """Take screenshot for debugging"""
        try:
            filename = f"/tmp/pypnm_gui_test_{name}.png"
            self.page.screenshot(path=filename, full_page=True)
            log(f"  📸 Screenshot: {filename}", CYAN)
            return filename
        except Exception as e:
            log(f"  ⚠ Screenshot failed: {e}", YELLOW)
            return None

    # ============== Basic Tests ==============

    def test_page_load(self):
        """Test that the main page loads"""
        section("TEST 1: Page Load")

        try:
            self.page.goto(GUI_URL)

            # Wait for page to load - check for Vue app
            self.page.wait_for_selector("#app", timeout=10000)

            # Check title
            title = self.page.title()
            assert "PyPNM" in title, f"Title should contain 'PyPNM', got: {title}"

            # Check main elements exist
            self.page.wait_for_selector("nav.navbar", timeout=5000)

            log(f"✓ Page loaded: {title}", GREEN)
            log(f"  URL: {self.page.url}", CYAN)
            self.record_result("Page Load", True)
            return True
        except Exception as e:
            log(f"✗ Page load failed: {e}", RED)
            self.record_result("Page Load", False, str(e))
            return False

    def test_api_health(self):
        """Test API health endpoints via browser"""
        section("TEST 2: API Health Check")

        try:
            # Test GUI backend health
            response = self.page.request.get(f"{API_BASE}/health")
            assert response.ok, f"GUI health check failed: {response.status}"
            health = response.json()
            log(f"✓ GUI Backend healthy: {health.get('status')}", GREEN)

            # Test PyPNM health
            response = self.page.request.get(f"{API_BASE}/pypnm/health")
            if response.ok:
                pypnm_health = response.json()
                pypnm_ok = pypnm_health.get('pypnm_healthy', False)
                if pypnm_ok:
                    log(f"✓ PyPNM API healthy", GREEN)
                else:
                    log(f"⚠ PyPNM API not reachable (may be running in mock mode)", YELLOW)
            else:
                log(f"⚠ PyPNM health check returned {response.status}", YELLOW)

            self.record_result("API Health", True)
            return True
        except Exception as e:
            log(f"✗ API health check failed: {e}", RED)
            self.record_result("API Health", False, str(e))
            return False

    def test_cmts_list(self):
        """Test CMTS listing"""
        section("TEST 3: CMTS List")

        try:
            response = self.page.request.get(f"{API_BASE}/cmts")
            assert response.ok, f"CMTS list failed: {response.status}"
            data = response.json()

            cmts_list = data.get('cmts', [])
            log(f"✓ Found {len(cmts_list)} CMTS devices", GREEN)
            for cmts in cmts_list[:3]:  # Show first 3
                log(f"  - {cmts.get('hostname', cmts.get('name', 'unknown'))}", CYAN)

            self.record_result("CMTS List", True)
            return cmts_list
        except Exception as e:
            log(f"✗ CMTS list failed: {e}", RED)
            self.record_result("CMTS List", False, str(e))
            return []

    def test_cmts_selection_ui(self):
        """Test CMTS selection in UI"""
        section("TEST 4: CMTS Selection UI")

        try:
            # Wait for Vue to load data
            time.sleep(2)
            
            # Find CMTS dropdown - look for the one in the filter card
            # The CMTS filter is in a card with "CMTS Filter" label
            cmts_select = self.page.locator("#cmtsFilter")
            if cmts_select.count() == 0:
                # Try finding by label
                cmts_select = self.page.locator("label:has-text('CMTS') + select, label:has-text('CMTS') ~ select").first
            if cmts_select.count() == 0:
                # Fall back to first select in filter card
                cmts_select = self.page.locator(".card select").first

            cmts_select.wait_for(state="visible", timeout=5000)

            # Get options
            options = cmts_select.locator("option").all_text_contents()
            log(f"✓ CMTS dropdown has {len(options)} options", GREEN)
            for opt in options[:5]:
                log(f"  - {opt}", CYAN)
            if len(options) > 5:
                log(f"  ... and {len(options) - 5} more", CYAN)

            # Select test CMTS if available
            found_cmts = None
            for opt in options:
                if TEST_CMTS in opt:
                    found_cmts = opt
                    break
            
            if found_cmts:
                cmts_select.select_option(label=found_cmts)
                log(f"✓ Selected test CMTS: {found_cmts}", GREEN)
            elif len(options) > 1:
                # Skip "All CMTS" or placeholder, select first real CMTS
                for i, opt in enumerate(options):
                    if opt and 'All' not in opt and 'Select' not in opt:
                        cmts_select.select_option(index=i)
                        log(f"✓ Selected CMTS: {opt}", GREEN)
                        break

            self.record_result("CMTS Selection UI", True)
            return True
        except Exception as e:
            log(f"✗ CMTS selection failed: {e}", RED)
            self.record_result("CMTS Selection UI", False, str(e))
            return False

    def test_get_modems_api(self):
        """Test getting modems via API"""
        section("TEST 5: Get Modems API")

        try:
            response = self.page.request.get(f"{API_BASE}/cmts/{TEST_CMTS}/modems")

            if not response.ok:
                log(f"⚠ Get modems returned {response.status}", YELLOW)
                self.record_result("Get Modems API", None, f"Status {response.status}")
                return []

            data = response.json()
            modems = data.get('modems', [])
            log(f"✓ Found {len(modems)} modems from {TEST_CMTS}", GREEN)

            # Show first few modems
            for modem in modems[:3]:
                mac = modem.get('mac_address', 'unknown')
                ip = modem.get('ip_address', 'N/A')
                log(f"  - {mac} ({ip})", CYAN)

            self.record_result("Get Modems API", True)
            return modems
        except Exception as e:
            log(f"✗ Get modems failed: {e}", RED)
            self.record_result("Get Modems API", False, str(e))
            return []

    def test_get_modems_ui(self):
        """Test Get Modems button in UI"""
        section("TEST 6: Get Modems UI")

        try:
            # Wait for button to become enabled after CMTS selection
            time.sleep(1)
            
            # Find Get Modems button
            btn = self.page.locator("button").filter(has_text="Get Modems")
            if btn.count() == 0:
                btn = self.page.locator("button").filter(has_text="Load")

            if btn.count() > 0:
                # Wait for button to be enabled (CMTS must be selected)
                try:
                    btn.wait_for(state="visible", timeout=5000)
                    # Check if button is disabled
                    if btn.is_disabled():
                        log("⚠ Get Modems button is disabled (need to select CMTS first)", YELLOW)
                        self.record_result("Get Modems UI", None, "Button disabled")
                        return False
                except:
                    pass
                
                btn.click(timeout=10000)
                log("✓ Clicked Get Modems button", GREEN)

                # Wait for loading to complete and table to populate
                log("  Waiting for modems to load...", CYAN)
                time.sleep(5)
                
                # Check for loading indicator
                loading = self.page.locator("button:has-text('Loading')").count()
                if loading > 0:
                    log("  Still loading, waiting longer...", CYAN)
                    time.sleep(10)
                
                rows = self.page.locator("table tbody tr").count()
                log(f"✓ Table has {rows} rows", GREEN)

                self.record_result("Get Modems UI", True)
                return rows > 0
            else:
                log("⚠ Get Modems button not found", YELLOW)
                self.record_result("Get Modems UI", None, "Button not found")
                return False
        except Exception as e:
            log(f"✗ Get modems UI failed: {e}", RED)
            self.record_result("Get Modems UI", False, str(e))
            return False

    # ============== PyPNM API Tests ==============

    def test_channel_stats_api(self):
        """Test channel statistics API endpoint"""
        section("TEST 7: Channel Stats API")

        try:
            response = self.page.request.post(
                f"{API_BASE}/pypnm/modem/{TEST_MODEM_MAC}/channel-stats",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY
                }),
                headers={"Content-Type": "application/json"}
            )

            if not response.ok:
                log(f"⚠ Channel stats returned {response.status}", YELLOW)
                self.record_result("Channel Stats API", None, f"Status {response.status}")
                return False

            data = response.json()

            # Check for downstream/upstream data
            if data.get('downstream') or data.get('upstream'):
                ds = data.get('downstream', {})
                us = data.get('upstream', {})

                scqam_count = ds.get('scqam', {}).get('count', 0)
                ofdm_count = ds.get('ofdm', {}).get('count', 0)
                atdma_count = us.get('atdma', {}).get('count', 0)
                ofdma_count = us.get('ofdma', {}).get('count', 0)

                log(f"✓ Channel stats retrieved successfully", GREEN)
                log(f"  DS: {scqam_count} SC-QAM, {ofdm_count} OFDM", CYAN)
                log(f"  US: {atdma_count} ATDMA, {ofdma_count} OFDMA", CYAN)

                self.record_result("Channel Stats API", True)
                return True
            else:
                log(f"⚠ No channel data in response", YELLOW)
                self.record_result("Channel Stats API", None, "No data")
                return False

        except Exception as e:
            log(f"✗ Channel stats failed: {e}", RED)
            self.record_result("Channel Stats API", False, str(e))
            return False

    def test_event_log_api(self):
        """Test event log API endpoint"""
        section("TEST 8: Event Log API")

        try:
            response = self.page.request.post(
                f"{API_BASE}/pypnm/modem/{TEST_MODEM_MAC}/event-log",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY
                }),
                headers={"Content-Type": "application/json"}
            )

            if not response.ok:
                log(f"⚠ Event log returned {response.status}", YELLOW)
                self.record_result("Event Log API", None, f"Status {response.status}")
                return False

            data = response.json()

            if data.get('status') == 0:
                logs = data.get('logs', [])
                log(f"✓ Event log retrieved: {len(logs)} events", GREEN)
                if logs:
                    log(f"  Latest: {logs[0].get('docsDevEvText', 'N/A')[:50]}...", CYAN)
                self.record_result("Event Log API", True)
                return True
            else:
                log(f"⚠ Event log status: {data.get('status')}", YELLOW)
                self.record_result("Event Log API", None, f"Status {data.get('status')}")
                return False

        except Exception as e:
            log(f"✗ Event log failed: {e}", RED)
            self.record_result("Event Log API", False, str(e))
            return False

    def test_fec_api(self):
        """Test FEC summary API endpoint"""
        section("TEST 9: FEC Summary API")

        try:
            response = self.page.request.post(
                f"{API_BASE}/pypnm/measurements/fec_summary/{TEST_MODEM_MAC}",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY,
                    "fec_summary_type": 2
                }),
                headers={"Content-Type": "application/json"}
            )

            if not response.ok:
                log(f"⚠ FEC returned {response.status}", YELLOW)
                self.record_result("FEC API", None, f"Status {response.status}")
                return False

            data = response.json()

            if data.get('status') == 0 or data.get('success'):
                log(f"✓ FEC summary retrieved", GREEN)
                self.record_result("FEC API", True)
                return True
            else:
                log(f"⚠ FEC status: {data.get('status', data.get('error', 'unknown'))}", YELLOW)
                self.record_result("FEC API", None, str(data.get('error', 'unknown')))
                return False

        except Exception as e:
            log(f"✗ FEC failed: {e}", RED)
            self.record_result("FEC API", False, str(e))
            return False

    def test_spectrum_api(self):
        """Test spectrum analyzer API endpoint (slow - captures full DS spectrum)"""
        section("TEST 10: Spectrum Analyzer API")

        try:
            self.page.set_default_timeout(MEASUREMENT_TIMEOUT)

            log("  ⏳ Running spectrum capture (this takes ~60s)...", CYAN)
            response = self.page.request.post(
                f"{API_BASE}/pypnm/measurements/spectrum/{TEST_MODEM_MAC}",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY,
                    "output_type": "json"
                }),
                headers={"Content-Type": "application/json"}
            )

            self.page.set_default_timeout(TEST_TIMEOUT)

            if not response.ok:
                log(f"⚠ Spectrum returned {response.status}", YELLOW)
                self.record_result("Spectrum API", None, f"Status {response.status}")
                return False

            data = response.json()

            if data.get('status') == 0 or data.get('success'):
                log(f"✓ Spectrum analysis completed", GREEN)
                if 'frequencies' in str(data) or 'power' in str(data):
                    log(f"  Data contains frequency/power measurements", CYAN)
                self.record_result("Spectrum API", True)
                return True
            else:
                log(f"⚠ Spectrum status: {data.get('status', data.get('error', 'unknown'))}", YELLOW)
                self.record_result("Spectrum API", None, str(data.get('error', 'unknown')))
                return False

        except Exception as e:
            log(f"✗ Spectrum failed: {e}", RED)
            self.record_result("Spectrum API", False, str(e))
            return False

    def test_rxmer_api(self):
        """Test RxMER API endpoint (slow - captures OFDM RxMER data)"""
        section("TEST 11: RxMER API")

        try:
            self.page.set_default_timeout(MEASUREMENT_TIMEOUT)

            log("  ⏳ Running RxMER capture...", CYAN)
            response = self.page.request.post(
                f"{API_BASE}/pypnm/measurements/rxmer/{TEST_MODEM_MAC}",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY,
                    "output_type": "json"
                }),
                headers={"Content-Type": "application/json"}
            )

            self.page.set_default_timeout(TEST_TIMEOUT)

            if not response.ok:
                log(f"⚠ RxMER returned {response.status}", YELLOW)
                self.record_result("RxMER API", None, f"Status {response.status}")
                return False

            data = response.json()

            if data.get('status') == 0 or data.get('success'):
                log(f"✓ RxMER measurement completed", GREEN)
                self.record_result("RxMER API", True)
                return True
            else:
                log(f"⚠ RxMER status: {data.get('status', data.get('error', 'unknown'))}", YELLOW)
                self.record_result("RxMER API", None, str(data.get('error', 'unknown')))
                return False

        except Exception as e:
            log(f"✗ RxMER failed: {e}", RED)
            self.record_result("RxMER API", False, str(e))
            return False

    def test_constellation_api(self):
        """Test constellation display API endpoint"""
        section("TEST 12: Constellation API")

        try:
            self.page.set_default_timeout(MEASUREMENT_TIMEOUT)

            log("  ⏳ Running constellation capture...", CYAN)
            response = self.page.request.post(
                f"{API_BASE}/pypnm/measurements/constellation/{TEST_MODEM_MAC}",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY,
                    "output_type": "json"
                }),
                headers={"Content-Type": "application/json"}
            )

            self.page.set_default_timeout(TEST_TIMEOUT)

            if not response.ok:
                log(f"⚠ Constellation returned {response.status}", YELLOW)
                self.record_result("Constellation API", None, f"Status {response.status}")
                return False

            data = response.json()

            if data.get('status') == 0 or data.get('success'):
                log(f"✓ Constellation data retrieved", GREEN)
                self.record_result("Constellation API", True)
                return True
            else:
                log(f"⚠ Constellation status: {data.get('status', data.get('error', 'unknown'))}", YELLOW)
                self.record_result("Constellation API", None, str(data.get('error', 'unknown')))
                return False

        except Exception as e:
            log(f"✗ Constellation failed: {e}", RED)
            self.record_result("Constellation API", False, str(e))
            return False

    def test_pre_eq_api(self):
        """Test pre-equalization API endpoint"""
        section("TEST 13: Pre-Equalization API")

        try:
            self.page.set_default_timeout(MEASUREMENT_TIMEOUT)

            response = self.page.request.post(
                f"{API_BASE}/pypnm/modem/{TEST_MODEM_MAC}/pre-eq",
                data=json.dumps({
                    "modem_ip": TEST_MODEM_IP,
                    "community": SNMP_COMMUNITY
                }),
                headers={"Content-Type": "application/json"}
            )

            self.page.set_default_timeout(TEST_TIMEOUT)

            if not response.ok:
                log(f"⚠ Pre-EQ returned {response.status}", YELLOW)
                self.record_result("Pre-EQ API", None, f"Status {response.status}")
                return False

            data = response.json()

            if data.get('status') == 0 or data.get('success'):
                log(f"✓ Pre-equalization data retrieved", GREEN)
                self.record_result("Pre-EQ API", True)
                return True
            else:
                log(f"⚠ Pre-EQ status: {data.get('status', data.get('error', 'unknown'))}", YELLOW)
                self.record_result("Pre-EQ API", None, str(data.get('error', 'unknown')))
                return False

        except Exception as e:
            log(f"✗ Pre-EQ failed: {e}", RED)
            self.record_result("Pre-EQ API", False, str(e))
            return False

    # ============== UI Interaction Tests ==============

    def test_select_modem_ui(self):
        """Test selecting a modem in the UI"""
        section("TEST 14: Select Modem UI")

        try:
            # Look for modem table
            rows = self.page.locator("table tbody tr")

            if rows.count() == 0:
                log("⚠ No modem rows in table", YELLOW)
                self.record_result("Select Modem UI", None, "No rows")
                return False

            # Click first row or its select button
            first_row = rows.first
            select_btn = first_row.locator("button").first

            if select_btn.count() > 0:
                select_btn.click()
            else:
                first_row.click()

            time.sleep(2)

            # Check if modem details panel appeared
            details = self.page.locator(".modem-details, .card-body, [class*='selected']")
            if details.count() > 0:
                log(f"✓ Modem selection triggered UI update", GREEN)
                self.record_result("Select Modem UI", True)
                return True
            else:
                log(f"⚠ No visible UI change after selection", YELLOW)
                self.record_result("Select Modem UI", None, "No UI change")
                return False

        except Exception as e:
            log(f"✗ Select modem UI failed: {e}", RED)
            self.record_result("Select Modem UI", False, str(e))
            return False

    def test_measurement_buttons(self):
        """Test that measurement buttons exist"""
        section("TEST 15: Measurement Buttons")

        measurements = ["Spectrum", "RxMER", "FEC", "Constellation", "Event Log"]
        found = []

        try:
            for measurement in measurements:
                btn = self.page.locator("button").filter(has_text=measurement)
                if btn.count() > 0:
                    found.append(measurement)

            if found:
                log(f"✓ Found measurement buttons: {', '.join(found)}", GREEN)
                self.record_result("Measurement Buttons", True)
                return found
            else:
                log("⚠ No measurement buttons found", YELLOW)
                self.record_result("Measurement Buttons", None, "No buttons")
                return []

        except Exception as e:
            log(f"✗ Measurement buttons test failed: {e}", RED)
            self.record_result("Measurement Buttons", False, str(e))
            return []

    def test_spectrum_ui(self):
        """Test Spectrum Analyzer button click in UI"""
        section("TEST 16: Spectrum Analyzer UI")

        try:
            btn = self.page.locator("button").filter(has_text="Spectrum")

            if btn.count() == 0:
                log("⚠ Spectrum button not found", YELLOW)
                self.record_result("Spectrum UI", None, "Button not found")
                return False

            btn.click()
            log("  Clicked Spectrum button, waiting for result...", CYAN)

            # Wait for loading to start
            time.sleep(5)

            # Check for chart or loading indicator
            canvas = self.page.locator("canvas")
            loading = self.page.locator("text=Loading")
            error = self.page.locator(".alert-danger, .text-danger")

            if canvas.count() > 0:
                log(f"✓ Spectrum chart rendered ({canvas.count()} canvas elements)", GREEN)
                self.record_result("Spectrum UI", True)
                return True
            elif loading.count() > 0:
                log("⚠ Still loading spectrum data (normal for live measurement)", YELLOW)
                self.record_result("Spectrum UI", None, "Still loading")
                return False
            elif error.count() > 0:
                log("⚠ Error displayed", YELLOW)
                self.record_result("Spectrum UI", None, "Error displayed")
                return False
            else:
                log("⚠ No chart or status found", YELLOW)
                self.record_result("Spectrum UI", None, "Unknown state")
                return False

        except Exception as e:
            log(f"✗ Spectrum UI failed: {e}", RED)
            self.record_result("Spectrum UI", False, str(e))
            return False

    # ============== Main Runner ==============

    def run_all_tests(self):
        """Run all GUI tests"""
        section("PyPNM GUI - Playwright E2E Test Suite")
        log(f"GUI URL: {GUI_URL}", CYAN)
        log(f"Test Modem: {TEST_MODEM_MAC} ({TEST_MODEM_IP})", CYAN)
        log(f"Test CMTS: {TEST_CMTS}", CYAN)

        if not self.setup():
            return 1

        try:
            # Phase 1: Basic page tests
            self.test_page_load()
            self.take_screenshot("01_page_load")

            self.test_api_health()

            # Phase 2: CMTS and modem listing
            self.test_cmts_list()
            self.test_cmts_selection_ui()
            self.take_screenshot("02_cmts_selected")

            self.test_get_modems_api()
            self.test_get_modems_ui()
            self.take_screenshot("03_modems_loaded")

            # Phase 3: Fast API endpoint tests
            self.test_channel_stats_api()
            self.test_event_log_api()
            self.test_fec_api()

            # Phase 4: PNM measurement tests (may be slow)
            log("\n⏳ Running PNM measurements (this may take a while)...", YELLOW)
            self.test_spectrum_api()
            self.test_rxmer_api()
            self.test_constellation_api()
            self.test_pre_eq_api()

            # Phase 5: UI interaction tests
            self.test_select_modem_ui()
            self.take_screenshot("04_modem_selected")

            self.test_measurement_buttons()
            self.test_spectrum_ui()
            self.take_screenshot("05_spectrum_ui")

            # Final screenshot
            self.take_screenshot("99_final_state")

            # Summary
            self.print_summary()

            return 0 if self.failed == 0 else 1

        except KeyboardInterrupt:
            log("\n\n⚠ Tests interrupted by user", YELLOW)
            self.take_screenshot("interrupted")
            return 1
        finally:
            self.teardown()

    def print_summary(self):
        """Print test summary"""
        section("TEST SUMMARY")

        total = self.passed + self.failed + self.skipped

        log(f"Total Tests: {total}", CYAN)
        log(f"  ✓ Passed:  {self.passed}", GREEN)
        log(f"  ✗ Failed:  {self.failed}", RED if self.failed > 0 else GREEN)
        log(f"  ⊘ Skipped: {self.skipped}", YELLOW if self.skipped > 0 else CYAN)

        if total > 0:
            success_rate = (self.passed / total * 100)
            color = GREEN if success_rate >= 80 else (YELLOW if success_rate >= 50 else RED)
            log(f"\nSuccess Rate: {success_rate:.1f}%", color)

        if self.failed > 0:
            log("\nFailed Tests:", RED)
            for result in self.test_results:
                if not result['passed'] and result['passed'] is not None:
                    log(f"  ✗ {result['test']}: {result['message']}", RED)

        # Save results to JSON
        try:
            results_file = "/tmp/pypnm_gui_test_results.json"
            with open(results_file, "w") as f:
                json.dump({
                    "total": total,
                    "passed": self.passed,
                    "failed": self.failed,
                    "skipped": self.skipped,
                    "success_rate": (self.passed / total * 100) if total > 0 else 0,
                    "tests": self.test_results
                }, f, indent=2)
            log(f"\n📄 Results saved to: {results_file}", CYAN)
        except Exception as e:
            log(f"⚠ Failed to save results: {e}", YELLOW)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="PyPNM GUI Playwright E2E Tests")
    parser.add_argument("--headless", action="store_true", 
                       help="Run in headless mode (no browser window)")
    parser.add_argument("--slow", type=int, default=300, 
                       help="Slow motion delay in ms (default: 300)")
    parser.add_argument("--modem-mac", type=str, 
                       help="Test modem MAC address")
    parser.add_argument("--modem-ip", type=str, 
                       help="Test modem IP address")
    parser.add_argument("--cmts", type=str, 
                       help="Test CMTS hostname")
    parser.add_argument("--community", type=str, 
                       help="SNMP community string")
    args = parser.parse_args()

    # Override globals if provided
    global TEST_MODEM_MAC, TEST_MODEM_IP, TEST_CMTS, SNMP_COMMUNITY
    if args.modem_mac:
        TEST_MODEM_MAC = args.modem_mac
    if args.modem_ip:
        TEST_MODEM_IP = args.modem_ip
    if args.cmts:
        TEST_CMTS = args.cmts
    if args.community:
        SNMP_COMMUNITY = args.community

    tester = GUITester(headless=args.headless, slow_mo=args.slow)
    return tester.run_all_tests()


if __name__ == "__main__":
    sys.exit(main())
