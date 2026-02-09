import time
import os
import json
import pickle
from pathlib import Path
from typing import Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import pandas as pd

# Load environment variables
load_dotenv()

# Cache ChromeDriver path to speed up startup (only install once)
_cached_chromedriver_path = None

def get_chromedriver_path():
    """Get ChromeDriver path, caching it to avoid re-downloading."""
    global _cached_chromedriver_path
    if _cached_chromedriver_path is None:
        _cached_chromedriver_path = ChromeDriverManager().install()
    return _cached_chromedriver_path

# ================= CONFIG =================
BASE_DIR = os.path.dirname(__file__)
COOKIE_FILE = os.path.join(BASE_DIR, "ig_cookies.pkl")
# Use persistent profile directory (not temp) so cookies persist
CHROME_PROFILE_DIR = r"C:\selenium_instagram_profile"

# ================= COOKIE MANAGEMENT (OPTIONAL - NOT USED FOR LOGIN) =================
# Cookies are saved after successful login as an optimization, but login always uses username/password
def save_cookies(driver):
    """Save cookies to file (optional optimization, not required for login)."""
    try:
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(driver.get_cookies(), f)
        # Don't print - cookies are optional
    except Exception as e:
        # Silently fail - cookies are optional
        pass

# ================= DRIVER =================
def create_driver(headless: bool = True):
    """Create and configure Chrome driver.
    
    Args:
        headless: If True, run browser in headless mode (default: True)
    
    Returns:
        webdriver.Chrome instance
        
    Raises:
        Exception: If Chrome driver fails to start
    """
    global CHROME_PROFILE_DIR

    # Ensure persistent Chrome profile directory exists (used on first attempt)
    persistent_profile_ok = True
    try:
        os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    except Exception as e:
        print(f"[WARN] Could not create Chrome profile directory: {e}")
        persistent_profile_ok = False

    # Fallback profile directory (safer fresh profile if persistent one crashes Chrome)
    fallback_profile_dir = os.path.join(BASE_DIR, "chrome_profile_temp_ig")
    try:
        os.makedirs(fallback_profile_dir, exist_ok=True)
    except Exception:
        # If this also fails, Chrome will still start with its own default profile
        fallback_profile_dir = None

    def build_options(use_persistent_profile: bool) -> Options:
        """Build Chrome Options, mirroring the stable Facebook driver config."""
        options = Options()

        if headless:
            # New headless mode with common stability flags
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")

        # Profile directory: try persistent first, then safe temp profile
        if use_persistent_profile and persistent_profile_ok:
            options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
        elif fallback_profile_dir:
            options.add_argument(f"--user-data-dir={fallback_profile_dir}")

        # General stability options (copied from facebook_scraper.py)
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-ipc-flooding-protection")
        # Use a fixed remote debugging port just like the Facebook scraper
        options.add_argument("--remote-debugging-port=9222")

        options.add_argument("--start-maximized")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Set a realistic user agent (updated to match current Chrome version)
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Additional preferences to make it look more like a real browser
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
        }
        options.add_experimental_option("prefs", prefs)
        return options

    try:
        # Try to create driver with retry logic (like Facebook scraper)
        max_retries = 3
        use_persistent_profile = True  # first try with persistent profile, then fall back

        for attempt in range(max_retries):
            options = build_options(use_persistent_profile)
            try:
                driver = webdriver.Chrome(
                    service=Service(get_chromedriver_path()),  # Use cached path for faster startup
                    options=options,
                )

                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"},
                )
                return driver
            except Exception as e:
                error_msg = str(e)

                # If Chrome crashes with DevToolsActivePort issue, switch to fresh profile and retry
                if "DevToolsActivePort" in error_msg or "crashed" in error_msg.lower():
                    print(
                        f"[WARN] Chrome failed to start (attempt {attempt + 1}/{max_retries}) "
                        f"with profile: {'persistent' if use_persistent_profile else 'temp'}. "
                        f"Error: {error_msg}"
                    )
                    # After first failure with persistent profile, always use fallback profile
                    use_persistent_profile = False

                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue

                    # Last attempt failed with crash → raise friendly message
                    raise Exception(
                        "Chrome failed to start. This is often caused by:\n"
                        "1. Chrome browser not installed or outdated\n"
                        "2. ChromeDriver version mismatch with Chrome\n"
                        "3. Another Chrome instance already running\n"
                        "4. Corrupted Chrome profile directory\n"
                        "5. Insufficient permissions\n\n"
                        "Automatic mitigation tried a fresh temporary profile but Chrome still crashed.\n"
                        "Try: Close all Chrome windows, update Chrome, or restart your computer.\n"
                        f"Original error: {error_msg}"
                    )

                # Non-DevTools errors: just retry a couple of times, then surface original error
                if attempt < max_retries - 1:
                    print(
                        f"[WARN] Chrome driver creation failed (attempt {attempt + 1}/{max_retries}): {error_msg}. "
                        "Retrying..."
                    )
                    time.sleep(2)
                else:
                    raise

    except Exception as e:
        error_msg = str(e)
        if "DevToolsActivePort" in error_msg or "crashed" in error_msg.lower():
            raise Exception(
                "Chrome failed to start. This is often caused by:\n"
                "1. Chrome browser not installed or outdated\n"
                "2. ChromeDriver version mismatch with Chrome\n"
                "3. Another Chrome instance already running\n"
                "4. Corrupted Chrome profile directory\n"
                "5. Insufficient permissions\n\n"
                "Try: Close all Chrome windows, delete any 'C:\\selenium_instagram_profile' folder, "
                "update Chrome, or restart your computer.\n"
                f"Original error: {error_msg}"
            )
        else:
            raise

# ================= LOGIN =================
def instagram_login(driver, username: Optional[str] = None, password: Optional[str] = None, headless: bool = True):
    """Login to Instagram using provided credentials or environment variables."""
    # Get credentials from parameters or environment
    if not username:
        username = os.getenv("IG_USERNAME") or os.getenv("INSTAGRAM_USERNAME")
    if not password:
        password = os.getenv("IG_PASSWORD") or os.getenv("INSTAGRAM_PASSWORD")
    
    if not username or not password:
        print("[WARN] Instagram credentials not provided. Trying to continue without login...")
        return
    
    driver.get("https://www.instagram.com/accounts/login/")
    
    # Skip waiting for full page load - start immediately (faster startup)
    time.sleep(0.5)  # Minimal wait for initial render
    
    # Check what page we're actually on
    current_url = driver.current_url.lower()
    page_title = driver.title.lower()
    print(f"[DEBUG] After loading login page - URL: {current_url}, Title: {page_title[:50]}")
    
    # Check if we're already logged in (redirected away from login page)
    if "accounts/login" not in current_url:
        print("[INFO] Already logged in (not on login page)")
        # Still dismiss "Not Now" prompts
        for _ in range(2):
            try:
                WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[text()='Not Now']"))
                ).click()
                time.sleep(1)
            except (TimeoutException, NoSuchElementException):
                pass
        return
    
    # Check if Instagram is blocking us or showing a challenge
    # Only check if we're actually on a challenge URL, not just if the word appears in page source
    page_source_lower = driver.page_source.lower()
    if "/challenge/" in current_url:
        print("[ERROR] Instagram is showing a challenge page.")
        if headless:
            raise Exception("Instagram challenge detected - please login manually first or use non-headless mode")
        else:
            print("[INFO] In non-headless mode - please solve the challenge in the browser window")
            print("[INFO] Waiting up to 120 seconds for you to complete the challenge...")
            try:
                WebDriverWait(driver, 120).until(
                    lambda d: "/challenge/" not in d.current_url.lower() and "accounts/login" not in d.current_url.lower()
                )
                print("[INFO] Challenge completed")
            except TimeoutException:
                raise Exception("Challenge not completed within timeout")
    
    if "blocked" in page_source_lower or "suspended" in page_source_lower:
        print("[ERROR] Instagram may be blocking automated access")
        raise Exception("Instagram appears to be blocking automated access")
    
    try:
        # Wait for username field with multiple selector strategies (Instagram may use different attributes)
        username_field = None
        username_selectors = [
            (By.NAME, "username"),
            (By.XPATH, "//input[@name='username']"),
            (By.XPATH, "//input[@type='text']"),
            (By.XPATH, "//input[@aria-label='Phone number, username, or email']"),
            (By.XPATH, "//input[@placeholder*='username' or @placeholder*='Username' or @placeholder*='email']"),
            (By.CSS_SELECTOR, "input[name='username']"),
            (By.CSS_SELECTOR, "input[type='text']")
        ]
        
        for selector_type, selector_value in username_selectors:
            try:
                username_field = WebDriverWait(driver, 2).until(  # Reduced to 2s for faster startup
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                if username_field.is_displayed():
                    print(f"[INFO] Found username field using: {selector_type}={selector_value}")
                    break
            except (TimeoutException, NoSuchElementException):
                continue
        
        if not username_field:
            # Debug: save page source to see what Instagram is showing
            print("[ERROR] Could not find username field. Instagram page structure may have changed.")
            print(f"[DEBUG] Current URL: {driver.current_url}")
            print(f"[DEBUG] Page title: {driver.title}")
            
            # Check if we're already logged in
            if "accounts/login" not in driver.current_url.lower():
                print("[INFO] Not on login page - may already be logged in")
                return
            
            # Check for common Instagram blocking/challenge indicators
            page_text = driver.page_source.lower()
            if "try again later" in page_text or "temporarily blocked" in page_text:
                raise Exception("Instagram temporarily blocked access. Try again later or use non-headless mode.")
            elif "verify" in page_text or "confirm" in page_text:
                raise Exception("Instagram requires verification. Cannot proceed in headless mode.")
            else:
                raise Exception("Could not find username field on Instagram login page. Page structure may have changed or Instagram is blocking automated access.")
        
        # Fill username
        username_field.clear()
        username_field.send_keys(username)
        time.sleep(1)
        
        # Find password field with multiple selectors
        password_field = None
        password_selectors = [
            (By.NAME, "password"),
            (By.XPATH, "//input[@name='password']"),
            (By.XPATH, "//input[@type='password']"),
            (By.XPATH, "//input[@aria-label='Password']"),
            (By.CSS_SELECTOR, "input[name='password']"),
            (By.CSS_SELECTOR, "input[type='password']")
        ]
        
        for selector_type, selector_value in password_selectors:
            try:
                password_field = WebDriverWait(driver, 2).until(  # Reduced to 2s for faster startup
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                if password_field.is_displayed():
                    print(f"[INFO] Found password field using: {selector_type}={selector_value}")
                    break
            except (TimeoutException, NoSuchElementException):
                continue
        
        if not password_field:
            raise Exception("Could not find password field on Instagram login page")
        
        # Fill password and submit
        password_field.clear()
        password_field.send_keys(password)
        time.sleep(1)
        password_field.send_keys(Keys.RETURN)

        # Wait for login to complete - check for nav element (main feed) or that we're not on login page
        try:
            # Wait for either nav element or check URL changed from login page
            def login_successful(driver):
                try:
                    # Check if nav element exists (main feed indicator)
                    driver.find_element(By.TAG_NAME, "nav")
                    return True
                except:
                    # Check if URL changed from login page
                    return "accounts/login" not in driver.current_url.lower()
            
            WebDriverWait(driver, 8).until(login_successful)  # Reduced to 8s for faster startup
            print("[INFO] Logged in to Instagram")
            # Cookies will be saved by the calling function
        except TimeoutException:
            # Check if we're stuck on a challenge/verification page
            current_url = driver.current_url.lower()
            page_text = driver.page_source.lower()
            
            if "challenge" in current_url or "challenge" in page_text:
                print("[ERROR] Instagram requires verification/challenge. Cannot proceed in headless mode.")
                raise Exception("Instagram verification required - please login manually first or disable 2FA")
            elif "login" in current_url:
                print("[ERROR] Login failed - still on login page")
                raise Exception("Instagram login failed - check credentials")
            else:
                print("[INFO] Login status unclear, but not on login page - continuing")
    except (TimeoutException, NoSuchElementException) as e:
        print(f"[WARN] Login attempt issue: {e}")
        # Check current state
        current_url = driver.current_url.lower()
        if "login" not in current_url and "challenge" not in current_url:
            print("[INFO] May already be logged in")
        else:
            print("[ERROR] Login failed")
            raise

    # Dismiss "Not Now" prompts (matching demo.py timing)
    for _ in range(2):
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[text()='Not Now']"))
            ).click()
            time.sleep(1)
        except (TimeoutException, NoSuchElementException):
            pass

# ================= LOAD POSTS / REELS / VIDEOS =================
def load_post_links(driver, max_posts):
    """Load links for posts, reels, and videos (with safety limits, minimal console output)."""
    links = set()
    time.sleep(5)

    max_scrolls = 50  # safety limit
    scroll_count = 0
    stable_count = 0
    last_link_count = 0

    while len(links) < max_posts and scroll_count < max_scrolls:
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'/p/') or contains(@href,'/reel/') or contains(@href,'/tv/')]")
        
        if not anchors:
            print(f"[DEBUG] No post links found on scroll {scroll_count + 1}")
        
        for a in anchors:
            try:
                href = a.get_attribute("href")
                if href:
                    links.add(href)
                if len(links) >= max_posts:
                    break
            except Exception:
                continue

        if len(links) == last_link_count:
            stable_count += 1
            if stable_count >= 5:
                print(f"[INFO] Stopped scrolling - no new links found after {stable_count} scrolls")
                break
        else:
            stable_count = 0
            last_link_count = len(links)
            if scroll_count % 5 == 0:  # Print progress every 5 scrolls
                print(f"[INFO] Found {len(links)} post links so far...")

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)  # Increased from 2 to match demo.py
        scroll_count += 1

    print(f"[INFO] Total post links collected: {len(links)}")
    return list(links)[:max_posts]

# ================= EXTRACT TEXT (POST / REEL / VIDEO) =================
def extract_post_data(driver, post_url):
    """Extract data from Instagram post, reel, or video.
    Matches the exact logic from the provided code.
    """
    driver.get(post_url)
    time.sleep(5)

    collected_text = set()
    time_text = ""
    datetime_val = ""

    # ========= CAPTION / REEL DESCRIPTION =========
    # Use spans with line-height: 18px (exact match to provided code)
    # This captures the full caption text including newlines
    try:
        spans = driver.find_elements(By.XPATH, '//span[@style="line-height: 18px;"]')
        for span in spans:
            # Get text preserving newlines and formatting
            text = span.text  # Don't strip immediately to preserve newlines
            if text and text.strip():  # Only add if there's actual content
                # Preserve the text as-is to maintain newlines and formatting
                collected_text.add(text)
    except Exception:
        pass

    # ========= HASHTAGS =========
    # Extract hashtags separately and add them
    try:
        hashtags = driver.find_elements(By.XPATH, "//article//a[starts-with(text(),'#')]")
        for h in hashtags:
            text = h.text.strip()
            if text:
                collected_text.add(text)
    except Exception:
        pass

    # ========= TIME =========
    try:
        time_el = driver.find_element(By.TAG_NAME, "time")
        time_text = time_el.text.strip()
        datetime_val = time_el.get_attribute("datetime")
    except Exception:
        pass

    # Determine content type (exact match to provided code)
    content_type = (
        "reel" if "/reel/" in post_url else
        "video" if "/tv/" in post_url else
        "post"
    )

    # Join all collected text with " | " separator (exact match to provided code)
    # This preserves the format shown in the example output
    combined_text = " | ".join(collected_text)

    return {
        "post_url": post_url,
        "content_type": content_type,
        "text": combined_text,
        "time": time_text,
        "datetime": datetime_val
    }

# ================= MAIN =================
def scrape_instagram_simple(ig_url: str, target_count: int = 20) -> pd.DataFrame:
    """
    Scrape Instagram profile/page posts and return DataFrame.
    Similar to scrape_facebook_simple for integration with Streamlit app.
    
    Args:
        ig_url: Instagram URL (e.g., https://www.instagram.com/username/) or username
        target_count: Maximum number of posts to scrape (default: 5)
    
    Returns:
        DataFrame with columns: ['shop_name', 'phone', 'floor', 'source']
    """
    driver = None
    try:
        # Get credentials from environment (required, like Facebook)
        username_cred = os.getenv("IG_USERNAME") or os.getenv("INSTAGRAM_USERNAME")
        password_cred = os.getenv("IG_PASSWORD") or os.getenv("INSTAGRAM_PASSWORD")
        
        if not username_cred or not password_cred:
            print("Error: IG_USERNAME and IG_PASSWORD must be set in .env file")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        
        # Extract username from URL if full URL provided
        username = ig_url
        if 'instagram.com' in ig_url:
            # Extract username from URL
            parts = ig_url.rstrip('/').split('/')
            username = parts[-1] if parts else ig_url
            # Remove @ if present
            username = username.replace('@', '')
        
        print(f"[INFO] Scraping Instagram profile: {username}")
        
        # Use headless mode (hardcoded like Facebook scraper)
        driver = create_driver(headless=True)
        
        # Always try username/password login first (from .env file)
        print("[INFO] Attempting login with username and password from .env file...")
        logged_in = False
        
        try:
            instagram_login(driver, username_cred, password_cred, headless=True)
            # Verify login was successful (reduced wait for faster startup)
            time.sleep(1)
            current_url = driver.current_url.lower()
            if "accounts/login" not in current_url and "/challenge/" not in current_url:
                # Check for logged-in indicators
                login_indicators = [
                    (By.XPATH, "//a[contains(@href, '/direct/')]"),
                    (By.XPATH, "//nav"),
                    (By.XPATH, "//a[contains(@href, '/accounts/edit/')]"),
                    (By.TAG_NAME, "nav")
                ]
                for indicator_type, indicator_value in login_indicators:
                    try:
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((indicator_type, indicator_value))
                        )
                        logged_in = True
                        print("[INFO] Login successful with username/password")
                        # Optionally save cookies (not used for login, just optimization)
                        save_cookies(driver)
                        break
                    except TimeoutException:
                        continue
            else:
                print("[WARN] Still on login/challenge page after login attempt")
        except Exception as e:
            print(f"[ERROR] Login failed: {e}")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        
        if not logged_in:
            print("[ERROR] Could not verify login status")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        

        # Navigate to profile
        profile_url = f"https://www.instagram.com/{username}/"
        print(f"[INFO] Navigating to profile: {profile_url}")
        driver.get(profile_url)
        time.sleep(1.5)  # Reduced for faster startup
        
        # Check for error messages (user not found, private account, etc.)
        page_text = driver.page_source.lower()
        if "sorry, this page isn't available" in page_text or "user not found" in page_text:
            print(f"[ERROR] Profile '{username}' not found or unavailable")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        
        if "this account is private" in page_text:
            print(f"[ERROR] Profile '{username}' is private and you're not following it")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        
        # Check if profile page loaded correctly - try multiple selectors
        profile_loaded = False
        selectors_to_try = [
            (By.TAG_NAME, "article"),
            (By.XPATH, "//a[contains(@href,'/p/') or contains(@href,'/reel/')]"),
            (By.XPATH, "//main"),
            (By.XPATH, "//header")
        ]
        
        for selector_type, selector_value in selectors_to_try:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                profile_loaded = True
                print(f"[INFO] Profile page loaded (found {selector_value})")
                break
            except TimeoutException:
                continue
        
        if not profile_loaded:
            print("[WARN] Profile page may not have loaded correctly, but continuing...")
            print(f"[DEBUG] Current URL: {driver.current_url}")
            print(f"[DEBUG] Page title: {driver.title}")

        # Load post links
        print(f"[INFO] Loading post links (target: {target_count})...")
        post_links = load_post_links(driver, target_count)
        print(f"[INFO] Found {len(post_links)} post links")

        if not post_links:
            print("[WARN] No post links found. This may indicate:")
            print("  - Profile is private and you're not following it")
            print("  - Profile doesn't exist or has no posts")
            print("  - Login failed and you're not authenticated")
            print(f"[DEBUG] Current URL: {driver.current_url}")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])

        results = []
        for i, link in enumerate(post_links, 1):
            try:
                print(f"[INFO] Extracting post {i}/{len(post_links)}: {link[:50]}...")
                post_data = extract_post_data(driver, link)
                if post_data:
                    results.append(post_data)
                time.sleep(2)
            except Exception as e:
                print(f"[WARN] Failed to extract data from {link}: {e}")
                continue

        # Convert to DataFrame format compatible with shop data
        # Store full Instagram data including post_url, content_type, text, time, datetime
        rows = []
        for post in results:
            text = post.get('text', '')
            post_url = post.get('post_url', '')
            content_type = post.get('content_type', 'post')
            time_text = post.get('time', '')
            datetime_val = post.get('datetime', '')
            
            # Use text as shop_name (first 200 chars) for display/comparison
            # If no text, use a generic identifier based on post URL
            if text:
                shop_name = text[:200] if len(text) > 200 else text
            else:
                if post_url:
                    # Extract post ID from URL as identifier
                    shop_name = f"Instagram {content_type.title()} {post_url.split('/')[-2] if '/' in post_url else 'Unknown'}"
                else:
                    shop_name = "Instagram Post"
            
            rows.append({
                'shop_name': shop_name,
                'phone': post_url,  # Store post_url in phone field for comparison
                'floor': f"{content_type}|{time_text}|{datetime_val}",  # Store metadata in floor field
                'source': f"Instagram {content_type.title()} Data",  # Clear heading for Instagram data
                # Store full text in a way that can be accessed
                'full_text': text,  # Full text for comparison
                'post_url': post_url,  # Full post URL
                'content_type': content_type,  # post/reel/video
                'time': time_text,  # Relative time (e.g., "3d", "4d")
                'datetime': datetime_val  # ISO datetime
            })

        # Create DataFrame with all columns
        df = pd.DataFrame(rows)
        
        # Ensure required columns exist for compatibility
        required_cols = ['shop_name', 'phone', 'floor', 'source']
        for col in required_cols:
            if col not in df.columns:
                df[col] = ''
        
        print(f"[SUCCESS] Extracted {len(df)} items from Instagram with full metadata")
        return df

    except Exception as e:
        print(f"[ERROR] Instagram scraping error: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def main():
    """Original main function for standalone execution."""
    import sys
    
    driver = None
    try:
        # Get credentials from environment variables only (no hardcoded defaults)
        username = os.getenv("IG_USERNAME") or os.getenv("INSTAGRAM_USERNAME")
        password = os.getenv("IG_PASSWORD") or os.getenv("INSTAGRAM_PASSWORD")
        
        if not username or not password:
            print("[ERROR] Instagram credentials not found. Please set IG_USERNAME and IG_PASSWORD environment variables.")
            return
        
        # Get URL from command line argument or environment variable
        if len(sys.argv) > 1:
            ig_url = sys.argv[1]
        else:
            ig_url = os.getenv("IG_URL") or os.getenv("INSTAGRAM_URL")
        
        if not ig_url:
            print("[ERROR] Instagram URL not provided. Usage: python instagram.py <instagram_url>")
            print("   Or set IG_URL environment variable")
            return
        
        # Extract username from URL if full URL provided
        if 'instagram.com' in ig_url:
            parts = ig_url.rstrip('/').split('/')
            search_query = parts[-1] if parts else ig_url
            search_query = search_query.replace('@', '')
        else:
            search_query = ig_url
        
        # Default to 5 posts for faster runs unless overridden via IG_MAX_POSTS
        max_posts = int(os.getenv("IG_MAX_POSTS", "5"))
        
        driver = create_driver(headless=False)
        instagram_login(driver, username, password, headless=False)

        driver.get(f"https://www.instagram.com/{search_query}/")
        time.sleep(1.5)  # Reduced for faster startup

        post_links = load_post_links(driver, max_posts)
        print(f"[INFO] Found {len(post_links)} posts/reels/videos")

        results = []
        for link in post_links:
            results.append(extract_post_data(driver, link))
            time.sleep(3)

        # ================= SAVE AS JSON =================
        if results:
            # Use Downloads folder or current directory as fallback
            downloads_path = Path.home() / "Downloads"
            if not downloads_path.exists():
                downloads_path = Path.cwd()
            output_file = str(downloads_path / f"instagram_{search_query}_post{len(results)}.json")
            
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=4)

            print(f"[SUCCESS] JSON saved → {output_file}")
        else:
            print("[WARN] No results to save")

    except Exception as e:
        print(f"[ERROR] An error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n[BROWSER LEFT OPEN]")
        input("Press ENTER to exit...")
        if driver:
            driver.quit()

if __name__ == "__main__":
    main() 
    