#!/usr/bin/env python3
"""
Automated UTSC Live test using Selenium
"""
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# Configuration
URL = "http://localhost:5051"
TEST_MAC = "e4:57:40:0b:db:b9"  # Replace with actual modem MAC

def setup_driver():
    """Setup Chrome driver with headless mode"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=options)
    return driver

def wait_for_element(driver, by, value, timeout=10):
    """Wait for element to be present"""
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )

def get_console_logs(driver):
    """Get browser console logs"""
    logs = driver.get_log('browser')
    return [log for log in logs if log['level'] in ['INFO', 'WARNING', 'SEVERE']]

def test_utsc_live():
    """Test UTSC Live functionality"""
    driver = None
    try:
        print(f"[{time.strftime('%H:%M:%S')}] Starting automated UTSC Live test...")
        
        driver = setup_driver()
        driver.set_window_size(1920, 1080)
        
        # Enable browser console logging
        driver.execute_cdp_cmd('Log.enable', {})
        
        print(f"[{time.strftime('%H:%M:%S')}] Loading page: {URL}")
        driver.get(URL)
        
        # Wait for page load
        time.sleep(2)
        
        print(f"[{time.strftime('%H:%M:%S')}] Switching to Modems view...")
        modems_link = wait_for_element(driver, By.XPATH, "//a[contains(text(), 'Modems')]")
        modems_link.click()
        time.sleep(1)
        
        print(f"[{time.strftime('%H:%M:%S')}] Selecting modem: {TEST_MAC}...")
        # Click modem row (assuming it has the MAC address)
        modem_row = wait_for_element(driver, By.XPATH, f"//td[contains(text(), '{TEST_MAC}')]/parent::tr")
        modem_row.click()
        time.sleep(2)
        
        print(f"[{time.strftime('%H:%M:%S')}] Switching to Measurements view...")
        measurements_link = wait_for_element(driver, By.XPATH, "//a[contains(text(), 'Measurements')]")
        measurements_link.click()
        time.sleep(1)
        
        print(f"[{time.strftime('%H:%M:%S')}] Clicking 'Start UTSC Live' button...")
        start_button = wait_for_element(driver, By.XPATH, "//button[contains(text(), 'Start UTSC Live')]")
        start_button.click()
        
        # Wait and monitor for 30 seconds
        print(f"[{time.strftime('%H:%M:%S')}] Monitoring for 30 seconds...")
        start_time = time.time()
        last_buffer_msg = None
        
        while time.time() - start_time < 30:
            # Check console logs for buffering messages
            logs = get_console_logs(driver)
            for log in logs:
                msg = log.get('message', '')
                if 'Buffering' in msg and msg != last_buffer_msg:
                    print(f"[{time.strftime('%H:%M:%S')}] Console: {msg}")
                    last_buffer_msg = msg
                elif '[UTSC]' in msg:
                    print(f"[{time.strftime('%H:%M:%S')}] Console: {msg}")
            
            # Check if chart is visible
            try:
                chart = driver.find_element(By.ID, "utscLiveChart")
                if chart.is_displayed():
                    print(f"[{time.strftime('%H:%M:%S')}] ✅ Chart is visible!")
                    return True
            except:
                pass
            
            time.sleep(2)
        
        print(f"[{time.strftime('%H:%M:%S')}] ❌ FAILED: No chart appeared after 30 seconds")
        print(f"[{time.strftime('%H:%M:%S')}] Final console logs:")
        logs = get_console_logs(driver)
        for log in logs[-20:]:  # Last 20 logs
            print(f"  {log.get('message', '')}")
        
        return False
        
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    success = test_utsc_live()
    exit(0 if success else 1)
