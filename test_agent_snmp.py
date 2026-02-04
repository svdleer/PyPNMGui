#!/usr/bin/env python3
"""
Simple Test: Verify Agent Handles SNMP
Select CMTS mnd-gt0002-ccap002 -> Click Get Modems
"""
import asyncio
from playwright.async_api import async_playwright

async def test():
    print("\n=== PyPNM Agent SNMP Test ===\n")
    
    async with async_playwright() as p:
        # Launch browser (visible)
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # 1. Load GUI
        print("1. Loading http://localhost:5050...")
        await page.goto("http://localhost:5050", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        print("   ✓ GUI loaded")
        
        # 2. Select CMTS
        print("\n2. Selecting CMTS: mnd-gt0002-ccap002...")
        await page.select_option("select#cmts-select", label="mnd-gt0002-ccap002")
        await page.wait_for_timeout(1000)
        print("   ✓ CMTS selected")
        
        # 3. Click Get Modems
        print("\n3. Clicking 'Get Modems' button...")
        await page.click("button:has-text('Get Modems')")
        print("   ✓ Button clicked")
        
        # 4. Wait and watch for results
        print("\n4. Waiting for results (20 seconds)...")
        print("   Watch agent logs to see SNMP activity!")
        await page.wait_for_timeout(20000)
        
        # 5. Check if modems loaded
        modem_rows = await page.query_selector_all("table tbody tr")
        print(f"\n5. Results: Found {len(modem_rows)} modem rows")
        
        if len(modem_rows) > 0:
            print("   ✓ SUCCESS - Modems loaded via agent!")
        else:
            print("   ⚠ No modems found (check agent logs)")
        
        # Take screenshot
        await page.screenshot(path="/tmp/agent_test.png")
        print("\n📸 Screenshot: /tmp/agent_test.png")
        
        # Keep browser open
        print("\n✓ Test complete! Press Enter to close browser...")
        input()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
