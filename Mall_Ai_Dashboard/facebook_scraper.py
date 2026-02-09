"""
Facebook scraper module for extracting posts from Facebook pages.
Adapted for integration with the mall AI dashboard.
"""
import os
import sys
import time
import pickle
import re
from datetime import datetime
from typing import List, Dict, Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from dotenv import load_dotenv
import pandas as pd
import requests
import json

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

# XPATH used to locate post html-divs
POST_XPATH = "//*[@class='html-div xdj266r x14z9mp xat24cr x1lziwak xexx8yu xyri2b x18d9i69 x1c1uobl']"

# Paths
BASE_DIR = os.path.dirname(__file__)
COOKIE_FILE = os.path.join(BASE_DIR, "fb_cookies.pkl")
CHROME_PROFILE_DIR = r"C:\selenium_chrome_profile"

# Cache for CSS order maps (keyed by page URL to avoid re-parsing)
_css_order_cache = {}

# OpenAI API configuration (for solving jumbled timestamps)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()


def save_cookies(driver):
    """Save cookies to file."""
    try:
        with open(COOKIE_FILE, "wb") as f:
            pickle.dump(driver.get_cookies(), f)
    except Exception as e:
        print(f"Warning: failed to save cookies: {e}")


def load_cookies(driver):
    """Load cookies from file."""
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE, "rb") as f:
            cookies = pickle.load(f)
    except (EOFError, pickle.UnpicklingError) as e:
        print(f"Warning: cookie file is empty or corrupted: {e}")
        try:
            os.remove(COOKIE_FILE)
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"Warning: failed to load cookies: {e}")
        return False

    try:
        for c in cookies:
            driver.add_cookie(c)
    except Exception as e:
        print(f"Warning: failed to add cookies to driver: {e}")
        return False

    return True


def create_driver(headless: bool = True):
    """Create and configure Chrome driver.
    
    Args:
        headless: If True, run browser in headless mode (default: True)
    
    Returns:
        webdriver.Chrome instance
        
    Raises:
        Exception: If Chrome driver fails to start
    """
    options = Options()
    
    # Ensure Chrome profile directory exists
    try:
        os.makedirs(CHROME_PROFILE_DIR, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create Chrome profile directory: {e}")
        # Use a temp directory in the current folder instead
        import tempfile
        profile_dir = os.path.join(BASE_DIR, "chrome_profile_temp")
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")
    else:
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    
    if headless:
        options.add_argument("--headless=new")  # Use new headless mode
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
    
    # Additional stability options for Windows
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-ipc-flooding-protection")
    options.add_argument("--remote-debugging-port=9222")
    
    # Set a realistic user agent to avoid detection
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Additional options to make it less detectable
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    options.add_experimental_option("prefs", prefs)

    try:
        # Try to create driver with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                driver = webdriver.Chrome(
                    service=Service(get_chromedriver_path()),  # Use cached path for faster startup
                    options=options
                )
                
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"}
                )
                return driver
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Chrome driver creation failed (attempt {attempt + 1}/{max_retries}), retrying...")
                    time.sleep(2)
                else:
                    raise Exception(f"Failed to create Chrome driver after {max_retries} attempts: {str(e)}")
    except Exception as e:
        error_msg = str(e)
        if "DevToolsActivePort" in error_msg or "crashed" in error_msg.lower():
            raise Exception(
                f"Chrome failed to start. This is often caused by:\n"
                f"1. Chrome browser not installed or outdated\n"
                f"2. ChromeDriver version mismatch with Chrome\n"
                f"3. Another Chrome instance already running\n"
                f"4. Insufficient permissions\n\n"
                f"Try: Close all Chrome windows, update Chrome, or restart your computer.\n"
                f"Original error: {error_msg}"
            )
        else:
            raise


def is_noise_line(line: str) -> bool:
    """Check if a line is noise/metadata (page info, not post content)."""
    s = line.strip().lower()
    if not s:
        return True

    # Repeated words (like "facebook facebook facebook")
    words = s.split()
    if len(words) > 1 and len(set(words)) == 1:  # All words are the same
        return True
    if len(words) >= 3 and words.count(words[0]) >= len(words) * 0.7:  # 70%+ same word
        return True

    # Very short fragments are usually UI noise
    if len(s) < 15:
        # Check if it's clearly UI noise
        if any(pattern in s for pattern in ['notification', 'see all', 'follow', 'like', 'share', 'comment']):
            return True
        # Otherwise, allow short lines that might be valid content
        return False

    # Lines dominated by "facebook" (header/navigation noise)
    if re.fullmatch(r"(facebook\s*){2,}", s):
        return True
    if s.count("facebook") >= 4:
        return True

    # Pure notification / UI strips
    ui_noise_keywords = [
        'notificationsallunreadnew',
        'notifications all unread new',
        'see all',
        'see all unread',
        'see all notifications',
        # NEW: Facebook notification-center phrases that should never be treated as posts
        'mark as read',
        'earlier unread',
        'see previous notifications',
        'you approved a login',
        # Patterns like "posted 3 new reels" from notification feed, not real post text
        'posted 3 new reels',
        'posted 2 new reels',
        'posted a new reel',
        'posted 3 new posts',
        'posted 2 new posts',
    ]
    for kw in ui_noise_keywords:
        if kw in s:
            return True

    # Lines that are mostly follower / page meta information
    noise_keywords = [
        'followers', 'recommend', 'closed now', 'open now', 'see all photos', 'photos',
        'follow', 'like', 'comment', 'share', 'write a comment', 'page',
        'details', 'links', 'services',
        'check in', 'check-ins', 'about', 'menu', 'events'
    ]
    for kw in noise_keywords:
        if kw in s:
            return True

    # Lines that are basically URLs / domains (standalone domain names)
    if re.search(r"https?://", s) or re.search(r"\bwww\.", s):
        return True
    # Standalone domain names (like "bellevuecollection.com" by itself)
    if re.match(r"^[a-z0-9\-]+\.[a-z]{2,4}$", s) or re.match(r"^[a-z0-9\-]+\.[a-z0-9\-]+\.[a-z]{2,4}$", s):
        return True

    # Lines that look like pure phone numbers or phone + mall name
    digits_only = re.sub(r"[^\d]", "", s)
    if len(digits_only) >= 7:
        # If after removing letters we still have a long digit string, treat as phone/address noise
        if re.fullmatch(r"[+\d\-\s().x]+", line.strip(), flags=re.IGNORECASE):
            return True

    # Lines that look like postal addresses (street + city + state)
    # Pattern: "Closed now 575 Bellevue Sq" or "575 Bellevue Sq, Bellevue"
    address_keywords = [
        'street', 'st ', 'st,', 'road', 'rd ', 'rd,', 'avenue', 'ave', 'boulevard', 'blvd',
        'square', 'sq', 'sq,', 'drive', 'dr ', 'dr,', 'lane', 'ln', 'parkway', 'pkwy',
        'united states', 'india', 'wa ', 'wa,', 'ca ', 'ca,'
    ]
    # Check for address patterns: number + street keyword OR "closed now/open now" + address
    if any(kw in s for kw in address_keywords):
        if re.search(r"\d{3,5}\s+\w+", s):  # Has number + word (like "575 Bellevue")
            return True
        if re.search(r"(closed|open)\s+now", s):  # Has "closed now" or "open now"
            return True

    # Page names (short, 2-3 words, all capitalized or proper nouns, no verbs)
    # Pattern: "Bellevue Collection" (just name, no sentence structure)
    words = s.split()
    if 2 <= len(words) <= 3:
        # Check if it's all proper nouns/capitalized words (likely page name)
        # If original line is mostly capitalized and short, it's probably a page name
        original_words = line.strip().split()
        if len(original_words) == len(words):
            capitalized_count = sum(1 for w in original_words if w and w[0].isupper())
            if capitalized_count >= len(original_words) * 0.8:  # 80%+ capitalized
                # Check if it doesn't have sentence structure (no verbs, no punctuation)
                if not re.search(r"[.!?]", line) and not any(w.endswith('ing') or w.endswith('ed') for w in words):
                    return True

    # The dot separator used in a lot of FB meta lines
    if '·' in line:
        return True

    return False


def filter_post_text(text: str) -> Optional[Dict]:
    """Extract and filter meaningful content from post text."""
    if not text or not text.strip():
        return None

    # Hard block: Facebook notification-center / personal feed snippets that
    # should NEVER be stored or treated as mall content anywhere (Scratch or Existing Tenant tabs).
    # This catches strings like:
    # "See allUnreadARRA TV posted 3 new reels... Mark as read ... Earlier Unread ... You approved a login ..."
    notification_block_patterns = re.compile(
        r"(?i)("
        r"posted\s+\d+\s+new\s+reels?"      # "posted 3 new reels"
        r"|posted\s+\d+\s+new\s+posts?"    # "posted 2 new posts"
        r"|you\s+approved\s+a\s+login"     # "You approved a login"
        r"|earlier\s+unread"               # "Earlier Unread"
        r"|see\s+previous\s+notifications" # "See previous notifications"
        r"|mark\s+as\s+read"               # "Mark as read"
        r")"
    )
    if notification_block_patterns.search(text):
        return None
    
    text = re.sub(r"\r", "\n", text)
    parts = [p.strip() for p in re.split(r"[\n]+", text) if p.strip()]

    kept = []
    for p in parts:
        p_clean = re.sub(r"\s+", " ", p).strip()
        # Only skip if it's clearly noise - be more lenient
        if not is_noise_line(p_clean):
            kept.append(p_clean)

    # If we filtered out everything, try a more lenient approach
    if not kept:
        # Try splitting by sentences and keeping longer ones
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for s in sentences:
            s_clean = re.sub(r"\s+", " ", s).strip()
            # Lower threshold - keep sentences longer than 20 chars
            if len(s_clean) > 20:
                # Only filter out if it's clearly pure noise
                if not is_noise_line(s_clean):
                    kept.append(s_clean)
    
    # If still nothing, try keeping the original text but clean it
    if not kept:
        # Keep original text but remove obvious noise patterns
        cleaned = re.sub(r"(?i)(notificationsallunreadnew|see all unread|see all notifications)", "", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) > 15:  # Lower threshold
            kept.append(cleaned)

    if not kept:
        return None

    result = ' '.join(kept)
    result = re.sub(r"\s+", " ", result).strip()

    # In many Facebook UIs, meta/header noise is concatenated with the real
    # caption using the middle dot "·" separator. Example:
    # "Facebook Facebook ... · Find your bliss with candles from ..."
    # For such cases, keep only the text AFTER the last "·".
    if "·" in result:
        tail = result.split("·")[-1].strip()
        # Only use the tail if it is reasonably long – avoids dropping
        # genuine short captions that might incidentally contain "·".
        if len(tail) >= 20:
            result = tail

    # Lower minimum length requirement from 20 to 15
    if len(result) <= 15:
        return None

    hashtags = re.findall(r"#\w[\w-]*", result)
    urls = re.findall(r"https?://\S+|www\.\S+", result)
    mentions = re.findall(r"@\w[\w-]*", result)

    caption = result
    for u in urls:
        caption = caption.replace(u, '')
    for h in hashtags:
        caption = caption.replace(h, '')
    for m in mentions:
        caption = caption.replace(m, '')

    caption = re.sub(r"\s+", " ", caption).strip()
    # Lower threshold - if caption is too short after cleaning, use original
    if len(caption) < 10:
        caption = result

    # Extra guard: drop blocks that look like generic shop lists / page headers
    # (many capitalized words, no real verbs, no hashtags)
    words = [w for w in re.split(r"\s+", caption) if w]
    if words and not hashtags:
        capitalized = sum(1 for w in words if w[0].isupper())
        verb_like = sum(
            1
            for w in words
            if w.lower() in {"is", "are", "was", "were", "has", "have", "open", "opening", "opened", "shop", "shopping"}
            or w.lower().endswith("ing")
            or w.lower().endswith("ed")
        )
        # If almost everything is capitalized names and there are no verbs, treat as noise
        if capitalized >= len(words) * 0.8 and verb_like == 0 and len(words) >= 5:
            return None

    return {
        'caption': caption,
        'hashtags': hashtags,
        'urls': urls,
        'mentions': mentions,
        'raw': result,
    }


def parse_css_order_from_page(driver, use_cache=True):
    """Extract order values from CSS in the current page (using user's EXACT logic).
    Enhanced to extract CSS from all sources: inline styles, style tags, and external stylesheets.
    
    Args:
        driver: Selenium WebDriver instance
        use_cache: If True, cache the CSS order map per page URL to avoid re-parsing
    
    Returns:
        Dictionary mapping CSS class names to their order values
    """
    # Check cache first
    if use_cache:
        try:
            current_url = driver.current_url
            if current_url in _css_order_cache:
                cached_map = _css_order_cache[current_url]
                print(f"Using cached CSS order map ({len(cached_map)} classes) for {current_url[:50]}...")
                return cached_map
        except Exception:
            pass
    
    order_map = {}
    css_content = ""
    
    try:
        # Method 1: Get all inline <style> tags from the page
        style_elements = driver.find_elements(By.TAG_NAME, "style")
        for style in style_elements:
            css_text = style.get_attribute("innerHTML") or style.get_attribute("textContent") or ""
            if css_text:
                css_content += css_text + "\n"
        
        # Method 2: Extract CSS from all stylesheets via JavaScript (including external ones)
        try:
            css_from_js = driver.execute_script("""
                var allCSS = '';
                var sheets = document.styleSheets;
                
                for (var i = 0; i < sheets.length; i++) {
                    try {
                        var sheet = sheets[i];
                        // Try to get all rules from the stylesheet
                        var rules = sheet.cssRules || sheet.rules;
                        if (rules) {
                            for (var j = 0; j < rules.length; j++) {
                                try {
                                    var rule = rules[j];
                                    // Get the full CSS text of the rule
                                    if (rule.cssText) {
                                        allCSS += rule.cssText + '\\n';
                                    } else if (rule.style && rule.style.order) {
                                        // If rule has order property, reconstruct the CSS
                                        var selector = rule.selectorText || '';
                                        var order = rule.style.order;
                                        if (selector && order) {
                                            allCSS += selector + ' { order: ' + order + '; }\\n';
                                        }
                                    }
                                } catch(e) {
                                    // Skip rules that can't be accessed (CORS, etc.)
                                }
                            }
                        }
                    } catch(e) {
                        // Skip stylesheets that can't be accessed (CORS restrictions)
                        // Try to get the href and fetch it if it's from the same origin
                        try {
                            if (sheet.href && sheet.href.startsWith(window.location.origin)) {
                                // Same origin - we could fetch it, but for now skip
                            }
                        } catch(e2) {}
                    }
                }
                return allCSS;
            """)
            if css_from_js:
                css_content += "\n" + css_from_js
        except Exception as e:
            print(f"Warning: Could not extract CSS from stylesheets via JavaScript: {e}")
        
        # Method 3: Try to fetch external CSS files from <link> tags (same origin only)
        try:
            link_elements = driver.find_elements(By.XPATH, "//link[@rel='stylesheet']")
            for link in link_elements:
                try:
                    href = link.get_attribute("href")
                    if href and (href.startswith("http://") or href.startswith("https://")):
                        # Only fetch if it's from the same origin (to avoid CORS issues)
                        current_url = driver.current_url
                        from urllib.parse import urlparse
                        current_domain = urlparse(current_url).netloc
                        link_domain = urlparse(href).netloc
                        
                        # For Facebook, we can try to fetch CSS if it's from facebook.com
                        if "facebook.com" in link_domain or current_domain == link_domain:
                            try:
                                import requests
                                response = requests.get(href, timeout=5, headers={
                                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                                })
                                if response.status_code == 200:
                                    css_content += "\n" + response.text
                            except Exception:
                                pass  # Skip if fetch fails
                except Exception:
                    continue
        except Exception as e:
            print(f"Warning: Could not fetch external CSS files: {e}")
        
        # Method 4: Get CSS from computed styles of elements with order property
        # This is a fallback to find order values even if CSS rules aren't accessible
        try:
            # Find elements that might have order property set
            elements_with_order = driver.execute_script("""
                var elements = [];
                var allElements = document.querySelectorAll('*');
                for (var i = 0; i < allElements.length; i++) {
                    var el = allElements[i];
                    var computed = window.getComputedStyle(el);
                    var order = computed.order;
                    if (order && order !== 'auto' && order !== '0') {
                        var classes = el.className;
                        if (classes && typeof classes === 'string') {
                            var classList = classes.split(' ').filter(function(c) { return c.trim(); });
                            for (var j = 0; j < classList.length; j++) {
                                elements.push({
                                    className: classList[j],
                                    order: parseInt(order) || 0
                                });
                            }
                        }
                    }
                }
                return elements;
            """)
            
            if elements_with_order:
                for elem_info in elements_with_order:
                    class_name = elem_info.get('className', '').strip()
                    order_value = elem_info.get('order', 0)
                    if class_name and order_value:
                        # Only add if not already in map (computed styles might have duplicates)
                        if class_name not in order_map:
                            order_map[class_name] = int(order_value)
        except Exception as e:
            print(f"Warning: Could not extract order from computed styles: {e}")
        
        # Parse CSS order patterns (EXACT patterns from user's code)
        patterns = [
            r'\.([a-z0-9]+)\{order:(\d+)\}',
            r'\.([a-z0-9]+)\{order:\s*(\d+)\}',
            r'\.([a-z0-9]+)\{order:\s*(\d+);\}',
            r'\.([a-z0-9]+)\s*\{\s*order:\s*(\d+)\s*;?\s*\}',
            # Additional patterns for more CSS formats
            r'\.([a-z0-9_-]+)\s*\{\s*order:\s*(\d+)\s*;?\s*\}',
            r'\.([a-z0-9_-]+)\s*\{\s*order:\s*(\d+)\s*\}',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, css_content, re.IGNORECASE)
            for class_name, order_value in matches:
                class_name = class_name.strip()
                try:
                    order_map[class_name] = int(order_value)
                except ValueError:
                    continue
        
        # Optional: Save CSS to file for debugging (only if we found order values)
        if order_map and len(order_map) > 0:
            try:
                css_debug_path = os.path.join(BASE_DIR, "facebook_css_debug.txt")
                with open(css_debug_path, 'w', encoding='utf-8') as f:
                    f.write("=== EXTRACTED CSS CONTENT ===\n\n")
                    f.write(css_content)
                    f.write("\n\n=== PARSED ORDER MAP ===\n\n")
                    for cls, order in sorted(order_map.items(), key=lambda x: x[1]):
                        f.write(f".{cls} {{ order: {order}; }}\n")
                print(f"Debug: Saved CSS to {css_debug_path}")
            except Exception as e:
                print(f"Warning: Could not save CSS debug file: {e}")
        
        print(f"Found {len(order_map)} order classes in CSS")
        
        # Cache the result
        if use_cache and order_map:
            try:
                current_url = driver.current_url
                _css_order_cache[current_url] = order_map
            except Exception:
                pass
        
    except Exception as e:
        print(f"Warning: Could not parse CSS order values: {e}")
        import traceback
        traceback.print_exc()
    
    return order_map


def parse_html_characters_from_element(driver, timestamp_element, order_map):
    """Extract characters and their order values from HTML spans (using user's EXACT logic).
    Enhanced to also get order from computed styles directly from span elements.
    """
    character_items = []
    try:
        # Method 1: Get order from CSS class map (original method)
        html_content = timestamp_element.get_attribute("outerHTML") or ""
        
        if not html_content:
            html_content = timestamp_element.get_attribute("innerHTML") or ""
        
        if html_content:
            # Find all span elements with their classes and content (EXACT pattern from user's code)
            span_pattern = r'<span[^>]*class="([^"]*)"[^>]*>([^<]+)</span>'
            matches = re.findall(span_pattern, html_content)
            
            for i, (class_attr, char) in enumerate(matches):
                # Clean the character - remove noise
                char_clean = char.strip()
                
                # Skip empty characters and noise
                if not char_clean or char_clean in ['&nbsp;', '\u00A0', ' ', '\n', '\t']:
                    continue
                
                classes = class_attr.split()
                
                # Find which class has an order value (EXACT logic from user's code)
                found_order = None
                for cls in classes:
                    if cls in order_map:
                        found_order = order_map[cls]
                        break
                
                if found_order is not None:
                    character_items.append({
                        'char': char_clean,
                        'order': found_order,
                        'index': i
                    })
        
        # Method 2: Get order directly from span elements via JavaScript (fallback if CSS map is empty)
        if not character_items or len(order_map) == 0:
            try:
                # Get all span elements directly from the DOM
                spans_with_order = driver.execute_script("""
                    var element = arguments[0];
                    var spans = element.querySelectorAll('span');
                    var results = [];
                    
                    for (var i = 0; i < spans.length; i++) {
                        var span = spans[i];
                        var computed = window.getComputedStyle(span);
                        var order = computed.order;
                        
                        // Get text content
                        var text = span.textContent || span.innerText || '';
                        text = text.trim();
                        
                        // Skip empty or whitespace-only spans
                        if (!text || text === '' || text === '\\u00A0' || text === '&nbsp;') {
                            continue;
                        }
                        
                        // Only include if order is set (not 'auto' or '0')
                        if (order && order !== 'auto' && order !== '0') {
                            var orderNum = parseInt(order) || 0;
                            if (orderNum > 0) {
                                results.push({
                                    char: text,
                                    order: orderNum,
                                    index: i
                                });
                            }
                        }
                    }
                    
                    return results;
                """, timestamp_element)
                
                if spans_with_order:
                    # Merge with existing results, avoiding duplicates
                    existing_orders = {item['order']: item for item in character_items}
                    for span_info in spans_with_order:
                        order_val = span_info.get('order', 0)
                        char_text = span_info.get('char', '').strip()
                        
                        # Skip if empty or already exists
                        if not char_text or order_val in existing_orders:
                            continue
                        
                        character_items.append({
                            'char': char_text,
                            'order': order_val,
                            'index': span_info.get('index', len(character_items))
                        })
                        existing_orders[order_val] = character_items[-1]
            
            except Exception as e:
                print(f"Warning: Could not extract order from computed styles: {e}")
        
        # Clean up characters - remove noise patterns
        cleaned_items = []
        for item in character_items:
            char = item['char']
            
            # Skip if character is just whitespace or HTML entities
            if not char or char.strip() == '':
                continue
            
            # Skip if it's just a single special character that's likely noise
            if len(char) == 1 and char in ['·', '•', '|', '·', '·']:
                continue
            
            # Clean HTML entities
            char = char.replace('&nbsp;', ' ').replace('\u00A0', ' ')
            char = char.strip()
            
            if char:
                item['char'] = char
                cleaned_items.append(item)
        
        character_items = cleaned_items
        
        print(f"Found {len(character_items)} characters with order values")
        
    except Exception as e:
        print(f"Warning: Error parsing HTML characters: {e}")
        import traceback
        traceback.print_exc()
    
    return character_items


def reconstruct_timestamp_from_spans(driver, timestamp_element):
    """Reconstruct timestamp from jumbled spans using CSS order values (using user's exact logic)."""
    try:
        # Get CSS order map from the page
        order_map = parse_css_order_from_page(driver)
        print(f"Found {len(order_map)} order classes in CSS")
        
        # Parse characters from HTML using user's exact logic
        # This function will also try to get order from computed styles if CSS map is empty
        character_items = parse_html_characters_from_element(driver, timestamp_element, order_map)
        
        if not character_items:
            print("No characters found with order values (neither from CSS nor computed styles).")
            # Try one more time with a more aggressive approach - get all spans and their computed order
            try:
                print("Attempting fallback: extracting all spans with computed order values...")
                all_spans = timestamp_element.find_elements(By.TAG_NAME, "span")
                for span in all_spans:
                    try:
                        order_val = driver.execute_script(
                            "return parseInt(window.getComputedStyle(arguments[0]).order) || 0;",
                            span
                        )
                        char_text = (span.text or span.get_attribute('textContent') or '').strip()
                        
                        if order_val > 0 and char_text and char_text not in ['&nbsp;', '\u00A0', ' ']:
                            character_items.append({
                                'char': char_text.replace('&nbsp;', ' ').replace('\u00A0', ' '),
                                'order': order_val,
                                'index': len(character_items)
                            })
                    except Exception:
                        continue
                
                if not character_items:
                    print("Still no characters found. Timestamp may not be in jumbled span format.")
                    return None
            except Exception as e:
                print(f"Fallback extraction failed: {e}")
                return None
        
        print(f"\nFound {len(character_items)} characters with order values")
        
        # Sort characters by order value in ascending order (exact logic from user's code)
        sorted_characters = sorted(character_items, key=lambda x: x['order'])
        
        print("\nCharacters sorted by order (ascending) - first 30:")
        for item in sorted_characters[:30]:  # Print first 30 for debugging
            print(f"  Order {item['order']:2d}: '{item['char']}'")
        
        # Form the final string (exact logic from user's code)
        final_string = ''.join(item['char'] for item in sorted_characters)
        
        # Clean up the string (replace &nbsp; with space) - exact logic from user's code
        final_string_clean = final_string.replace('&nbsp;', ' ').replace('\u00A0', ' ')
        
        # Additional noise cleaning
        # Remove excessive whitespace
        final_string_clean = re.sub(r'\s+', ' ', final_string_clean)
        # Remove leading/trailing whitespace
        final_string_clean = final_string_clean.strip()
        
        # Remove common noise patterns
        noise_patterns = [
            r'^[·•|]+',  # Leading bullet points
            r'[·•|]+$',  # Trailing bullet points
        ]
        for pattern in noise_patterns:
            final_string_clean = re.sub(pattern, '', final_string_clean).strip()
        
        print(f"\nFinal sorted string: '{final_string_clean}'")
        
        # Look for timestamp patterns (exact patterns from user's code)
        timestamp_patterns = [
            r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+at\s+(\d{1,2}):(\d{2})',
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+at\s+(\d{1,2}):(\d{2})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})',
            r'(\d{1,2})-(\d{1,2})-(\d{4})\s+(\d{1,2}):(\d{2})',
            r'at\s+(\d{1,2}):(\d{2})',
            r'(\d{1,2}):(\d{2})',
        ]
        
        found_timestamp = None
        for pattern in timestamp_patterns:
            match = re.search(pattern, final_string_clean, re.IGNORECASE)
            if match:
                found_timestamp = match.group()
                print(f"✅ Found timestamp: {found_timestamp}")
                return found_timestamp
        
        if not found_timestamp:
            print("No timestamp pattern found in the sorted string.")
            print("\nTrying to find any time-like patterns...")
            
            # Look for time patterns like HH:MM (exact logic from user's code)
            time_pattern = r'(\d{1,2}):(\d{2})'
            time_matches = re.findall(time_pattern, final_string_clean)
            if time_matches:
                for hour, minute in time_matches:
                    print(f"  Time-like pattern: {hour}:{minute}")
                # Return the cleaned string if it contains time patterns
                return final_string_clean
            
            # Look for date patterns (exact logic from user's code)
            date_pattern = r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)'
            date_matches = re.findall(date_pattern, final_string_clean, re.IGNORECASE)
            if date_matches:
                for day, month in date_matches:
                    print(f"  Date-like pattern: {day} {month}")
                return final_string_clean
        
        # Return the cleaned string if it looks like a timestamp
        if any(month in final_string_clean.lower() for month in ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']):
            return final_string_clean
        if re.search(r'\d{1,2}:\d{2}', final_string_clean):
            return final_string_clean
        
        # Return the cleaned string if it's reasonable length
        if len(final_string_clean) > 5 and len(final_string_clean) < 100:
            return final_string_clean
                    
    except Exception as e:
        print(f"Warning: Could not reconstruct timestamp from spans: {e}")
        import traceback
        traceback.print_exc()
    
    return None


def extract_jumbled_timestamp_text(el, driver=None):
    """Extract jumbled timestamp text from span elements with order values.
    
    This function:
    1. Finds spans that contain jumbled timestamp characters
    2. Extracts each span's character and CSS order value
    3. Groups characters by order value
    4. Joins characters within each order group
    5. Sorts order groups and concatenates them
    
    Args:
        el: Post element containing the timestamp
        driver: Selenium WebDriver instance (required for getting computed styles)
    
    Returns:
        String containing reconstructed jumbled timestamp text, or None if not found
    """
    if not driver:
        print("Warning: Driver required for extracting order values from spans")
        return None
    
    try:
        # Find all spans in the post element
        all_spans = el.find_elements(By.XPATH, ".//span")
        
        if not all_spans:
            return None
        
        # Extract characters with their order values
        character_items = []
        
        for span in all_spans:
            try:
                # Get the character/text from this span
                char_text = span.get_attribute('textContent') or span.text or ''
                char_text = char_text.strip()
                
                # Skip empty spans or HTML entities only
                if not char_text or char_text in ['&nbsp;', '\u00A0', ' ', '\n', '\t']:
                    continue
                
                # Get CSS order value from computed styles
                order_value = driver.execute_script(
                    "var computed = window.getComputedStyle(arguments[0]); "
                    "var order = computed.order; "
                    "return (order && order !== 'auto' && order !== '0') ? parseInt(order) : 0;",
                    span
                )
                
                # Only include spans with valid order values (> 0)
                if order_value and order_value > 0:
                    # Clean the character
                    char_clean = char_text.replace('&nbsp;', ' ').replace('\u00A0', ' ').strip()
                    if char_clean:
                        character_items.append({
                            'char': char_clean,
                            'order': order_value
                        })
            
            except Exception:
                continue
        
        if not character_items:
            print("No spans found with order values")
            return None
        
        print(f"Found {len(character_items)} characters with order values")
        
        # Group characters by order value
        order_groups = {}
        for item in character_items:
            order = item['order']
            char = item['char']
            
            if order not in order_groups:
                order_groups[order] = []
            order_groups[order].append(char)
        
        print(f"Found {len(order_groups)} unique order groups")
        
        # Join characters within each order group
        # For each order, join all characters together
        order_strings = {}
        for order, chars in order_groups.items():
            # Join characters in the order they appear (don't reverse, just join)
            joined = ''.join(chars)
            order_strings[order] = joined
            print(f"  Order {order}: '{joined}' (from {len(chars)} characters)")
        
        # Sort order groups by order value (ascending)
        sorted_orders = sorted(order_strings.keys())
        
        # Concatenate all order groups in sorted order
        reconstructed = ''.join(order_strings[order] for order in sorted_orders)
        
        print(f"Reconstructed string: '{reconstructed}'")
        
        # Validate that we have something meaningful
        if len(reconstructed) < 5:
            print("Reconstructed string too short")
            return None
        
        # Check if it contains timestamp-like patterns
        has_digits = bool(re.search(r'\d', reconstructed))
        has_time_pattern = bool(re.search(r'\d{1,2}:\d{2}', reconstructed))
        has_month = any(month in reconstructed.lower() for month in ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])
        
        if has_digits or has_time_pattern or has_month:
            print(f"✅ Extracted jumbled timestamp with order-based reconstruction: {reconstructed[:100]}...")
            return reconstructed
        else:
            print(f"⚠️ Reconstructed string doesn't look like a timestamp: {reconstructed[:100]}...")
            return reconstructed  # Return anyway, let OpenAI try to solve it
        
    except Exception as e:
        print(f"Warning: Error extracting jumbled timestamp text with order values: {e}")
        import traceback
        traceback.print_exc()
        return None


def clean_timestamp_noise(jumbled_text):
    """Clean noise from jumbled timestamp text using basic pattern matching.
    
    Args:
        jumbled_text: Raw jumbled timestamp text with noise
    
    Returns:
        Cleaned text with noise removed
    """
    if not jumbled_text:
        return ""
    
    # Remove HTML entities
    cleaned = jumbled_text.replace('&nbsp;', ' ').replace('\u00A0', ' ')
    
    # Remove excessive whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Remove leading/trailing special characters that are likely noise
    cleaned = re.sub(r'^[·•|•\s]+', '', cleaned)
    cleaned = re.sub(r'[·•|•\s]+$', '', cleaned)
    
    # Remove standalone special characters (likely noise)
    cleaned = re.sub(r'\s[·•|•]\s', ' ', cleaned)
    
    # Remove very short isolated characters that are likely noise (but keep digits and letters)
    words = cleaned.split()
    filtered_words = []
    for word in words:
        # Keep if it's a digit, letter, colon, or meaningful punctuation
        if len(word) == 1:
            if word.isalnum() or word in [':', '-', '/', '.']:
                filtered_words.append(word)
            # Skip other single characters (likely noise)
        else:
            filtered_words.append(word)
    
    cleaned = ' '.join(filtered_words)
    cleaned = cleaned.strip()
    
    return cleaned


def solve_jumbled_timestamp_with_gemini(jumbled_text):
    """Use OpenAI to solve/reconstruct jumbled timestamp text.
    
    Args:
        jumbled_text: Jumbled timestamp text (may contain noise)
    
    Returns:
        Solved/reconstructed timestamp string, or None if failed
    """
    if not jumbled_text or len(jumbled_text.strip()) < 5:
        return None
    
    # Clean the text first
    cleaned_text = clean_timestamp_noise(jumbled_text)
    
    if not cleaned_text:
        return None
    
    prompt = f"""You are an expert at solving jumbled and obfuscated text. Your task is to reconstruct a Facebook post timestamp from scrambled characters.

The text below contains characters from a Facebook timestamp that have been:
- Split into multiple groups by CSS order values
- Characters within each group may still be scrambled
- May contain noise characters that need to be removed

Jumbled text (already grouped by order, but may still need reordering): {cleaned_text}

INSTRUCTIONS:
1. Analyze the text carefully - it may contain multiple character groups that need to be reordered
2. Identify all characters that belong to a timestamp (digits, letters, colons, spaces, month names)
3. Reorder ALL characters to form a valid, readable timestamp
4. Remove any noise, duplicate characters, or irrelevant text
5. Facebook timestamp formats are typically:
   - "12 January at 14:30"
   - "5 Jan at 8:45 AM"
   - "January 18 at 8:19 AM"
   - "Yesterday at 7:07 PM"
   - "Mon at 9:41 AM"
   - "12/01/2024 at 14:30"
6. The text may need to be reversed, characters reordered, or both
7. Return ONLY the final reconstructed timestamp in readable format
8. If you cannot reconstruct a valid timestamp, return "N/A"

IMPORTANT: The text may appear as character groups (like "pr80i9ar11rhh189a0" or "oo7g7gggo") that need to be decoded and reordered into a proper timestamp.

Return ONLY the solved timestamp (no explanations, no markdown, just the timestamp text):"""

    try:
        if not OPENAI_API_KEY:
            print("Warning: OPENAI_API_KEY is not set. Please add it to your .env file.")
            return None

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

        body = {
            "model": OPENAI_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.1,
            "max_tokens": 256,
        }

        response = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
            timeout=30,
        )
        response.raise_for_status()

        resp_json = response.json()

        # Extract text from OpenAI response
        raw = ""
        if isinstance(resp_json, dict):
            choices = resp_json.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                raw = msg.get("content", "") or ""

        if not raw:
            raw = (response.text or "").strip()

        if not raw:
            print("Warning: Empty response from OpenAI when solving timestamp")
            return None

        # Clean the response
        solved = raw.strip()

        # Remove markdown code blocks if present
        if solved.startswith("```"):
            end_idx = solved.find("```", 3)
            if end_idx != -1:
                solved = solved[3:end_idx].strip()
                if solved.startswith("text") or solved.startswith("timestamp"):
                    solved = solved[4:].strip()

        # Remove quotes if present
        solved = solved.strip('"\'')

        # Validate that it looks like a timestamp
        if solved.lower() in ['n/a', 'na', 'none', 'null', '']:
            return None

        # Check if it contains timestamp-like patterns
        has_time = bool(re.search(r'\d{1,2}:\d{2}', solved))
        has_date = bool(re.search(r'\d', solved)) and any(
            month in solved.lower()
            for month in [
                'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug',
                'sep', 'oct', 'nov', 'dec', 'january', 'february', 'march',
                'april', 'june', 'july', 'august', 'september', 'october',
                'november', 'december'
            ]
        )

        if has_time or has_date:
            print(f"✅ OpenAI solved timestamp: {solved}")
            return solved
        else:
            print(f"⚠️ OpenAI response doesn't look like a timestamp: {solved}")
            return None

    except requests.exceptions.Timeout:
        print("Warning: OpenAI API timed out when solving timestamp")
        return None
    except requests.exceptions.ConnectionError:
        print("Warning: Connection error - cannot reach OpenAI API")
        return None
    except Exception as e:
        print(f"Warning: Error solving timestamp with OpenAI: {e}")
        return None


def extract_post_timestamp(el, driver=None):
    """Extract timestamp from post element."""
    try:
        # Method 1: Try abbr with data-utime attribute (most reliable)
        abbr = el.find_elements(By.XPATH, ".//abbr[@data-utime]")
        if abbr:
            dt_attr = abbr[0].get_attribute('data-utime')
            if dt_attr and dt_attr.isdigit():
                return datetime.fromtimestamp(int(dt_attr)).isoformat()

        # Method 2: Try time element with datetime attribute
        time_elems = el.find_elements(By.XPATH, ".//time[@datetime]")
        if time_elems:
            dt = time_elems[0].get_attribute('datetime')
            if dt:
                try:
                    return datetime.fromisoformat(dt).isoformat()
                except Exception:
                    return dt

        # Method 3: Try abbr with title attribute
        abbr2 = el.find_elements(By.XPATH, ".//abbr[@title]")
        if abbr2:
            title = abbr2[0].get_attribute('title')
            if title:
                return title

        # Method 4: Look for timestamp in aria-label or title attributes
        timestamp_elems = el.find_elements(By.XPATH, ".//*[@aria-label or @title]")
        for elem in timestamp_elems:
            aria_label = elem.get_attribute('aria-label') or ''
            title_attr = elem.get_attribute('title') or ''
            for text in [aria_label, title_attr]:
                if text and len(text) < 100:
                    if any(month in text.lower() for month in ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']):
                        return text
                    if any(pattern in text.lower() for pattern in ['ago', 'hour', 'day', 'week', 'month', 'year', 'minute']):
                        return text

        # Method 5: Extract jumbled timestamp and solve with OpenAI (AI-based solving)
        if driver:
            try:
                jumbled_text = extract_jumbled_timestamp_text(el, driver)
                if jumbled_text:
                    print(f"Extracted jumbled timestamp text: {jumbled_text[:100]}...")
                    solved_timestamp = solve_jumbled_timestamp_with_gemini(jumbled_text)
                    if solved_timestamp:
                        print(f"✅ Solved timestamp using OpenAI: {solved_timestamp}")
                        return solved_timestamp
            except Exception as e:
                print(f"Warning: Error in OpenAI timestamp solving: {e}")
        
        # Method 6: Try to reconstruct from jumbled spans (CSS order logic - fallback)
        if driver:
            # First, try to find the specific span with the known classes that contain jumbled timestamps
            # The span classes: html-span xdj266r x14z9mp xat24cr x1lziwak xexx8yu xyri2b...
            # We'll look for spans that have multiple of these classes
            known_timestamp_classes = ['xdj266r', 'x14z9mp', 'xat24cr', 'x1lziwak', 'xexx8yu', 'xyri2b', 
                                      'x18d9i69', 'x1c1uobl', 'x1hl2dhg', 'x16tdsg8', 'x1vvkbs', 
                                      'x4k7w5x', 'x1h91t0o', 'x1h9r5lt', 'x1jfb8zj', 'xv2umb2', 
                                      'x1beo9mf', 'xaigb6o', 'x12ejxvf', 'x3igimt', 'xarpa2k', 
                                      'xedcshv', 'x1lytzrv', 'x1t2pt76', 'x7ja8zs', 'x1qrby5j']
            
            # Try to find spans with these specific classes (prioritize spans with multiple matching classes)
            all_spans = el.find_elements(By.XPATH, ".//span")
            best_span = None
            best_match_count = 0
            
            for span in all_spans:
                try:
                    span_classes = span.get_attribute("class") or ""
                    # Count how many known timestamp classes this span has
                    match_count = sum(1 for cls in known_timestamp_classes if cls in span_classes)
                    if match_count > best_match_count:
                        # Check if this span has many nested spans (jumbled timestamp indicator)
                        nested_spans = span.find_elements(By.TAG_NAME, "span")
                        if len(nested_spans) > 5:
                            best_match_count = match_count
                            best_span = span
                except Exception:
                    continue
            
            # If we found a good candidate span, try to reconstruct
            if best_span and best_match_count >= 1:  # At least 1 matching class (lowered threshold)
                print(f"Found potential timestamp span with {best_match_count} matching classes")
                # Get a preview of the span's text to verify it's jumbled
                span_text_preview = best_span.get_attribute('textContent') or best_span.text or ''
                print(f"Span text preview (first 100 chars): {span_text_preview[:100]}")
                reconstructed = reconstruct_timestamp_from_spans(driver, best_span)
                if reconstructed:
                    print(f"✅ Reconstructed timestamp from jumbled spans (matched {best_match_count} classes): {reconstructed}")
                    return reconstructed
                else:
                    print(f"⚠️ Could not reconstruct timestamp from span. Check console for details.")
            
            # Also try individual class searches as fallback
            for class_name in known_timestamp_classes[:3]:  # Check first few classes
                try:
                    timestamp_spans = el.find_elements(By.XPATH, f".//span[contains(@class, '{class_name}')]")
                    for span in timestamp_spans:
                        # Check if this span has many nested spans (jumbled timestamp indicator)
                        nested_spans = span.find_elements(By.TAG_NAME, "span")
                        if len(nested_spans) > 5:
                            # This looks like a jumbled timestamp span
                            reconstructed = reconstruct_timestamp_from_spans(driver, span)
                            if reconstructed:
                                print(f"✅ Reconstructed timestamp from jumbled spans: {reconstructed}")
                                return reconstructed
                except Exception:
                    continue
            
            # Fallback: Find elements that might contain timestamp with nested spans
            possible_timestamp_elems = el.find_elements(By.XPATH, ".//*[contains(@class, 'timestamp') or contains(@class, 'time') or contains(@aria-label, 'ago') or contains(@aria-label, 'hour') or contains(@aria-label, 'day')]")
            
            # Also try elements with many nested spans (likely jumbled timestamp)
            # Look for any element that contains jumbled-looking text (single characters separated)
            all_elems = el.find_elements(By.XPATH, ".//*")
            for elem in all_elems:
                try:
                    spans = elem.find_elements(By.TAG_NAME, "span")
                    # If element has many spans (likely jumbled timestamp)
                    if len(spans) > 5:
                        txt = elem.get_attribute('textContent') or elem.text or ''
                        # Check if it looks jumbled (many single characters separated by spaces/newlines)
                        if txt and len(txt) > 10:
                            # Check if text looks jumbled (pattern: single chars separated)
                            # Example: "o s t S e d n o r p 7 y J : 8 3"
                            words = txt.split()
                            if len(words) > 5:
                                # Check if most words are single characters (jumbled indicator)
                                single_char_words = sum(1 for w in words if len(w) == 1)
                                if single_char_words >= len(words) * 0.5:  # 50%+ are single chars
                                    print(f"Found jumbled-looking text: {txt[:50]}...")
                                    reconstructed = reconstruct_timestamp_from_spans(driver, elem)
                                    if reconstructed:
                                        print(f"✅ Reconstructed timestamp from jumbled spans: {reconstructed}")
                                        return reconstructed
                except Exception:
                    continue

        # Method 6: Fallback - extract from text content but clean it properly
        possible = el.find_elements(By.XPATH, ".//*[contains(text(),'at') or contains(text(),',')]")
        for p in possible:
            txt = (p.get_attribute('textContent') or p.text or '').strip()
            txt = ' '.join(txt.split())  # Normalize whitespace
            if len(txt) < 100 and txt:
                if any(month in txt.lower() for month in ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']):
                    return txt
                if any(pattern in txt.lower() for pattern in ['ago', 'hour', 'day', 'week', 'month', 'year', 'minute', 'second']):
                    return txt
                if re.search(r'\d{1,2}:\d{2}', txt):
                    return txt
                    
    except Exception as e:
        print(f"Error extracting timestamp: {e}")
        pass
    return None


def extract_html_div_text(driver, max_posts=20) -> List[Dict]:
    """Extract text from post html-div elements - limit to max_posts for speed."""
    texts = []
    xpath = POST_XPATH
    # Get elements once at the start
    elements = driver.find_elements(By.XPATH, xpath)

    seen = set()
    # Check up to 3x max_posts to account for filtering (some may be page metadata)
    total = min(len(elements), max_posts * 3)
    
    # Process only first max_posts posts with full "See more" clicking
    for index in range(total):
        if len(texts) >= max_posts:
            break
            
        retries = 2
        while retries > 0:
            try:
                el = elements[index]

                # Click "See more" to get full post text (like before)
                try:
                    see_more_xpath = (
                        ".//a[normalize-space(.)='See more'] | .//span[normalize-space(.)='See more'] |"
                        " .//div[normalize-space(.)='See more'] | .//*[@role='button' and contains(., 'See more') ]"
                    )
                    see_more_elems = el.find_elements(By.XPATH, see_more_xpath)
                    for sme in see_more_elems:
                        try:
                            if sme.is_displayed():
                                driver.execute_script("arguments[0].click();", sme)
                                time.sleep(0.25)  # Wait for text to expand
                        except Exception:
                            continue
                except Exception:
                    pass

                # Extract text from dir="auto" div (contains post content)
                raw = ''
                try:
                    # Find all dir="auto" divs inside this post element
                    dir_auto_divs = el.find_elements(By.XPATH, ".//div[@dir='auto']")
                    
                    if dir_auto_divs:
                        # If multiple dir="auto" divs found, use the one with most text (likely the main content)
                        content_div = max(dir_auto_divs, key=lambda d: len(d.get_attribute("innerText") or d.text or ""))
                        raw = content_div.get_attribute("innerText") or content_div.text or ''
                    else:
                        # Fallback: if no dir="auto" div found, use the element itself
                        raw = el.get_attribute("innerText") or el.text or ''
                except Exception as e:
                    # Fallback to original method if something goes wrong
                    raw = el.get_attribute("innerText") or el.text or ''
                
                raw = re.sub(r"(?i)see more(?:\.{0,3})", "", raw)
                
                # Clean raw text - remove only the most obvious UI noise but otherwise keep it
                raw_clean = re.sub(r"(?i)(notificationsallunreadnew|see all unread|see all notifications)", "", raw)
                # Keep original newlines for possible future use, but also have a compact version
                raw_compact = re.sub(r"\s+", " ", raw_clean).strip()
                
                # Try to filter, but if it fails, fall back to using the raw text so we don't drop posts
                processed = filter_post_text(raw)
                
                if not processed:
                    # Very permissive fallback: as long as there is some reasonable-length text,
                    # treat this element as a post so it appears in the output.
                    base_text = raw_compact or raw_clean.strip()
                    if not base_text or len(base_text) < 10:
                        break  # Too short to be meaningful, try next element
                    
                    processed = {
                        'caption': base_text[:200],
                        'hashtags': [],
                        'urls': [],
                        'mentions': [],
                        'raw': base_text
                    }
                
                if processed:
                    # Extract timestamp (pass driver for span reconstruction)
                    ts = extract_post_timestamp(el, driver=driver)
                    processed['timestamp'] = ts

                    # Extract a best-guess post URL from links inside this post element
                    post_url = ""
                    try:
                        link_elems = el.find_elements(By.XPATH, ".//a[@href]")
                        for a in link_elems:
                            href = a.get_attribute("href") or ""
                            href_low = href.lower()
                            if "facebook.com" not in href_low:
                                continue
                            # Heuristics for post permalinks
                            if any(token in href_low for token in [
                                "/posts/",
                                "/photos/",
                                "/photo/",
                                "/videos/",
                                "/video/",
                                "/reel/",
                                "/permalink/",
                                "story_fbid",
                                "fbid="
                            ]):
                                post_url = href
                                break
                    except Exception:
                        post_url = ""

                    processed["post_url"] = post_url

                    # Use a shorter, more lenient key for deduplication
                    # Use first 60 chars to allow slight variations
                    caption = processed.get('caption', '')
                    raw_text = processed.get('raw', '')
                    
                    # Create a simple key from first part of text
                    key_text = caption[:60] if caption else raw_text[:60]
                    # Allow shorter keys so we don't drop short-but-real posts
                    if not key_text or len(key_text.strip()) < 5:
                        break  # Try next element
                    
                    # Normalize the key (remove extra spaces, lowercase)
                    key = re.sub(r"\s+", " ", key_text.lower()).strip()
                    
                    # Only skip if it's an exact match (very lenient)
                    if key and key not in seen:
                        seen.add(key)
                        texts.append(processed)
                        break  # Successfully added, move to next
                break
            except StaleElementReferenceException:
                retries -= 1
                time.sleep(0.2)
                continue
            except Exception:
                break

    return texts


def scroll_to_load_all(driver, xpath=POST_XPATH, max_scrolls=100, pause=2.5, stable_threshold=3, target_count=None):
    """Scroll page to load all posts."""
    last_count = 0
    stable = 0
    # Optimize: reduce pause time for faster scrolling
    optimized_pause = max(1.0, pause * 0.6)  # Reduce pause by 40%
    
    for i in range(max_scrolls):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(optimized_pause)

        try:
            elems = driver.find_elements(By.XPATH, xpath)
            count = len(elems)
        except Exception:
            count = last_count

        if count > last_count:
            last_count = count
            stable = 0
            # If we have enough elements and target_count is specified, stop early
            if target_count and count >= target_count * 2:  # Get 2x to account for filtering
                break
        else:
            stable += 1
            if stable >= stable_threshold:
                break

    return last_count


def scrape_facebook_page(fb_url: str, target_count: int = 30, headless: bool = False) -> pd.DataFrame:
    """
    Scrape Facebook page posts and return as DataFrame.
    
    Args:
        fb_url: Facebook page URL (e.g., https://www.facebook.com/Vishaal.Mall/)
        target_count: Maximum number of posts to extract
        headless: Run browser in headless mode (not recommended for Facebook)
    
    Returns:
        DataFrame with columns: shop_name, phone, floor
        (shop_name will contain post captions/content, phone/floor will be extracted if found)
    """
    driver = None
    try:
        driver = create_driver(headless=True)
        wait = WebDriverWait(driver, 30)

        # Navigate to Facebook login page
        driver.get("https://www.facebook.com/")

        # Try to load cookies first
        if not load_cookies(driver):
            driver.refresh()
            # If cookies not loaded, user needs to login manually
            try:
                WebDriverWait(driver, 6).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']"))
                )
                print("Already logged in")
            except TimeoutException:
                # Wait for manual login
                print("Please login to Facebook in the browser window...")
                input("Press ENTER after you have logged in and solved any CAPTCHA...")
        else:
            driver.refresh()
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']"))
                )
            except TimeoutException:
                print("Please login to Facebook in the browser window...")
                input("Press ENTER after you have logged in and solved any CAPTCHA...")

        save_cookies(driver)

        # Navigate to target Facebook page
        driver.get(fb_url)
        time.sleep(6)

        page_url = driver.current_url
        try:
            page_name = wait.until(EC.presence_of_element_located((By.XPATH, "//h1//span"))).text
        except Exception:
            page_name = driver.title or "Facebook Page"

        # Scroll to load posts
        print(f"Loading posts from {page_name}...")
        final_count = scroll_to_load_all(driver, xpath=POST_XPATH, max_scrolls=120, pause=2.5, stable_threshold=4)
        print(f"Loaded {final_count} post elements. Extracting posts...")

        # Extract posts (limit to 20 for good coverage, with full "See more" clicking)
        all_posts = extract_html_div_text(driver, max_posts=20)
        
        # Process and deduplicate
        collected = []
        seen = set()
        for p in all_posts:
            raw = p.get('raw') or ''
            norm = re.sub(r"\s+", " ", raw).strip()
            if not norm:
                continue
            key = norm.lower()
            if key not in seen:
                seen.add(key)
                collected.append(p)
                if len(collected) >= target_count:
                    break

        print(f"Extracted {len(collected)} posts from Facebook page")

        # Convert to DataFrame format compatible with shop data
        # Extract shop names/business mentions from post content
        rows = []
        for post in collected:
            caption = post.get('caption', '')
            # Try to extract shop/business names from caption
            # Look for capitalized words or business-like patterns
            shop_name = caption[:200] if caption else "Facebook Post"  # Use first 200 chars as shop_name
            phone = "-"  # Facebook posts typically don't have phone numbers
            floor = "-"  # Facebook posts typically don't have floor info
            
            rows.append({
                'shop_name': shop_name,
                'phone': phone,
                'floor': floor,
                'source': 'Facebook Page'
            })

        df = pd.DataFrame(rows, columns=['shop_name', 'phone', 'floor', 'source'])
        return df

    except Exception as e:
        print(f"Error scraping Facebook page: {e}")
        return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def scrape_facebook_simple(fb_url: str, target_count: int = 20) -> pd.DataFrame:
    """
    Scrape Facebook page with automatic login using credentials from .env file.
    For use in Streamlit app.
    """
    driver = None
    try:
        # Get credentials from environment
        login_id = os.getenv("FB_LOGIN")
        password = os.getenv("FB_PASSWORD")
        
        if not login_id or not password:
            print("Error: FB_LOGIN and FB_PASSWORD must be set in .env file")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        
        driver = create_driver(headless=True)
        wait = WebDriverWait(driver, 30)

        # Navigate to Facebook login page (skip waiting for full load - start immediately)
        print("Navigating to Facebook...")
        driver.get("https://www.facebook.com/")
        
        # Minimal wait - don't wait for full page load, start checking immediately
        time.sleep(0.5)  # Minimal wait for initial render
        
        # Check current page state
        current_url = driver.current_url
        print(f"Loaded Facebook page: {current_url}")
        
        # Try loading cookies first
        logged_in = False
        if load_cookies(driver):
            driver.refresh()
            time.sleep(0.5)  # Minimal wait - start checking immediately
            
            # Check if already logged in with cookies - try multiple indicators
            login_indicators = [
                (By.XPATH, "//input[@aria-label='Search Facebook']"),
                (By.XPATH, "//input[contains(@placeholder, 'Search')]"),
                (By.XPATH, "//a[contains(@href, '/me')]"),  # Profile link
                (By.XPATH, "//div[contains(@aria-label, 'Your profile')]"),
                (By.XPATH, "//span[text()='Home']"),
            ]
            
            for indicator_type, indicator_value in login_indicators:
                try:
                    WebDriverWait(driver, 1).until(  # Reduced to 1s for faster startup
                        EC.presence_of_element_located((indicator_type, indicator_value))
                    )
                    logged_in = True
                    print("Logged in using cookies")
                    break
                except TimeoutException:
                    continue
            
            # Also check URL - if we're not on login page, might be logged in
            if not logged_in and "login" not in driver.current_url.lower():
                try:
                    # Try to find any logged-in indicator
                    driver.find_element(By.XPATH, "//body")
                    if "facebook.com/login" not in driver.current_url:
                        logged_in = True
                        print("Logged in using cookies (detected by URL)")
                except Exception:
                    pass
        
        # If not logged in, perform login (using the working approach from original code)
        if not logged_in:
            print("Logging in with credentials from .env file...")
            try:
                # Wait a bit for page to stabilize
                time.sleep(2)
                
                # First check if we're already shown the logged-in search box (short wait)
                try:
                    WebDriverWait(driver, 2).until(  # Reduced to 2s for faster startup
                        EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']"))
                    )
                    print("Already logged in (search box found)")
                    logged_in = True
                except TimeoutException:
                    # Try multiple selectors for the email field (Facebook may change attributes)
                    email_el = None
                    try:
                        email_el = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.NAME, "email")))  # Reduced for faster startup
                    except TimeoutException:
                        try:
                            email_el = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.ID, "email")))  # Reduced for faster startup
                        except TimeoutException:
                            try:
                                email_el = WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.XPATH, "//input[@type='email']")))  # Reduced for faster startup
                            except TimeoutException:
                                # Save debug info to help diagnose layout or blocking issues
                                print("Login fields not found within timeout. Saving debug snapshot.")
                                try:
                                    screenshot_path = os.path.join(BASE_DIR, "fb_login_debug.png")
                                    driver.save_screenshot(screenshot_path)
                                    html_path = os.path.join(BASE_DIR, "fb_login_page.html")
                                    with open(html_path, "w", encoding="utf-8") as f:
                                        f.write(driver.page_source)
                                    print(f"Saved debug files: {screenshot_path}, {html_path}")
                                except Exception:
                                    pass
                                print("Error: Could not find email field. Facebook page structure may have changed.")
                                return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
                    
                    # Fill email and password
                    email_el.clear()
                    email_el.send_keys(login_id)
                    print("Email entered")
                    
                    try:
                        pass_el = WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.NAME, "pass")))
                    except TimeoutException:
                        try:
                            pass_el = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.ID, "pass")))
                        except TimeoutException:
                            pass_el = WebDriverWait(driver, 6).until(EC.presence_of_element_located((By.XPATH, "//input[@type='password']")))
                    
                    pass_el.send_keys(password + Keys.RETURN)
                    print("Password entered, submitted login form")
                    
                    # Wait a bit for login to process
                    time.sleep(5)
                    
                    # Check for CAPTCHA - in headless mode, we'll wait longer
                    if "captcha" in driver.page_source.lower() or "security check" in driver.page_source.lower() or "checkpoint" in driver.page_source.lower():
                        print("CAPTCHA or security check detected. Waiting up to 60 seconds for resolution...")
                        # In headless mode, we can't manually solve, so we wait and hope it auto-resolves
                        # Or the user needs to solve it in a visible browser first to get cookies
                        try:
                            WebDriverWait(driver, 60).until(
                                EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']"))
                            )
                            logged_in = True
                            print("Login successful after CAPTCHA wait")
                            save_cookies(driver)
                        except TimeoutException:
                            print("Login failed: CAPTCHA not resolved within timeout. Please login manually once to create cookies.")
                            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
                
                # Find password field
                pass_el = None
                password_selectors = [
                    (By.ID, "pass"),
                    (By.NAME, "pass"),
                    (By.XPATH, "//input[@type='password']"),
                    (By.XPATH, "//input[@id='pass']"),
                    (By.XPATH, "//input[@name='pass']"),
                    (By.XPATH, "//input[@placeholder='Password']"),
                    (By.XPATH, "//input[@aria-label='Password']"),
                ]
                
                for selector_type, selector_value in password_selectors:
                    try:
                        pass_el = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((selector_type, selector_value))
                        )
                        if pass_el.is_displayed() and pass_el.is_enabled():
                            print(f"Found password field using: {selector_type}={selector_value}")
                            break
                        else:
                            pass_el = None
                    except (TimeoutException, Exception):
                        continue
                
                if pass_el is None:
                    # Try to find password field by scanning
                    try:
                        all_inputs = driver.find_elements(By.XPATH, "//input[@type='password']")
                        for inp in all_inputs:
                            if inp.is_displayed() and inp.is_enabled():
                                pass_el = inp
                                print("Found password field by scanning")
                                break
                    except Exception:
                        pass
                
                if pass_el is None:
                    print("Error: Could not find password field")
                    return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
                
                # Fill password
                try:
                    pass_el.clear()
                    time.sleep(0.5)
                    pass_el.send_keys(password)
                    time.sleep(1)
                except Exception as e:
                    print(f"Error filling password field: {e}")
                    return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
                
                # Click login button or press Enter
                login_success = False
                login_button_selectors = [
                    (By.NAME, "login"),
                    (By.ID, "loginbutton"),
                    (By.XPATH, "//button[@type='submit']"),
                    (By.XPATH, "//button[contains(text(), 'Log in')]"),
                    (By.XPATH, "//button[contains(text(), 'Log In')]"),
                    (By.XPATH, "//input[@type='submit']"),
                    (By.XPATH, "//button[@name='login']"),
                ]
                
                for selector_type, selector_value in login_button_selectors:
                    try:
                        login_btn = driver.find_element(selector_type, selector_value)
                        if login_btn.is_displayed() and login_btn.is_enabled():
                            login_btn.click()
                            login_success = True
                            print(f"Clicked login button using: {selector_type}={selector_value}")
                            break
                    except Exception:
                        continue
                
                if not login_success:
                    # Try pressing Enter as fallback
                    try:
                        pass_el.send_keys(Keys.RETURN)
                        print("Pressed Enter to submit login")
                    except Exception:
                        pass
                
                # Wait for login to complete (check for search box or CAPTCHA)
                time.sleep(5)
                
                # Check if login was successful or if CAPTCHA is required
                try:
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']"))
                    )
                    logged_in = True
                    print("Login successful")
                    save_cookies(driver)
                except TimeoutException:
                    # Check if CAPTCHA is present
                    page_source_lower = driver.page_source.lower()
                    if "captcha" in page_source_lower or "security check" in page_source_lower or "checkpoint" in page_source_lower:
                        print("CAPTCHA or security check detected. Waiting for manual resolution...")
                        # Wait up to 60 seconds for user to solve CAPTCHA
                        try:
                            WebDriverWait(driver, 60).until(
                                EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']"))
                            )
                            logged_in = True
                            save_cookies(driver)
                            print("Login successful after CAPTCHA")
                        except TimeoutException:
                            print("Login failed: CAPTCHA not resolved within timeout period")
                            print("Please ensure you solve the CAPTCHA in the browser window when it appears")
                            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
                    else:
                        print("Login failed - unable to verify login status")
                        print(f"Current URL: {driver.current_url}")
                        # Check if we're on a different page that might indicate login issues
                        if "login" in driver.current_url.lower() or "checkpoint" in driver.current_url.lower():
                            print("Still on login/checkpoint page - login may have failed")
                        return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
                        
            except Exception as e:
                print(f"Error during login: {e}")
                return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])
        
        if not logged_in:
            print("Could not log in to Facebook")
            return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source'])

        # Wait until logged-in search box is present before continuing
        wait.until(EC.presence_of_element_located((By.XPATH, "//input[@aria-label='Search Facebook']")))
        save_cookies(driver)
        print("Logged in successfully")

        # Navigate to target Facebook page directly (optimized)
        print(f"Opening Facebook page: {fb_url}")
        driver.get(fb_url)
        time.sleep(1.5)  # Reduced for faster startup

        # Get page name
        page_url = driver.current_url
        try:
            page_name = wait.until(EC.presence_of_element_located((By.XPATH, "//h1//span"))).text
        except Exception:
            page_name = driver.title or "Facebook Page"
        print(f"\nOpened Page: {page_name}\n")

        # Collect posts by scrolling thoroughly (optimized for speed)
        collected = []
        seen = set()
        max_scrolls = 80  # Reduced from 120 - enough to get 20 posts
        pause = 1.5  # Reduced from 2.5 for faster scrolling
        stable_threshold = 3  # Reduced from 4 to stop earlier
        print(f"Scrolling to load posts (max {max_scrolls} scrolls)...")
        final_count = scroll_to_load_all(driver, xpath=POST_XPATH, max_scrolls=max_scrolls, pause=pause, stable_threshold=stable_threshold, target_count=target_count)
        print(f"Finished scrolling; {final_count} post elements present. Extracting posts...")

        # Extract posts. Ask extractor for more than we finally need so that
        # filtering/dedup still leaves us at least target_count posts that have
        # real per-post URLs (not just the page URL).
        max_posts_to_extract = min(120, max(target_count * 4, 40))
        all_posts = extract_html_div_text(driver, max_posts=max_posts_to_extract)
        added = 0
        
        # Since extract_html_div_text already does deduplication, we can be more lenient here
        # Just collect all posts that passed the filter
        for p in all_posts:
            raw = p.get('raw') or ''
            caption = p.get('caption', '')
            
            # Use caption if available, otherwise raw
            text_to_check = caption if caption else raw
            norm = re.sub(r"\s+", " ", text_to_check).strip()
            
            # Only skip if text is too short (very lenient threshold)
            if not norm or len(norm) < 10:
                continue
            
            # Add all posts - deduplication already happened in extract_html_div_text
            # Use a simple key based on first 60 chars for final check
            key = norm.lower()[:60].strip()
            
            # Only skip if we've seen this exact short key (very lenient)
            if key not in seen:
                seen.add(key)
                collected.append(p)
                added += 1
                if len(collected) >= target_count:
                    break

        print(f"Extracted {len(all_posts)} posts from elements, added {added} to collection, total collected {len(collected)}")

        # Convert to DataFrame with source column indicating Facebook post data.
        # IMPORTANT CHANGE:
        #   Do NOT drop posts just because we couldn't extract a clean per-post URL.
        #   We keep every meaningful post we collected so that:
        #     - Facebook Scratch tab always shows all scraped posts
        #     - Existing Tennent Research tab can still use the text for matching
        rows = []
        for post in collected:
            caption = post.get('caption', '') or ''
            raw_text = post.get('raw', '') or caption
            timestamp = post.get('timestamp', '')  # Get timestamp if available
            hashtags = post.get('hashtags', []) or []
            hashtags_str = " ".join(hashtags) if hashtags else ""

            # Build display text = caption + hashtags (so #tags are visible in Excel)
            display_text = caption or raw_text or ''
            if hashtags_str:
                display_text = f"{display_text} {hashtags_str}".strip()
            
            # If we somehow still don't have any meaningful text, skip this one
            if not display_text.strip():
                continue

            # Keep post URL if we found one, but do NOT require it
            detected_post_url = (post.get('post_url') or '').strip()

            rows.append({
                'shop_name': display_text[:300],
                'phone': '-',  # Keep phone field neutral for compatibility
                'floor': '-',
                'source': 'Facebook Post Data',  # Clear heading for Facebook data
                'post_text': display_text,  # Full post text + hashtags
                'post_date': timestamp if timestamp else '',  # Post date/timestamp
                # May be empty if we couldn't extract a clean per-post URL,
                # but row is still kept so no data is omitted.
                'post_url': detected_post_url,
            })

            if len(rows) >= target_count:
                break

        # Create DataFrame with all columns
        df = pd.DataFrame(rows)
        
        # Ensure required columns exist for compatibility
        required_cols = ['shop_name', 'phone', 'floor', 'source']
        for col in required_cols:
            if col not in df.columns:
                df[col] = ''
        
        # Add optional columns if they don't exist
        if 'post_text' not in df.columns:
            df['post_text'] = df.get('shop_name', '')
        if 'post_date' not in df.columns:
            df['post_date'] = ''
        
        return df

    except Exception as e:
        print(f"Error in Facebook scraping: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame(columns=['shop_name', 'phone', 'floor', 'source', 'post_text', 'post_date'])
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

