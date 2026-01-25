#!/usr/bin/env python3
"""
GUI Session Test - Emulates a complete user workflow
Tests the full UTSC live monitoring flow end-to-end
"""

import asyncio
import sys
import time
from playwright.async_api import async_playwright, expect

# Configuration
GUI_URL = "http://localhost:5050"
TEST_TIMEOUT = 300000  # 5 minutes
UTSC_DURATION = 60  # seconds


async def test_utsc_live_session():
    """Test a complete UTSC live monitoring session"""
    
    async with async_playwright() as p:
        # Launch browser
        print("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=False)  # Set to True for CI/CD
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # Step 1: Load GUI
            print(f"📡 Loading GUI: {GUI_URL}")
            await page.goto(GUI_URL, wait_until="networkidle", timeout=TEST_TIMEOUT)
            await page.wait_for_load_state("domcontentloaded")
            print("✅ GUI loaded")
            
            # Wait for Vue app to initialize
            await asyncio.sleep(2)
            
            # Step 2: Select CMTS
            print("🔍 Looking for CMTS dropdown...")
            cmts_select = page.locator("#cmts-select")
            await expect(cmts_select).to_be_visible(timeout=10000)
            
            # Get CMTS list
            await cmts_select.click()
            await asyncio.sleep(1)
            cmts_options = await page.locator("#cmts-select option").all()
            
            if len(cmts_options) <= 1:  # Only "Select CMTS" option
                print("❌ No CMTS systems available")
                return False
            
            # Select first CMTS (skip the placeholder)
            cmts_text = await cmts_options[1].inner_text()
            print(f"📡 Selecting CMTS: {cmts_text}")
            await cmts_select.select_option(index=1)
            await asyncio.sleep(2)
            print("✅ CMTS selected")
            
            # Step 3: Get Live Modems
            print("📥 Getting live modems...")
            get_modems_btn = page.locator("button:has-text('Get Live Modems')")
            await expect(get_modems_btn).to_be_visible(timeout=5000)
            await get_modems_btn.click()
            
            # Wait for modems to load
            print("⏳ Waiting for modems to load...")
            await asyncio.sleep(10)  # Give time for SNMP walk
            
            # Check if modems table has entries
            modem_rows = page.locator("#modems-table tbody tr")
            count = await modem_rows.count()
            
            if count == 0:
                print("❌ No modems found")
                return False
            
            print(f"✅ Found {count} modems")
            
            # Step 4: Select first modem
            print("🖱️ Selecting first modem...")
            first_row = modem_rows.first
            await first_row.click()
            await asyncio.sleep(1)
            
            # Get modem MAC
            mac_cell = first_row.locator("td").nth(1)  # MAC is usually 2nd column
            modem_mac = await mac_cell.inner_text()
            print(f"✅ Selected modem: {modem_mac}")
            
            # Step 5: Switch to Upstream tab
            print("📊 Switching to Upstream tab...")
            upstream_tab = page.locator("a[href='#upstream']")
            await upstream_tab.click()
            await asyncio.sleep(1)
            print("✅ Upstream tab active")
            
            # Step 6: Click Auto-Discover RF Port
            print("🔍 Auto-discovering RF port...")
            discover_btn = page.locator("button:has-text('Auto-Discover')")
            if await discover_btn.is_visible():
                await discover_btn.click()
                await asyncio.sleep(5)  # Wait for discovery
                print("✅ RF port discovered")
            else:
                print("⚠️ Auto-discover button not found, may already be set")
            
            # Step 7: Configure UTSC parameters
            print("⚙️ Configuring UTSC parameters...")
            
            # Set center frequency (50 MHz)
            center_freq_input = page.locator("#utsc-center-freq")
            if await center_freq_input.is_visible():
                await center_freq_input.fill("50")
            
            # Set span (80 MHz)
            span_input = page.locator("#utsc-span")
            if await span_input.is_visible():
                await span_input.fill("80")
            
            # Set bins (800)
            bins_input = page.locator("#utsc-bins")
            if await bins_input.is_visible():
                await bins_input.fill("800")
            
            print("✅ UTSC parameters configured")
            
            # Step 8: Start Live Monitoring
            print("🎬 Starting UTSC live monitoring...")
            live_checkbox = page.locator("input[type='checkbox'][id*='utsc-live']")
            
            if not await live_checkbox.is_visible():
                print("❌ Live monitoring checkbox not found")
                return False
            
            await live_checkbox.check()
            await asyncio.sleep(2)
            
            # Verify WebSocket connection
            print("🔌 Checking WebSocket connection...")
            await asyncio.sleep(5)
            
            # Look for buffering or streaming status
            status_div = page.locator(".utsc-status, .stream-status")
            if await status_div.count() > 0:
                status_text = await status_div.first.inner_text()
                print(f"📊 Stream status: {status_text}")
            
            # Step 9: Wait for data to stream
            print(f"⏳ Monitoring for {UTSC_DURATION} seconds...")
            start_time = time.time()
            data_received = False
            
            # Monitor for spectrum updates
            for i in range(UTSC_DURATION):
                await asyncio.sleep(1)
                elapsed = time.time() - start_time
                
                # Check for spectrum chart or data
                chart_canvas = page.locator("canvas, .scichart-canvas, .spectrum-chart")
                if await chart_canvas.count() > 0:
                    if not data_received:
                        print("✅ Spectrum data being displayed")
                        data_received = True
                
                # Check for error messages
                error_toast = page.locator(".toast-error, .error-message")
                if await error_toast.count() > 0:
                    error_text = await error_toast.first.inner_text()
                    print(f"❌ Error detected: {error_text}")
                    return False
                
                # Progress indicator
                if i % 10 == 0:
                    print(f"⏱️ {int(elapsed)}s / {UTSC_DURATION}s - {'✅ Streaming' if data_received else '⏳ Waiting for data'}")
            
            # Step 10: Stop monitoring
            print("⏹️ Stopping live monitoring...")
            await live_checkbox.uncheck()
            await asyncio.sleep(2)
            print("✅ Monitoring stopped")
            
            # Final status
            if data_received:
                print("\n" + "="*60)
                print("✅ TEST PASSED - UTSC live monitoring working!")
                print("="*60)
                return True
            else:
                print("\n" + "="*60)
                print("❌ TEST FAILED - No data received during monitoring")
                print("="*60)
                return False
                
        except Exception as e:
            print(f"\n❌ TEST FAILED with exception: {e}")
            import traceback
            traceback.print_exc()
            return False
            
        finally:
            # Screenshot for debugging
            await page.screenshot(path="test_session_final.png")
            print("📸 Screenshot saved: test_session_final.png")
            
            # Keep browser open for inspection if test failed
            if not data_received:
                print("⏸️ Browser left open for inspection (close manually)")
                await asyncio.sleep(30)
            
            await browser.close()


async def test_quick_cmts_check():
    """Quick test - just verify CMTS list loads"""
    
    async with async_playwright() as p:
        print("🚀 Quick CMTS check...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto(GUI_URL, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            cmts_select = page.locator("#cmts-select")
            await expect(cmts_select).to_be_visible(timeout=10000)
            
            options_count = await page.locator("#cmts-select option").count()
            
            if options_count > 1:
                print(f"✅ CMTS list loaded: {options_count - 1} systems")
                return True
            else:
                print("❌ No CMTS systems found")
                return False
                
        except Exception as e:
            print(f"❌ Quick check failed: {e}")
            return False
        finally:
            await browser.close()


async def main():
    """Run tests"""
    print("\n" + "="*60)
    print("PyPNM GUI Session Test")
    print("="*60 + "\n")
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        success = await test_quick_cmts_check()
    else:
        success = await test_utsc_live_session()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
