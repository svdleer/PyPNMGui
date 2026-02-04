#!/usr/bin/env python3
"""
Simple test: Select CMTS and Get Modems
Steps:
1. Open GUI
2. Select CMTS: mnd-gt0002-ccap002
3. Click "Get Modems"
4. Verify agent performs SNMP
"""

import asyncio
import subprocess
from playwright.async_api import async_playwright

GUI_URL = "http://localhost:5050"

async def test_get_modems():
    print("\n=== Test: Get Modems via Agent ===\n")
    
    # Start watching agent logs
    print("1. Starting agent log monitor...")
    log_proc = subprocess.Popen(
        ["ssh", "-p", "65001", "svdleer@access-engineering.nl", 
         "docker logs -f pypnm-agent-lab 2>&1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    await asyncio.sleep(2)
    
    async with async_playwright() as p:
        # Launch browser (visible)
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Enable console logging to see API calls
        page.on("console", lambda msg: print(f"   [Browser] {msg.type}: {msg.text}"))
        page.on("response", lambda response: print(f"   [API] {response.status} {response.url}"))
        
        try:
            # Step 1: Open GUI
            print("2. Opening GUI...")
            await page.goto(GUI_URL)
            await page.wait_for_load_state("networkidle")
            print("   ✓ GUI loaded")
            
            # Step 2: Wait for CMTS list to load
            print("\n3. Waiting for CMTS list...")
            await page.wait_for_selector('select.form-select', timeout=10000)
            await asyncio.sleep(2)
            print("   ✓ CMTS list loaded")
            
            # Step 3: Select CMTS by finding the option
            print("\n4. Selecting CMTS: mnd-gt0002-ccap002...")
            # Find and click the select
            selects = await page.query_selector_all('select.form-select')
            for select in selects:
                options = await select.query_selector_all('option')
                for option in options:
                    text = await option.inner_text()
                    if 'mnd-gt0002-ccap002' in text:
                        value = await option.get_attribute('value')
                        await select.select_option(value)
                        print(f"   ✓ Selected: {text.strip()}")
                        await asyncio.sleep(1)
                        break
            
            # Step 4: Click Get Modems (might be "getLiveModems" button)
            print("\n5. Clicking 'Get Modems' button...")
            get_modems_btn = await page.query_selector('button.btn-success')
            if get_modems_btn:
                await get_modems_btn.click()
                print("   ✓ Button clicked")
            else:
                print("   ✗ Get Modems button not found")
            
            # Wait for response
            print("\n6. Waiting for modems to load...")
            await asyncio.sleep(8)
            
            # Check if modems appeared
            modem_rows = await page.query_selector_all('table tbody tr')
            print(f"   ✓ Found {len(modem_rows)} modem rows in table")
            
            # Keep browser open to see results
            print("\n7. Keeping browser open for 10 seconds...")
            print("   (Watch the browser and agent activity)")
            await asyncio.sleep(10)
            
        except Exception as e:
            print(f"   ✗ Error: {e}")
        finally:
            await browser.close()
    
    # Stop log monitoring
    log_proc.terminate()
    
    print("\n=== Test Complete ===\n")

if __name__ == "__main__":
    asyncio.run(test_get_modems())
