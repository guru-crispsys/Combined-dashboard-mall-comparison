import json
import os
import time
import requests
import numpy as np
from seleniumwire.undetected_chromedriver import Chrome, ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configuration
OUTPUT_FILE = os.path.join(os.path.expanduser("~"), "Downloads", "tenants_detailed.json")
CHROME_PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")

def get_fresh_options(headless=True):
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    
    # ADVANCED STEALTH FLAGS
    # Note: undetected_chromedriver handles many of these internally.
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # Hide that we are using a proxy (common trigger for PerimeterX)
    options.add_argument("--proxy-server='direct://'")
    options.add_argument("--proxy-bypass-list=*")
    return options

def create_driver(headless=True):
    os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)

    # Selenium-wire specific setup to bypass proxy detection
    sw_options = {
        'verify_ssl': False, # Avoid cert strikes seen in screenshot
        'connection_timeout': None,
        'request_storage': 'memory'
    }

    try:
        # Explicitly request version 144 to match system browser
        print(f"Starting Chrome (Version 144, Headless={headless})...", flush=True)
        driver = Chrome(options=get_fresh_options(headless=headless), seleniumwire_options=sw_options, version_main=144)
    except Exception as e:
        print(f"Initial Driver Init Failed: {e}. Retrying with auto-detection fallback...")
        try:
            # Re-creating options is mandatory to avoid "RuntimeError"
            driver = Chrome(options=get_fresh_options(headless=headless), seleniumwire_options=sw_options)
        except Exception as e2:
            print(f"Fatal: Could not initialize driver: {e2}")
            return None
    
    # Hide automation signatures
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"}
        )
    except: pass

    return driver

def solve_affine(pts):
    """
    Solves for affine transform coefficients (a*x + b*y + c = target)
    using 3 control points (Cramer's Rule for 3x3 system).
    """
    x = [p['control']['x'] for p in pts]
    y = [p['control']['y'] for p in pts]
    lat = [p['target']['x'] for p in pts]
    lon = [p['target']['y'] for p in pts]

    def get_coeffs(targets):
        # Matrix: [x1 y1 1], [x2 y2 1], [x3 y3 1]
        det = (x[0] * (y[1] - y[2]) - y[0] * (x[1] - x[2]) + (x[1] * y[2] - x[2] * y[1]))
        if abs(det) < 1e-10: return [0, 0, 0]
        
        a = ((y[1] - y[2]) * targets[0] - (y[0] - y[2]) * targets[1] + (y[0] - y[1]) * targets[2]) / det
        b = (-(x[1] - x[2]) * targets[0] + (x[0] - x[2]) * targets[1] - (x[0] - x[1]) * targets[2]) / det
        c = ((x[1] * y[2] - x[2] * y[1]) * targets[0] - (x[0] * y[2] - x[2] * y[0]) * targets[1] + (x[0] * y[1] - x[1] * y[0]) * targets[2]) / det
        return a, b, c

    a, b, c = get_coeffs(lat)
    d, e, f = get_coeffs(lon)
    return (a, b, c), (d, e, f)

def scrape_brookefields(url):
    """
    Scraper for Brookefields.com: Extracting store data from JS variables and shop list.
    """
    import re
    print(f"Initializing Brookefields Scraper for: {url}", flush=True)
    
    floors = [
        "Lower-Ground-Floor",
        "Ground-Floor",
        "First-Floor",
        "Second-Floor",
        "Third-Floor",
        "Fourth-Floor"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    all_tenants = []
    shop_details = {}

    print("Fetching global shop list for details...", flush=True)
    try:
        r_shops = requests.get("https://brookefields.com/shops", headers=headers, timeout=15)
        # Extract name, shop number and phone
        matches = re.finditer(r'<h4>(.*?)</h4>.*?<p>Shop No: (.*?)</p>.*?<p>Phone: (.*?)</p>', r_shops.text, re.S)
        for m in matches:
            name = m.group(1).strip()
            shop_no = m.group(2).strip()
            phone = m.group(3).strip()
            shop_details[name.lower()] = {"shop_no": shop_no, "phone": phone}
    except Exception as e:
        print(f"Minor: Could not fetch details from /shops: {e}")

    for floor in floors:
        floor_url = f"https://brookefields.com/mall-locator/{floor}"
        print(f"Processing {floor}...", flush=True)
        try:
            r = requests.get(floor_url, headers=headers, timeout=15)
            # Extract the store mapping from the JS variable
            m = re.search(r'var arrStore = (\{.*?\});', r.text)
            if m:
                floor_data = json.loads(m.group(1))
                for store_id, info in floor_data.items():
                    name = info.get('name', 'Unknown')
                    top = info.get('top', '0')
                    left = info.get('left', '0')
                    
                    lat = float(top) if top != "0" else None
                    lon = float(left) if left != "0" else None
                    
                    details = shop_details.get(name.lower(), {})
                    desc = f"Shop No: {details.get('shop_no', 'N/A')} | Phone: {details.get('phone', 'N/A')}"
                    
                    all_tenants.append({
                        "name": name,
                        "description": desc,
                        "location_id": f"bf-{store_id}",
                        "floor": floor.replace("-", " "),
                        "hours": "10:00 AM - 11:00 PM", # Mall standard
                        "latitude": lat,
                        "longitude": lon,
                    })
        except Exception as e:
            print(f"Error on floor {floor}: {e}")
            
    return all_tenants

def prepare_map_state(driver):
    """
    Helper to handle cookies, overlays, and ensure the Map tab is active.
    Shared by both Vision and Generic scrapers.
    """
    print("Preparing Map View (Cookies & Tabs)...", flush=True)
    
    # 1. DISMISS COOKIES / OVERLAYS (Aggressive & Multilingual)
    print("  > Checking for cookie banners...", flush=True)
    time.sleep(2) # Wait for banners to animate in
    
    # Common words for "Accept", "Allow", "Agree", "OK" in EN, DA, DE, ES, FR
    accept_keywords = [
        "accept", "agree", "allow", "permit", "consent", "okay", "got it",
        "accepter", "godkend", "tillad", "forstået", # Danish
        "akzeptieren", "zustimmen", "verstanden",    # German
        "aceptar", "permitir", "entendido",          # Spanish
        "autoriser", "oui"                           # French
    ]
    
    # Construct lower-case translation logic for XPath 1.0 (Selenium)
    # translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
    limit_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lower_chars = "abcdefghijklmnopqrstuvwxyz"
    
    xpath_conditions = []
    for kw in accept_keywords:
        # Match text content or aria-label
        xpath_conditions.append(f"contains(translate(text(), '{limit_chars}', '{lower_chars}'), '{kw}')")
        xpath_conditions.append(f"contains(translate(@aria-label, '{limit_chars}', '{lower_chars}'), '{kw}')")
    
    # Combine into one massive OR query for efficiency (or chunk it if too long)
    # We'll split into Button-like elements
    tags = ["button", "a", "div[@role='button']"]
    
    for tag in tags:
        for kw in accept_keywords:
            # We iterate keywords to keep XPaths manageable / debuggable
            xpath = f"//{tag}[contains(translate(text(), '{limit_chars}', '{lower_chars}'), '{kw}')]"
            
            # Refine: Ignore if text is too long (likely an article, not a button)
            # XPath 1.0 doesn't have string-length in generic predicate easily mixed, so we filter in Python
            try:
                elems = driver.find_elements(By.XPATH, xpath)
                for elem in elems:
                    if not elem.is_displayed(): continue
                    
                    # Filter out non-buttons (long text)
                    if len(elem.text.strip()) > 40: continue
                    
                    # Check dimensions - cookie buttons are usually somewhat substantial but not huge
                    size = elem.size
                    if size['width'] < 10 or size['height'] < 10: continue
                    
                    print(f"  > Found cookie candidate ({tag}): '{elem.text[:20]}...'", flush=True)
                    try:
                        # Try standard click
                        elem.click()
                    except:
                        # Try JS click
                        driver.execute_script("arguments[0].click();", elem)
                    time.sleep(1)
            except: pass

    # Specific ID/Class Fallbacks for common CMPs
    specific_selectors = [
        "//button[@id='onetrust-accept-btn-handler']",
        "//*[@id='CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll']",
        "//*[@class='cc-btn cc-dismiss']",
        "//*[@class='cc-btn cc-allow']",
        "//button[contains(@class, 'cookie') and contains(@class, 'accept')]",
        "//div[contains(@class, 'cookie')]//button",
        "//*[@class='close']",
        "//button[@aria-label='Close']"
    ]
    
    for sel in specific_selectors:
        try:
            elems = driver.find_elements(By.XPATH, sel)
            for elem in elems:
                if elem.is_displayed():
                    print(f"  > Dismissing overlay via selector: {sel}", flush=True)
                    driver.execute_script("arguments[0].click();", elem)
                    time.sleep(1)
        except: pass

    # 2. SWITCH TO MAP TAB (if not already there)
    # We look for "Overview map", "Map", "Floor Plan", etc.
    map_keywords = [
        "Overview map", 
        "Oversigtskort", 
        "Kort over centret", 
        "View Map", 
        "Interactive Map",
        "Map View",
        "Floor Map",
        "Directory",
        "Map"
    ]
    
    # Check if we are already on a map page (URL check)
    # But sometimes the URL doesn't change much, or we are on the page but need to click a tab.
    
    found_tab = False
    for keyword in map_keywords:
        xpath = f"//*[contains(text(), '{keyword}')]"
        try:
            elems = driver.find_elements(By.XPATH, xpath)
            for elem in elems:
                if elem.is_displayed():
                    # Filter out noise (e.g. footers)
                    if len(elem.text.strip()) > 30: continue
                    
                    tag = elem.tag_name.lower()
                    try:
                        parent = elem.find_element(By.XPATH, "..")
                        parent_tag = parent.tag_name.lower()
                    except: parent_tag = ""
                    
                    if tag in ['a', 'button', 'li', 'span', 'div'] or parent_tag in ['a', 'button', 'li']:
                        print(f"Switching to map tab: '{keyword}'", flush=True)
                        try:
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", elem)
                        except:
                            elem.click()
                        time.sleep(5) # Wait for map render
                        found_tab = True
                        break
        except: pass
        if found_tab: break
    
    # 3. Last Resort: Link with href='.../map'
    if not found_tab:
        try:
             btns = driver.find_elements(By.XPATH, "//a[contains(@href, '/map')]")
             for btn in btns:
                 if btn.is_displayed():
                     print(f"Found map link by href: {btn.get_attribute('href')}")
                     driver.execute_script("arguments[0].click();", btn)
                     time.sleep(5)
                     break
        except: pass



# --- VISION-BASED SCRAPER ---
def scrape_mall_with_vision(url):
    """
    Captures a screenshot of the mall map and extracts tenant data using Vision LLM.
    """
    print(f"Initializing Vision-Based Scraper for: {url}", flush=True)
    driver = create_driver(headless=True)
    if not driver:
        print("Error: Webdriver failed to initialize.")
        return None

    try:
        print(f"Navigating to target for vision capture...", flush=True)
        driver.get(url)
        time.sleep(12) # generous wait for map render
        
        # Robust Map Preparation (Cookies & Tabs)
        prepare_map_state(driver)

        # Take full window screenshot
        screenshot_path = os.path.join(os.getcwd(), "map_capture_temp.png")
        driver.save_screenshot(screenshot_path)
        print(f"Screenshot captured: {screenshot_path}", flush=True)
        
        # Dynamic import to avoid circular dependencies
        import sys
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if root_dir not in sys.path:
            sys.path.append(root_dir)
        
        from Mall_Ai_Dashboard.llm_engine import extract_shops_from_image_via_llm
        
        print("Analyzing map image with AI Vision...", flush=True)
        data = extract_shops_from_image_via_llm(screenshot_path, url)
        
        if data:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print(f"Vision Success: Extracted {len(data)} tenants.")
            return data
        return None

    except Exception as e:
        print(f"Vision Scraper Error: {e}")
        return None
    finally:
        try: driver.quit()
        except: pass

def scrape_mall_data(url, use_vision=False):
    """
    Unified Scraper Entry Point with Robust Session Management and Verification Bypass.
    """
    if use_vision:
        return scrape_mall_with_vision(url)

    # --- SITE-SPECIFIC SCRAPERS ---
    if "brookefields.com" in url:
        data = scrape_brookefields(url)
        if data:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            print(f"\nSuccessfully saved {len(data)} tenants to {OUTPUT_FILE}")
            return data
        return None

    # --- GENERIC SELENIUM SCRAPER (FALLBACK) ---
    print(f"Initializing Generic Selenium Scraper for: {url}", flush=True)
    print("This method will attempt to intercept map data (Mappedin) from network traffic.", flush=True)
    
    captured = {'token': None, 'venue': None}
    driver = create_driver()
    if not driver:
        print("Error: Webdriver failed to initialize.")
        return None

    try:
        print("Navigating to target...", flush=True)
        driver.get(url)
        
        # --- ROBUST BYPASS 'PRESS & HOLD' VERIFICATION ---
        print("Checking for interactive challenges...", flush=True)
        # Random sleep to mimic human behavior
        time.sleep(4 + np.random.random() * 2)
        
        def handle_captcha_elements(source_root):
            # Known captcha selectors: PerimeterX, Cloudflare, etc.
            selectors = [
                "//div[@id='px-captcha']",
                "//div[contains(@class, 'captcha')]",
                "//*[contains(text(), 'Press & Hold')]",
                "//*[contains(text(), 'Verifying you are human')]"
            ]
            
            for attempt in range(3): # Try up to 3 times if it fails
                for sel in selectors:
                    try:
                        elems = source_root.find_elements(By.XPATH, sel)
                        if elems and elems[0].is_displayed():
                            print(f"Verification element matched: {sel}. Attempt {attempt+1}...", flush=True)
                            
                            # Center of element
                            element = elems[0]
                            
                            # Start interaction
                            action = ActionChains(driver)
                            action.move_to_element_with_offset(element, 5 + np.random.randint(0, 5), 5 + np.random.randint(0, 5))
                            action.click_and_hold().perform()
                            
                            # Hold with "Human Jitter"
                            hold_start = time.time()
                            hold_duration = 11 + np.random.random() * 4
                            while time.time() - hold_start < hold_duration:
                                # Micro-movements while holding
                                action.move_by_offset(np.random.randint(-1, 2), np.random.randint(-1, 2)).perform()
                                time.sleep(0.5 + np.random.random() * 0.5)
                            
                            action.release().perform()
                            print("Hold interaction complete. Verifying...", flush=True)
                            time.sleep(5)
                            
                            # Check if "Please try again" or red text appeared (failure)
                            page_text = driver.page_source.lower()
                            if "please try again" in page_text or "try again" in page_text:
                                print("Bypass failed (Retry detected). Cooling down and retrying...", flush=True)
                                time.sleep(5)
                                break # Exit inner loop to retry outer loop
                            return True
                    except Exception as e: 
                        continue
            return False

        # 1. Check iframes (Crucial for Simon/PerimeterX)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                if handle_captcha_elements(driver):
                    driver.switch_to.default_content()
                    print("Bypass successful in iframe.", flush=True)
                    break
                driver.switch_to.default_content()
            except: 
                driver.switch_to.default_content()
                continue

        # 2. Check main content
        handle_captcha_elements(driver)

        # Robust Map Preparation (Cookies & Tabs)
        prepare_map_state(driver)

        # --- FINAL POLLING FOR NETWORK DATA ---
        print("Monitoring for map data registration...", flush=True)
        for i in range(120):
            # Check for alive session before accessing driver
            try:
                _ = driver.current_url
            except:
                print("\nBrowser session lost or closed.")
                break

            # Use selenium-wire to intercept requests
            for request in driver.requests:
                auth = request.headers.get('Authorization')
                if auth and "Bearer " in auth:
                    token = auth.replace("Bearer ", "").strip()
                    if len(token) > 20: captured['token'] = token
                
                req_url = request.url
                if "mappedin.com" in req_url:
                    if not captured['token']:
                        import urllib.parse
                        ps = urllib.parse.parse_qs(urllib.parse.urlparse(req_url).query)
                        if 'token' in ps: captured['token'] = ps['token'][0]
                        elif 'key' in ps: captured['token'] = ps['key'][0]

                    parts = req_url.split('/')
                    for j, part in enumerate(parts):
                        if part in ['map', 'location', 'node', 'venue'] and j + 1 < len(parts):
                            ext = parts[j+1].split('?')[0]
                            if len(ext) > 5: captured['venue'] = ext

            if captured['token'] and captured['venue']: break
            
            if i % 5 == 0:
                try:
                    driver.execute_script("window.scrollBy(0, 300);")
                    time.sleep(0.5)
                    driver.execute_script("window.scrollBy(0, -300);")
                    print(".", end="", flush=True)
                except: break
            time.sleep(1)

    except Exception as e:
        print(f"Scraper Error: {e}", flush=True)
    finally:
        # Final attempt to extract venue from URL if still missing
        if not captured['venue']:
            try:
                import re
                url_now = driver.current_url
                m = re.search(r'/mall/([^/#?]+)', url_now)
                if m: captured['venue'] = m.group(1)
            except: pass
            
        print("Closing browser session...", flush=True)
        try:
            driver.quit()
        except: pass

    if not captured['token']:
        print("Error: Could not capture Authorization token.", flush=True)
        return None
    
    if not captured['venue']:
        print("Error: Could not determine Venue ID.", flush=True)
        return None

    token, target = captured['token'], captured['venue']
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"Requesting data for: {target}...", flush=True)
    try:
        r = requests.get(f"https://api-gateway.mappedin.com/public/1/map/{target}?fields=id,name,georeference,elevation,shortName", headers=headers, timeout=15)
        
        if r.status_code != 200 and "simon" not in target:
            alt_target = f"simon-{target}"
            print(f"Retrying with Simon alias: {alt_target}")
            r = requests.get(f"https://api-gateway.mappedin.com/public/1/map/{alt_target}?fields=id,name,georeference,elevation,shortName", headers=headers, timeout=15)
            if r.status_code == 200: target = alt_target

        if r.status_code != 200:
            print(f"API Error: Received status {r.status_code} for venue {target}")
            return None
        
        maps_res = r.json()
        locs_res = requests.get(f"https://api-gateway.mappedin.com/public/1/location/{target}?fields=name,description,externalId,type,nodes,operationHours", headers=headers, timeout=15).json()
        nodes_res = requests.get(f"https://api-gateway.mappedin.com/public/1/node/{target}?fields=id,x,y,map", headers=headers, timeout=15).json()
        
    except Exception as e:
        print(f"Connection error: {e}")
        return None

    map_lookup = {m['id']: m for m in maps_res}
    node_lookup = {n['id']: n for n in nodes_res}
    transforms = {m_id: solve_affine(m['georeference'][:3]) for m_id, m in map_lookup.items() if 'georeference' in m and len(m['georeference']) >= 3}

    detailed_tenants = []
    print("\n--- PROCESSING TENANT DATA ---")
    for loc in locs_res:
        if loc.get('type') == 'void': continue 
        
        name = loc.get('name', 'Unknown')
        floor_name = "Level 1"
        lat, lon = None, None

        if loc.get('nodes') and len(loc['nodes']) > 0:
            node_id = loc['nodes'][0]['node']
            map_id = loc['nodes'][0]['map']
            node = node_lookup.get(node_id)
            map_obj = map_lookup.get(map_id)
            
            if map_obj:
                elevation = map_obj.get('elevation', 0)
                floor_name = map_obj.get('name', f"Level {int(elevation) if elevation else 1}")

            if node and map_id in transforms:
                (a, b, c), (d, e, f) = transforms[map_id]
                lat = a * node['x'] + b * node['y'] + c
                lon = d * node['x'] + e * node['y'] + f

        tenant_data = {
            "name": name,
            "description": loc.get('description', '').replace('\r\n', ' ').strip(),
            "location_id": loc.get('externalId', ''),
            "floor": floor_name,
            "hours": format_hours(loc.get('operationHours', [])),
            "latitude": lat,
            "longitude": lon,
        }
        detailed_tenants.append(tenant_data)
        print(f"Found: {name.ljust(35)} | Floor: {floor_name}")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(detailed_tenants, f, indent=2)

    print(f"\nSuccessfully saved {len(detailed_tenants)} tenants to {OUTPUT_FILE}")
    return detailed_tenants

def format_hours(hours_list):
    if not hours_list: return "Not available"
    summary = []
    try:
        if isinstance(hours_list, list):
            for entry in hours_list:
                days, opens, closes = entry.get('dayOfWeek', []), entry.get('opens', ''), entry.get('closes', '')
                if days and opens and closes: summary.append(f"{', '.join(days)}: {opens} - {closes}")
        elif isinstance(hours_list, str): return hours_list
    except: return "Contact Store"
    return "; ".join(summary) if summary else "See Description"



if __name__ == "__main__":
    import sys
    # Example URL: Midland Park Mall
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.simon.com/mall/midland-park-mall/map/#/"
    scrape_mall_data(test_url)
