import os
import time
import csv
import re
import json
import argparse
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# Config
DEFAULT_OUTPUT_CSV = "mall_shops.csv"
DEFAULT_OUTPUT_TEXT = "mall_shops.txt"
HEADLESS = os.getenv("HEADLESS", "1") == "1"

# Cache ChromeDriver path to speed up startup (only install once)
_cached_chromedriver_path = None

def get_chromedriver_path():
    """Get ChromeDriver path, caching it to avoid re-downloading."""
    global _cached_chromedriver_path
    if _cached_chromedriver_path is None:
        _cached_chromedriver_path = ChromeDriverManager().install()
    return _cached_chromedriver_path


def create_driver():
    options = Options()
    if HEADLESS:
        # new headless mode flag is supported in newer Chrome builds
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

    driver = webdriver.Chrome(
        service=Service(get_chromedriver_path()),  # Use cached path for faster startup
        options=options,
    )
    return driver


def extract_category_links_from_soup(soup, base_url=""):
    """Extract category links from action-card elements.
    
    Returns a list of (category_name, category_url) tuples.
    """
    category_links = []
    cards = soup.select(".action-card")
    
    for card in cards:
        # Find link in the card (could be .cover-link, a tag, or any link)
        link_elem = card.select_one("a, .cover-link, [href]")
        if link_elem:
            href = link_elem.get("href") or ""
            if not href:
                continue
            
            # Convert relative URLs to absolute
            if href.startswith("/"):
                href = urljoin(base_url, href)
            elif not href.startswith("http"):
                continue
            
            # Get category name from title
            title_elem = card.select_one(".title, h2.title, h3.title, h4.title")
            category_name = title_elem.get_text(strip=True) if title_elem else href
            
            if href and href not in [url for _, url in category_links]:
                category_links.append((category_name, href))
    
    return category_links


def detect_alphabetical_listing_page(soup):
    """Detect if page has alphabetical shop listing structure.
    
    Checks for common patterns like alphabetical navigation, link-based listings,
    or retailers/stores pages with alphabetical organization.
    """
    # Check for alphabetical navigation (A-Z links)
    alpha_nav = soup.select("a[href*='#'], a[href*='?letter='], a[href*='&letter=']")
    if alpha_nav:
        # Check if there are multiple single-letter links (A-Z navigation)
        single_letters = [a for a in alpha_nav if len(a.get_text(strip=True)) == 1 and a.get_text(strip=True).isalpha()]
        if len(single_letters) >= 5:  # At least 5 letters suggests alphabetical nav
            return True
    
    # Check for retailers/stores page with many links
    retailers_links = soup.select("a[href*='/retailers'], a[href*='/stores'], a[href*='/shop']")
    if len(retailers_links) > 20:  # Many shop links suggests alphabetical listing
        return True
    
    # Check for common alphabetical listing patterns in page structure
    page_text = soup.get_text().lower()
    if ("retailers" in page_text or "stores" in page_text) and len(retailers_links) > 10:
        return True
    
    return False


def extract_shops_from_brand_card_grid_component(soup):
    """Extract shops specifically from BrandCardGrid_component__bXmSV class.
    
    This targets the exact class structure used by Westfield and similar sites.
    """
    shops = []
    seen = set()
    phone_re = re.compile(r"(\+?\d[\d\-\s\(\)]{6,}\d)")
    
    # Find the specific BrandCardGrid component
    brand_card_grid = soup.select_one(".BrandCardGrid_component__bXmSV")
    
    if not brand_card_grid:
        # Try with partial match in case the hash changes
        brand_card_grid = soup.select_one("[class*='BrandCardGrid_component']")
    
    if not brand_card_grid:
        return []
    
    # Find all shop cards within the grid
    # Look for links or divs that contain shop information
    # Try multiple selectors to find shop cards
    shop_cards = brand_card_grid.select("a[href*='/retailers'], a[href*='/shop'], a[href*='/store'], [class*='BrandCard'], [class*='card'], [class*='shop'], [class*='store'], [class*='retailer']")
    
    # If no cards found with those selectors, try finding all links and divs
    if not shop_cards:
        shop_cards = brand_card_grid.find_all(["a", "div", "li"], recursive=True)
    
    for card in shop_cards:
        # Extract shop name from the card
        shop_name = ""
        
        # Try multiple strategies to get shop name
        # 1. Check for content header or title
        content_header = card.select_one("[class*='contentHeader'], [class*='content-header'], [class*='header'], [class*='title'], h2, h3, h4")
        if content_header:
            shop_name = content_header.get_text(strip=True)
        
        # 2. Check for brand card content
        if not shop_name:
            content = card.select_one("[class*='BrandCard_content'], [class*='content'], [class*='name']")
            if content:
                shop_name = content.get_text(strip=True)
        
        # 3. Check link text or aria-label
        if not shop_name:
            shop_name = card.get_text(strip=True)
            if not shop_name:
                shop_name = card.get("aria-label") or card.get("title") or ""
        
        # Clean and validate shop name
        if not shop_name or len(shop_name) < 2:
            continue
        
        # Skip if it's navigation/UI text
        skip_texts = ["closed", "open", "see more", "learn more", "shop", "store", "visit",
                     "home", "about", "contact", "hours", "directions", "menu", "cart",
                     "search", "sign in", "sign up", "login", "filters", "shops", "retailers",
                     "get your latest", "from our line-up", "brands"]
        if any(skip in shop_name.lower() for skip in skip_texts):
            continue
        
        # Skip single characters or numbers
        if len(shop_name) == 1 or shop_name.isdigit():
            continue
        
        # Must contain at least one letter
        if not re.search(r'[a-zA-Z]', shop_name):
            continue
        
        # Remove "Closed" suffix if present
        shop_name = shop_name.replace("Closed", "").strip()
        if shop_name.lower().endswith("closed"):
            shop_name = shop_name[:-6].strip()
        
        if not shop_name or len(shop_name) < 2:
            continue
        
        # Skip duplicates
        name_key = shop_name.lower()
        if name_key in seen:
            continue
        seen.add(name_key)
        
        # Extract phone number from card
        phone = ""
        card_text = card.get_text(separator=" ", strip=True)
        phone_match = phone_re.search(card_text)
        if phone_match:
            phone = phone_match.group(1)
        
        # Extract floor information
        floor = ""
        floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth|level \d)", card_text, re.I)
        if floor_match:
            floor = floor_match.group(0)
        
        # Extract image URL
        image_url = ""
        img = card.find("img")
        if img:
            image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if image_url.startswith("//"):
                image_url = "https:" + image_url
        
        shops.append({
            "shop_name": shop_name,
            "phone": phone,
            "floor": floor,
            "image_url": image_url,
        })
    
    return shops


def extract_shops_from_brand_card_grid(soup):
    """Extract shops from BrandCard grid structure (generic for multiple malls).
    
    Looks for common BrandCard CSS class patterns:
    - BrandCardGrid_component, BrandCardGrid_grid
    - BrandCardGrid_cardLink, BrandCard_brandCard
    - BrandCard_content, BrandCard_contentHeader
    """
    shops = []
    seen = set()
    phone_re = re.compile(r"(\+?\d[\d\-\s\(\)]{6,}\d)")
    
    # Strategy: Look for BrandCard elements using partial class name matching
    # This works even if class names have dynamic suffixes
    
    # Find BrandCard grid containers
    brand_card_grids = soup.select("[class*='BrandCardGrid'], [class*='brand-card-grid'], [class*='BrandCard']")
    
    for grid in brand_card_grids:
        # Find all card links within the grid
        card_links = grid.select("a[class*='cardLink'], a[class*='card-link'], a[class*='BrandCard']")
        
        for card_link in card_links:
            # Extract shop name from the card
            shop_name = ""
            
            # Try to get name from various locations in the card structure
            # 1. Check for content header (most common location for shop name)
            content_header = card_link.select_one("[class*='contentHeader'], [class*='content-header'], [class*='header']")
            if content_header:
                shop_name = content_header.get_text(strip=True)
            
            # 2. Check for brand card content
            if not shop_name:
                content = card_link.select_one("[class*='BrandCard_content'], [class*='brand-card-content'], [class*='content']")
                if content:
                    # Get first significant text from content
                    all_text = content.get_text(separator="\n", strip=True)
                    lines = [line.strip() for line in all_text.split("\n") if line.strip()]
                    if lines:
                        shop_name = lines[0]
            
            # 3. Check for brand card itself
            if not shop_name:
                brand_card = card_link.select_one("[class*='BrandCard_brandCard'], [class*='brand-card']")
                if brand_card:
                    shop_name = brand_card.get_text(strip=True)
            
            # 4. Fallback to link text or aria-label
            if not shop_name:
                shop_name = card_link.get_text(strip=True)
                if not shop_name:
                    shop_name = card_link.get("aria-label") or card_link.get("title") or ""
            
            # Clean and validate shop name
            if not shop_name or len(shop_name) < 2:
                continue
            
            # Skip if it's navigation/UI text
            skip_texts = ["closed", "open", "see more", "learn more", "shop", "store", "visit",
                         "home", "about", "contact", "hours", "directions", "menu", "cart",
                         "search", "sign in", "sign up", "login", "filters", "shops", "retailers"]
            if any(skip in shop_name.lower() for skip in skip_texts):
                continue
            
            # Skip single characters
            if len(shop_name) == 1:
                continue
            
            # Skip if it's a number
            if shop_name.isdigit():
                continue
            
            # Must contain at least one letter
            if not re.search(r'[a-zA-Z]', shop_name):
                continue
            
            # Remove "Closed" suffix if present
            shop_name = shop_name.replace("Closed", "").strip()
            if shop_name.lower().endswith("closed"):
                shop_name = shop_name[:-6].strip()
            
            if not shop_name or len(shop_name) < 2:
                continue
            
            # Skip duplicates
            name_key = shop_name.lower()
            if name_key in seen:
                continue
            seen.add(name_key)
            
            # Extract phone number from card
            phone = ""
            card_text = card_link.get_text(separator=" ", strip=True)
            phone_match = phone_re.search(card_text)
            if phone_match:
                phone = phone_match.group(1)
            
            # Extract floor information
            floor = ""
            floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth|level \d)", card_text, re.I)
            if floor_match:
                floor = floor_match.group(0)
            
            # Extract image URL
            image_url = ""
            img = card_link.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
            
            shops.append({
                "shop_name": shop_name,
                "phone": phone,
                "floor": floor,
                "image_url": image_url,
            })
    
    return shops


def extract_shops_from_alphabetical_listing(soup):
    """Extract shops from alphabetical listing page structure.
    
    Handles websites that list shops alphabetically in a link-based format.
    """
    shops = []
    seen = set()
    phone_re = re.compile(r"(\+?\d[\d\-\s\(\)]{6,}\d)")
    
    # Strategy 0: Try BrandCard grid structure first (most specific)
    brand_card_shops = extract_shops_from_brand_card_grid(soup)
    if brand_card_shops:
        print(f"Found {len(brand_card_shops)} shops using BrandCard grid extraction")
        shops.extend(brand_card_shops)
        seen.update(shop["shop_name"].lower() for shop in brand_card_shops)
    
    # Common navigation/UI text to skip (generic - no mall-specific names)
    skip_texts = ["Closed", "Open", "See More", "Learn More", "Shop", "Store", "Visit", 
                  "Home", "About", "Contact", "Hours", "Directions", "Menu", "Cart", 
                  "Search", "Sign In", "Sign Up", "Login", "Filters", "ABCDEFGHIJKLMNOPQRSTUVWXYZ0-9",
                  "Get your latest", "Stores", "Food & Drink", "Entertainment", "Services",
                  "Events", "Offers", "Movies", "Map of the center", "Access", "Parking",
                  "Opening Hours", "Sustainable Development", "Subscribe", "Change center",
                  "Lunar New Year", "Our centers", "Our centers in the United States", "shops", 
                  "Retailers", "Retailer", "Management Office", "Legal Information", "Company",
                  "Get your latest looks and styles", "from our line-up brands",
                  # Legal/Terms text
                  "Terms and Conditions", "Terms & Conditions", "Terms", "Conditions",
                  "SMS Terms", "Privacy Notice", "Privacy Policy", "Privacy",
                  "Legal Mentions", "Legal Information", "Legal",
                  # Corporate/Company text
                  "Westfield Group URW", "Group URW", "URW", "Advertise With Westfield Rise",
                  "Advertise With", "Advertise", "Careers", "Career", "Jobs", "Job",
                  "Leasing Opportunities", "Leasing", "Download", "More information",
                  # Cookie/Privacy text
                  "Cookie", "Cookies", "Privacy", "Consent", "Opt Out", "Vendor", "Vendors",
                  "Strictly Necessary", "Functional Cookies", "Performance Cookies", "Targeting Cookies",
                  "Social Media Cookies", "Always Active", "Reject All", "Allow All", "Accept",
                  "View Vendor Details", "List of IAB Vendors", "Your Privacy", "Confirm My Choices",
                  # UI Elements
                  "Button", "Label", "Checkbox", "Filter Button", "Back Button", "Vendors List",
                  "Apply", "Cancel", "Clear", "Show Purposes",
                  # Data usage text
                  "partners can use", "can use this purpose", "can use this feature",
                  "Measure content performance", "Measure advertising performance",
                  "Use limited data", "Create profiles", "personalised", "Link different devices",
                  "Performance: to measure site traffic", "Performance:", "to measure site traffic",
                  # Footer/Copyright
                  "My account", "Account", "©", "Copyright"]
    
    # Strategy 1: Look for links that might be shop names
    # Alphabetical listing pages typically list shops as links
    all_links = soup.find_all("a", href=True)
    
    for link in all_links:
        # Get link text
        link_text = link.get_text(strip=True)
        
        # Skip if empty or too short
        if not link_text or len(link_text) < 2:
            continue
        
        # Skip if it's navigation/UI text
        if any(skip.lower() in link_text.lower() for skip in skip_texts):
            continue
        
        # Skip legal/terms text
        legal_keywords = ["terms and conditions", "terms & conditions", "terms", "conditions",
                         "sms terms", "privacy notice", "privacy policy", "legal mentions", "legal information"]
        if any(keyword in link_text.lower() for keyword in legal_keywords):
            continue
        
        # Skip corporate/company text
        corporate_keywords = ["westfield group", "group urw", "urw", "advertise with", "advertise",
                             "careers", "career", "leasing opportunities", "leasing", "download", 
                             "more information", "company", "corporate"]
        if any(keyword in link_text.lower() for keyword in corporate_keywords):
            continue
        
        # Skip cookie/privacy consent text
        cookie_keywords = ["cookie", "privacy", "consent", "opt out", "vendor", "iab", "strictly necessary", 
                          "functional cookies", "performance cookies", "targeting cookies", "social media cookies"]
        if any(keyword in link_text.lower() for keyword in cookie_keywords):
            continue
        
        # Skip UI element text
        ui_keywords = ["button", "label", "checkbox", "filter button", "back button", "vendors list", 
                      "apply", "cancel", "clear", "reject all", "allow all", "show purposes"]
        if any(keyword in link_text.lower() for keyword in ui_keywords):
            continue
        
        # Skip data usage/partner text
        if re.search(r'\d+\s+partners?\s+can\s+use', link_text.lower()):
            continue
        if any(phrase in link_text.lower() for phrase in ["can use this purpose", "can use this feature", 
                                                           "measure content performance", "measure advertising performance",
                                                           "use limited data", "create profiles", "personalised"]):
            continue
        
        # Skip performance/description text
        if re.search(r'^performance:\s*to\s+measure', link_text.lower()):
            continue
        if re.search(r':\s*to\s+measure\s+site\s+traffic', link_text.lower()):
            continue
        
        # Skip copyright/footer text (year patterns and copyright symbol)
        if '©' in link_text or '(c)' in link_text.lower() or 'copyright' in link_text.lower():
            continue
        if re.match(r'^\d{4}\s*,?\s*[a-z\s]+$', link_text.lower()):
            continue
        if re.search(r'^\d{4}\s*,', link_text):
            continue
        
        # Skip single characters (alphabet navigation)
        if len(link_text) == 1 and link_text.isalpha():
            continue
        
        # Skip URLs
        if link_text.startswith("http") or "www." in link_text.lower():
            continue
        
        # Extract shop name - remove "Closed" suffix if present
        shop_name = link_text.replace("Closed", "").strip()
        
        # Clean up - remove trailing "Closed" if present
        if shop_name.lower().endswith("closed"):
            shop_name = shop_name[:-6].strip()
        
        # Skip if empty or too short after cleaning
        if not shop_name or len(shop_name) < 2:
            continue
        
        # Skip if it's a number or single character
        if len(shop_name) == 1 or shop_name.isdigit():
            continue
        
        # Must contain at least one letter
        if not re.search(r'[a-zA-Z]', shop_name):
            continue
        
        # Skip duplicates
        name_key = shop_name.lower()
        if name_key in seen:
            continue
        seen.add(name_key)
        
        # Extract phone number from nearby elements
        phone = ""
        parent = link.find_parent()
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True)
            phone_match = phone_re.search(parent_text)
            if phone_match:
                phone = phone_match.group(1)
        
        # Extract floor information
        floor = ""
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True)
            floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth|level \d)", parent_text, re.I)
            if floor_match:
                floor = floor_match.group(0)
        
        # Extract image URL
        image_url = ""
        img = link.find("img")
        if not img and parent:
            img = parent.find("img")
        if img:
            image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if image_url.startswith("//"):
                image_url = "https:" + image_url
        
        shops.append({
            "shop_name": shop_name,
            "phone": phone,
            "floor": floor,
            "image_url": image_url,
        })
    
    # Strategy 2: Look for list items or divs that contain shop names
    # Sometimes shops are in list items or divs, not just links
    list_items = soup.find_all(["li", "div", "span", "p"])
    
    for item in list_items:
        # Get text content
        text = item.get_text(strip=True)
        
        # Skip if empty or too short
        if not text or len(text) < 2:
            continue
        
        # Skip if it's navigation/UI text
        if any(skip.lower() in text.lower() for skip in skip_texts):
            continue
        
        # Skip legal/terms text
        legal_keywords = ["terms and conditions", "terms & conditions", "terms", "conditions",
                         "sms terms", "privacy notice", "privacy policy", "legal mentions", "legal information"]
        if any(keyword in text.lower() for keyword in legal_keywords):
            continue
        
        # Skip corporate/company text
        corporate_keywords = ["westfield group", "group urw", "urw", "advertise with", "advertise",
                             "careers", "career", "leasing opportunities", "leasing", "download", 
                             "more information", "company", "corporate"]
        if any(keyword in text.lower() for keyword in corporate_keywords):
            continue
        
        # Skip cookie/privacy consent text
        cookie_keywords = ["cookie", "privacy", "consent", "opt out", "vendor", "iab", "strictly necessary", 
                          "functional cookies", "performance cookies", "targeting cookies", "social media cookies"]
        if any(keyword in text.lower() for keyword in cookie_keywords):
            continue
        
        # Skip UI element text
        ui_keywords = ["button", "label", "checkbox", "filter button", "back button", "vendors list", 
                      "apply", "cancel", "clear", "reject all", "allow all", "show purposes"]
        if any(keyword in text.lower() for keyword in ui_keywords):
            continue
        
        # Skip data usage/partner text
        if re.search(r'\d+\s+partners?\s+can\s+use', text.lower()):
            continue
        if any(phrase in text.lower() for phrase in ["can use this purpose", "can use this feature", 
                                                      "measure content performance", "measure advertising performance",
                                                      "use limited data", "create profiles", "personalised"]):
            continue
        
        # Skip performance/description text
        if re.search(r'^performance:\s*to\s+measure', text.lower()):
            continue
        if re.search(r':\s*to\s+measure\s+site\s+traffic', text.lower()):
            continue
        
        # Skip copyright/footer text (year patterns and copyright symbol)
        if '©' in text or '(c)' in text.lower() or 'copyright' in text.lower():
            continue
        if re.match(r'^\d{4}\s*,?\s*[a-z\s]+$', text.lower()):
            continue
        if re.search(r'^\d{4}\s*,', text):
            continue
        
        # Skip single characters
        if len(text) == 1:
            continue
        
        # Skip URLs
        if text.startswith("http") or "www." in text.lower():
            continue
        
        # Skip if it contains a link (we already processed links above)
        if item.find("a"):
            continue
        
        # Extract shop name - remove "Closed" suffix if present
        shop_name = text.replace("Closed", "").strip()
        
        # Clean up - remove trailing "Closed" if present
        if shop_name.lower().endswith("closed"):
            shop_name = shop_name[:-6].strip()
        
        # Skip if empty or too short after cleaning
        if not shop_name or len(shop_name) < 2:
            continue
        
        # Skip if it's a number or single character
        if len(shop_name) == 1 or shop_name.isdigit():
            continue
        
        # Must contain at least one letter
        if not re.search(r'[a-zA-Z]', shop_name):
            continue
        
        # Skip duplicates
        name_key = shop_name.lower()
        if name_key in seen:
            continue
        seen.add(name_key)
        
        # Extract phone number
        phone = ""
        item_text = item.get_text(separator=" ", strip=True)
        phone_match = phone_re.search(item_text)
        if phone_match:
            phone = phone_match.group(1)
        
        # Extract floor information
        floor = ""
        floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth|level \d)", item_text, re.I)
        if floor_match:
            floor = floor_match.group(0)
        
        # Extract image URL
        image_url = ""
        img = item.find("img")
        if img:
            image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            if image_url.startswith("//"):
                image_url = "https:" + image_url
        
        shops.append({
            "shop_name": shop_name,
            "phone": phone,
            "floor": floor,
            "image_url": image_url,
        })
    
    # Strategy 3: Look for structured data or JSON-LD
    json_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_scripts:
        try:
            script_content = script.string
            if not script_content:
                continue
            data = json.loads(script_content)
            if isinstance(data, dict):
                if data.get("@type") == "ItemList" and "itemListElement" in data:
                    for item in data["itemListElement"]:
                        if isinstance(item, dict) and "name" in item:
                            name = item["name"]
                            # Clean name (remove "Closed" suffix)
                            name = name.replace("Closed", "").strip()
                            if name and name.lower() not in seen and len(name) >= 2:
                                seen.add(name.lower())
                                shops.append({
                                    "shop_name": name,
                                    "phone": item.get("telephone", ""),
                                    "floor": "",
                                    "image_url": item.get("image", ""),
                                })
        except Exception:
            pass
    
    return shops


def extract_shops_from_soup(soup, is_category_page=False):
    """Extract shops from a soup object.
    
    Args:
        soup: BeautifulSoup object
        is_category_page: If True, expects to find actual shop listings (not category cards)
    """
    shops = []
    seen = set()
    phone_re = re.compile(r"(\+?\d[\d\-\s\(\)]{6,}\d)")
    
    # Strategy 0: Try BrandCard grid structure first (most specific and reliable)
    brand_card_shops = extract_shops_from_brand_card_grid(soup)
    if brand_card_shops:
        print(f"Found {len(brand_card_shops)} shops using BrandCard grid extraction")
        shops.extend(brand_card_shops)
        seen.update(shop["shop_name"].lower() for shop in brand_card_shops)
        # If we found shops with BrandCard method, return early (most reliable)
        if len(brand_card_shops) >= 10:  # If we found a good number, trust this method
            return shops

    # Try multiple strategies to find shop/store elements
    
    # Strategy 1: For category pages - look for actual shop listings
    if is_category_page:
        # Look for shop/store elements on category pages
        # Common patterns: store cards, shop listings, retailer items, action-card (for shop cards)
        shop_candidates = soup.select(".store-item, .shop-item, .retailer-item, .store-card, .shop-card, .retailer-card, .action-card, [class*='store-list'], [class*='shop-list'], article, .product-item, .listing-item, .store, .shop, .retailer")
        
        for item in shop_candidates:
            # Try to find shop name
            shop_name = ""
            
            # Try title element first (same as action-card pattern)
            title_elem = item.select_one(".title, h2.title, h3.title, h4.title")
            if title_elem:
                shop_name = title_elem.get_text(strip=True)
            
            # Try heading
            if not shop_name:
                name_tag = item.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                if name_tag:
                    shop_name = name_tag.get_text(strip=True)
            
            # Try link text
            if not shop_name:
                link_tag = item.find("a")
                if link_tag:
                    shop_name = link_tag.get_text(strip=True).strip()
            
            # Try data attributes
            if not shop_name:
                shop_name = item.get("data-name") or item.get("data-title") or ""
            
            # Try first significant text
            if not shop_name:
                all_text = item.get_text(separator="\n", strip=True)
                lines = [line.strip() for line in all_text.split("\n") if line.strip()]
                if lines and len(lines[0]) > 2:
                    shop_name = lines[0]
            
            # Skip if empty or invalid
            if not shop_name or len(shop_name) < 2:
                continue
            
            # Skip common non-shop names
            skip_names = {"See More", "Learn More", "Shop", "Store", "Visit", "Home", "About", "Contact", 
                          "Hours", "Directions", "Menu", "Cart", "Search", "Sign In", "Sign Up", "Login"}
            if shop_name.lower() in {s.lower() for s in skip_names}:
                continue
            
            # Skip URLs
            if shop_name.startswith("http") or "www." in shop_name.lower():
                continue
            
            # Skip duplicates
            name_key = shop_name.lower()
            if name_key in seen:
                continue
            seen.add(name_key)
            
            # Extract other info
            item_text = item.get_text(separator=" ", strip=True)
            phone_match = phone_re.search(item_text)
            phone = phone_match.group(1) if phone_match else ""
            
            floor = ""
            floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth)", item_text, re.I)
            if floor_match:
                floor = floor_match.group(0)
            
            img = item.find("img")
            image_url = ""
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
                if image_url.startswith("//"):
                    image_url = "https:" + image_url
            
            shops.append({
                "shop_name": shop_name,
                "phone": phone,
                "floor": floor,
                "image_url": image_url,
            })
        
        # If shops found, return them; otherwise fall through to generic strategies
        if shops:
            return shops
    
    # Strategy 2: Bellevue Collection style - action-card with .title class
    # On /shop/ pages, action-card elements ARE shop cards, not category cards
    # On other pages, they might be category cards
    candidates = soup.select(".action-card")
    
    if candidates:
        # Check if these are shop cards or category cards by looking for shop-like content
        # If action-card has a .title and the title looks like a shop name (not a category name),
        # treat them as shop cards
        
        for card in candidates:
            # Find the title element
            title_elem = card.select_one(".title, h2.title, h3.title, h4.title")
            if title_elem:
                shop_name = title_elem.get_text(strip=True)
                
                # Remove "Closed" suffix if present (from old code logic)
                shop_name = shop_name.replace("Closed", "").strip()
                if shop_name.lower().endswith("closed"):
                    shop_name = shop_name[:-6].strip()
                
                # Skip if empty or already seen
                if not shop_name or len(shop_name) < 2 or shop_name.lower() in seen:
                    continue
                
                # Skip common category names that might appear as action-card titles
                category_names = {"See More", "Home Décor & Furniture", "Store Happenings", "Be. Rewarded"}
                if shop_name in category_names or any(cat.lower() in shop_name.lower() for cat in ["See More", "Explore", "Discover"]):
                    # This might be a category card, skip for now (we'll handle category links separately)
                    continue
                
                # Must contain at least one letter (from old code validation)
                if not re.search(r'[a-zA-Z]', shop_name):
                    continue
                
                seen.add(shop_name.lower())
                
                # Extract other information from the card
                description_elem = card.select_one(".description")
                description = description_elem.get_text(strip=True) if description_elem else ""
                
                # Look for image
                img = card.find("img")
                image_url = ""
                if img:
                    image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
                    if image_url.startswith("//"):
                        image_url = "https:" + image_url
                    elif image_url.startswith("/"):
                        pass  # Would need base URL for absolute conversion
                
                # Extract phone number from card text
                card_text = card.get_text(separator=" ", strip=True)
                phone_match = phone_re.search(card_text)
                phone = phone_match.group(1) if phone_match else ""
                
                # Extract floor information
                floor = ""
                floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth)", card_text, re.I)
                if floor_match:
                    floor = floor_match.group(0)
                
                shops.append({
                    "shop_name": shop_name,
                    "phone": phone,
                    "floor": floor,
                    "image_url": image_url,
                })
        
        # If we found shops from action-card, return them
        if shops:
            return shops
    
    # Strategy 2: Specific selectors (original + generic)
    candidates = soup.select("figure, .et_pb_column, .dnxte_blurb, .gallery-item, .et_pb_module, article, .card, .store-card, .shop-card, [class*='store'], [class*='shop'], [class*='retailer']")
    
    # Strategy 2: If no results, try links with text that might be store names
    if not candidates:
        # Look for links in navigation or store listings
        candidates = soup.select("a[href*='shop'], a[href*='store'], .store-link, .shop-link")
        # Also try generic containers - find divs/li with links inside
        all_divs = soup.find_all(["div", "li", "article", "section"], class_=lambda x: x and ("item" in str(x).lower() or "card" in str(x).lower()))
        for elem in all_divs:
            if elem.find("a"):
                candidates.append(elem)
    
    # Strategy 3: If still no results, look for headings that might be store names
    if not candidates:
        # Look for headings in sections that might contain store listings
        headings = soup.select("h2, h3, h4, h5, h6")
        heading_parents = [h.find_parent() for h in headings if h.find_parent()]
        candidates.extend(heading_parents)

    for c in candidates:
        # name candidates - try multiple approaches
        shop_name = ""
        
        # Try finding name in headings first
        name_tag = c.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if name_tag:
            shop_name = name_tag.get_text(strip=True)
        
        # If no heading, try link text
        if not shop_name:
            link_tag = c.find("a")
            if link_tag:
                shop_name = link_tag.get_text(strip=True)
                # If link has aria-label or title, prefer that
                if link_tag.get("aria-label"):
                    shop_name = link_tag.get("aria-label").strip()
                elif link_tag.get("title"):
                    shop_name = link_tag.get("title").strip()
        
        # If still no name, try data attributes
        if not shop_name:
            shop_name = c.get("data-name") or c.get("data-title") or c.get("aria-label") or ""
            shop_name = shop_name.strip()
        
        # If still no name, try first significant text in the element
        if not shop_name:
            # Get all text and take first meaningful line
            all_text = c.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in all_text.split("\n") if line.strip()]
            if lines:
                # Skip common non-shop-name text
                skip_patterns = ["Shop", "Store", "See More", "Learn More", "Visit", "Hours", "Contact"]
                for line in lines[:3]:  # Check first 3 lines
                    if line and len(line) > 2 and not any(skip in line for skip in skip_patterns):
                        shop_name = line
                        break
        
        # Clean up shop name
        if shop_name:
            # Remove common prefixes/suffixes
            shop_name = re.sub(r'^(Shop|Store|Visit|Go to)\s+', '', shop_name, flags=re.I)
            shop_name = shop_name.strip()
            # Remove "Closed" suffix if present (from old code logic)
            shop_name = shop_name.replace("Closed", "").strip()
            if shop_name.lower().endswith("closed"):
                shop_name = shop_name[:-6].strip()
        
        # Validation: shop name should be meaningful
        if not shop_name or len(shop_name) < 2:
            continue
        
        # Must contain at least one letter (from old code validation)
        if not re.search(r'[a-zA-Z]', shop_name):
            continue
        
        # Skip common non-shop names
        skip_names = {"See More", "Learn More", "Shop", "Store", "Visit", "Home", "About", "Contact", 
                      "Hours", "Directions", "Menu", "Cart", "Search", "Sign In", "Sign Up", "Login"}
        if shop_name.lower() in {s.lower() for s in skip_names}:
            continue
        
        # Skip URLs
        if shop_name.startswith("http") or "www." in shop_name.lower():
            continue
        
        # Skip if already seen
        name_key = shop_name.lower()
        if name_key in seen:
            continue
        seen.add(name_key)

        # Extract image URL
        img = c.find("img")
        image_url = ""
        if img:
            image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            # Convert relative URLs to absolute if needed
            if image_url.startswith("//"):
                image_url = "https:" + image_url
            elif image_url.startswith("/"):
                # Would need base URL for absolute conversion
                pass

        # Extract phone number from element text
        text = c.get_text(separator=" ", strip=True)
        phone_match = phone_re.search(text)
        phone = phone_match.group(1) if phone_match else ""

        # Extract floor information
        floor = ""
        floor_match = re.search(r"(B\d|Ground Floor|First Floor|Second Floor|Third Floor|Fourth Floor|Food Court|Multiplex|Fun Zone|Ground|First|Second|Third|Fourth)", text, re.I)
        if floor_match:
            floor = floor_match.group(0)

        shops.append({
            "shop_name": shop_name,
            "phone": phone,
            "floor": floor,
            "image_url": image_url,
        })
    
    # If still no shops found, try a fallback: extract from structured data (JSON-LD, etc.)
    if not shops:
        # Look for JSON-LD structured data
        json_scripts = soup.find_all("script", type="application/ld+json")
        for script in json_scripts:
            try:
                script_content = script.string
                if not script_content:
                    continue
                data = json.loads(script_content)
                # Handle different JSON-LD structures
                if isinstance(data, dict):
                    if data.get("@type") == "ItemList" and "itemListElement" in data:
                        for item in data["itemListElement"]:
                            if isinstance(item, dict) and "name" in item:
                                name = item["name"]
                                if name and name.lower() not in seen:
                                    seen.add(name.lower())
                                    shops.append({
                                        "shop_name": name,
                                        "phone": item.get("telephone", ""),
                                        "floor": "",
                                        "image_url": item.get("image", ""),
                                    })
            except Exception:
                pass

    return shops


def scrape_html_and_extract_text(url, headless: bool = HEADLESS, wait_seconds: float = 3.0, save_to_file: bool = True):
    """Scrape HTML from URL and extract clean text using BeautifulSoup.
    
    Args:
        url: URL to scrape
        headless: Whether to run browser in headless mode
        wait_seconds: Initial wait time for page load
        save_to_file: Whether to save extracted text to a file
    
    Returns:
        Tuple of (clean_text, filepath) where filepath is None if save_to_file is False
    """
    if not url:
        raise ValueError("url is required for scraping")

    driver = create_driver()
    clean_text = ""
    
    try:
        driver.get(url)
        
        # Wait for initial page load
        time.sleep(wait_seconds)
        
        # Scroll to load lazy-loaded content
        last_height = 0
        scroll_attempts = 0
        max_scroll_attempts = 30
        stable_count = 0
        stable_threshold = 3
        
        print("Scrolling to load all content...")
        while scroll_attempts < max_scroll_attempts:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            
            current_height = driver.execute_script("return document.body.scrollHeight")
            
            if current_height == last_height:
                stable_count += 1
                if stable_count >= stable_threshold:
                    break
            else:
                stable_count = 0
                last_height = current_height
            
            scroll_attempts += 1
        
        # Additional scrolls to ensure everything is loaded
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
        
        # Get page source and parse with BeautifulSoup
        html = driver.page_source
        soup = BeautifulSoup(html, "lxml")
        
        # Enhanced HTML cleaning - Remove noise elements
        # Remove script, style, and metadata elements
        for element in soup(["script", "style", "noscript", "meta", "link", 
                             "iframe", "embed", "object", "svg", "canvas"]):
            element.decompose()
        
        # Remove navigation and UI elements
        for element in soup(["nav", "header", "footer", "aside"]):
            element.decompose()
        
        # Remove elements with common noise classes/IDs (popups, ads, etc.)
        noise_selectors = [
            "[class*='cookie']", "[class*='popup']", "[class*='modal']",
            "[class*='overlay']", "[class*='notification']", "[class*='alert']",
            "[id*='cookie']", "[id*='popup']", "[id*='modal']",
            "[id*='overlay']", "[id*='notification']", "[id*='alert']",
            "[class*='navigation']", "[class*='menu']", "[class*='header']",
            "[class*='footer']", "[class*='sidebar']", "[class*='ad']",
            "[class*='advertisement']", "[class*='social']", "[class*='share']",
            "[class*='banner']", "[class*='promo']", "[class*='promotion']"
        ]
        for selector in noise_selectors:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception:
                pass  # Skip if selector is invalid
        
        # Get text content with better separator
        text = soup.get_text(separator="\n", strip=True)
        
        # Enhanced text cleaning - filter out noise
        lines = []
        # Common UI/navigation text to skip
        skip_patterns = [
            'skip to content', 'menu', 'search', 'close', 'open', 'loading...',
            'cookie', 'privacy', 'terms', 'accept', 'decline', 'subscribe',
            'follow us', 'share', 'like', 'comment', 'view more', 'see more',
            'learn more', 'read more', 'click here', 'sign in', 'log in',
            'sign up', 'register', 'home', 'about', 'contact', 'careers'
        ]
        
        for line in text.split("\n"):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Skip very short lines (likely noise)
            if len(line) < 2:
                continue
            
            # Skip lines that are just numbers, symbols, or whitespace
            if re.match(r'^[\d\s\-\+\(\)\.\,\:\;\!\?]+$', line):
                continue
            
            # Skip common UI text (case-insensitive)
            line_lower = line.lower()
            if any(pattern in line_lower for pattern in skip_patterns):
                # But keep it if it's part of a longer meaningful text
                if len(line) > 20:  # Might be meaningful if longer
                    pass  # Keep it
                else:
                    continue
            
            # Skip lines that look like URLs
            if line.startswith('http://') or line.startswith('https://') or 'www.' in line_lower:
                continue
            
            # Skip lines that are just email addresses
            if '@' in line and '.' in line and len(line.split()) == 1:
                continue
            
            # Skip lines that are just phone numbers (long sequences of digits/spaces)
            if re.match(r'^[\d\s\-\+\(\)]+$', line) and len(line) > 7:
                continue
            
                lines.append(line)
        
        clean_text = "\n".join(lines)
        
        print(f"Extracted {len(clean_text)} characters of clean text from {url}")
        
        filepath = None
        if save_to_file:
            # Save extracted text to a file
            import os
            from urllib.parse import urlparse
            from datetime import datetime
            
            # Create extracted_texts directory if it doesn't exist
            output_dir = "extracted_texts"
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate filename from URL and timestamp
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace("www.", "").replace(".", "_")
            path = parsed_url.path.replace("/", "_").replace("#", "_").replace("?", "_")
            if not path or path == "_":
                path = "home"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{domain}_{path}_{timestamp}.txt"
            filepath = os.path.join(output_dir, filename)
            
            # Save the extracted text
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"Extracted text from: {url}\n")
                f.write(f"Extraction date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Character count: {len(clean_text)}\n")
                f.write("=" * 80 + "\n\n")
                f.write(clean_text)
            
            print(f"Saved extracted text to: {filepath}")
        
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    
    return clean_text, filepath


def scrape_url(url, output_csv: str = DEFAULT_OUTPUT_CSV, output_text: str = DEFAULT_OUTPUT_TEXT, headless: bool = HEADLESS, wait_seconds: float = 3.0, write_files: bool = True, use_llm_extraction: bool = True):
    """Scrape `url` and either write files (CSV + labeled text) or return data in-memory.

    If `write_files` is True (default), writes `output_csv` and `output_text` and returns their paths.
    If `write_files` is False, returns a tuple `(shops, labeled_text)` and does not write to disk.
    
    Args:
        use_llm_extraction: If True, uses LLM to extract shop names from cleaned text (new method).
                           If False, uses the old parsing logic (legacy method).
    """
    if not url:
        raise ValueError("url is required for scraping")

    # Always clear any stale last_extracted_text_path.txt at the start of a new scrape
    # so the UI never shows a previous site's text file for the current URL.
    try:
        import os
        if os.path.exists("last_extracted_text_path.txt"):
            os.remove("last_extracted_text_path.txt")
    except Exception:
        # Non-fatal – continue even if cleanup fails
        pass

    # UNIVERSAL METHOD: Extract all HTML, clean with BeautifulSoup, and use OpenAI
    if use_llm_extraction:
        print(f"Using universal HTML extraction with OpenAI for {url}")
        shops = []
        driver = create_driver()
        try:
            driver.get(url)
            time.sleep(wait_seconds)
            
            # Scroll to load all content (lazy-loaded content)
            last_height = 0
            scroll_attempts = 0
            max_scroll_attempts = 30
            stable_count = 0
            stable_threshold = 3
            
            print("Scrolling to load all content...")
            while scroll_attempts < max_scroll_attempts:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)
                current_height = driver.execute_script("return document.body.scrollHeight")
                if current_height == last_height:
                    stable_count += 1
                    if stable_count >= stable_threshold:
                        break
                else:
                    stable_count = 0
                    last_height = current_height
                scroll_attempts += 1
            
            # Additional scrolls to ensure all content is loaded
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)
            
            # Get all HTML
            html = driver.page_source
            
            # Clean HTML using BeautifulSoup - remove only obvious non-content elements
            print("Cleaning HTML with BeautifulSoup...")
            soup = BeautifulSoup(html, "lxml")
            
            # Remove script and style elements
            for script in soup(["script", "style", "noscript", "meta", "link"]):
                script.decompose()
            
            # Remove comments
            from bs4 import Comment
            comments = soup.find_all(string=lambda text: isinstance(text, Comment))
            for comment in comments:
                comment.extract()
            
            # Get clean text from the cleaned HTML
            # Extract text with sensible newlines, but keep all lines;
            # let the LLM decide what is noise vs. useful content.
            clean_text = soup.get_text(separator="\n", strip=True)
            # Normalize excessive whitespace but keep even short lines,
            # because some shop names or codes can be short.
            lines = [line.strip() for line in clean_text.split("\n")]
            clean_text = "\n".join(line for line in lines if line)
            
            print(f"Extracted {len(clean_text)} characters of clean text from {url}")
            
            # Save extracted text to file for debugging/review.
            # IMPORTANT: We always create this text file (even when write_files=False)
            # so that the Streamlit UI can show the correct file for each URL.
            from datetime import datetime
            os.makedirs("extracted_texts", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            url_safe = url.replace("https://", "").replace("http://", "").replace("/", "_").replace("?", "_").replace("&", "_")[:100]
            extracted_text_filepath = f"extracted_texts/{url_safe}_{timestamp}.txt"
            with open(extracted_text_filepath, "w", encoding="utf-8") as f:
                f.write(clean_text)
            print(f"Saved extracted text to: {extracted_text_filepath}")
            
            # Use OpenAI to extract shop names from the clean text
            if not clean_text or len(clean_text.strip()) < 50:
                print(f"Warning: Insufficient text extracted from {url}")
                shops = []
            else:
                # Import here to avoid circular imports
                from llm_engine import extract_shops_from_text
                # Use LLM (OpenAI) to extract shop names from the clean text
                print(f"Extracting shop names using OpenAI from {len(clean_text)} characters of text...")
                shops = extract_shops_from_text(clean_text, url=url)
                print(f"✅ OpenAI extracted {len(shops)} shops from {url}")
                
                # Store the extracted text filepath for later download.
                # This is used by the Streamlit app to show "Download Extracted Text Files"
                # with the correct mapping between URL and text file.
                if extracted_text_filepath:
                    with open("last_extracted_text_path.txt", "w", encoding="utf-8") as f:
                        f.write(extracted_text_filepath)
        except Exception as e:
            print(f"Error in universal extraction: {e}")
            import traceback
            traceback.print_exc()
            print("Falling back to legacy parsing method...")
            use_llm_extraction = False  # Fall back to old method
        finally:
            try:
                driver.quit()
            except Exception:
                pass
    
    # LEGACY METHOD: Use old parsing logic (only if LLM extraction failed or was disabled)
    if not use_llm_extraction:
        print(f"Using legacy parsing method for {url}")
        driver = create_driver()
        shops = []
        html = ""
        try:
            driver.get(url)

            # Minimal wait - start scrolling immediately (faster startup)
            time.sleep(0.5)  # Reduced from wait_seconds - start immediately

            # More aggressive scrolling to load all lazy-loaded content
            # Scroll gradually and check if content is still loading
            last_height = 0
            scroll_attempts = 0
            max_scroll_attempts = 50  # Increase max scroll attempts
            stable_count = 0
            stable_threshold = 3
            
            print("Scrolling to load all content...")
            while scroll_attempts < max_scroll_attempts:
                # Scroll to bottom
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.5)  # Wait for lazy loading
                
                # Check current height
                current_height = driver.execute_script("return document.body.scrollHeight")
                
                if current_height == last_height:
                    stable_count += 1
                    if stable_count >= stable_threshold:
                        # Height hasn't changed for several scrolls, likely all content loaded
                        break
                else:
                    stable_count = 0
                    last_height = current_height
                
                scroll_attempts += 1
            
            # Additional scrolls to ensure everything is loaded
            for _ in range(5):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.5)
            
            # Scroll back to top gradually
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            print(f"Finished scrolling after {scroll_attempts} attempts")

            html = driver.page_source
            soup = BeautifulSoup(html, "lxml")
            
            # Check if this page has alphabetical listing structure
            if detect_alphabetical_listing_page(soup):
                print(f"Detected alphabetical listing page, using link-based extraction...")
                shops = extract_shops_from_alphabetical_listing(soup)
                if shops:
                    print(f"Found {len(shops)} shops using alphabetical listing extraction method")
                else:
                    print("No shops found with alphabetical listing method, falling back to generic extraction...")
                    shops = extract_shops_from_soup(soup, is_category_page=False)

            # For /shop/ URL, treat it as a shop directory page and extract shops directly
            is_shop_directory = "/shop" in url.lower() or "shop" in url.lower()
            
            # Only process if we haven't already extracted shops from alphabetical listing
            if not shops and is_shop_directory:
                # This is likely a shop directory page - extract shops directly
                print(f"Treating {url} as shop directory page, extracting shops directly...")
                shops = extract_shops_from_soup(soup, is_category_page=True)
                
                # If no shops found, try checking for category links (for sites that have categories on /shop/)
                if not shops:
                    category_links = extract_category_links_from_soup(soup, base_url=url)
                    if category_links:
                        print(f"Found {len(category_links)} category/card link(s), scraping shops from each...")
                        
                        for category_name, category_url in category_links:
                            try:
                                print(f"  Scraping category: {category_name} ({category_url})")
                                driver.get(category_url)
                                
                                # Wait for page to load
                                time.sleep(wait_seconds)
                                
                                # More aggressive scrolling for category pages
                                last_height = 0
                                scroll_attempts = 0
                                max_scroll_attempts = 50
                                stable_count = 0
                                
                                while scroll_attempts < max_scroll_attempts:
                                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                    time.sleep(1.5)
                                    current_height = driver.execute_script("return document.body.scrollHeight")
                                    
                                    if current_height == last_height:
                                        stable_count += 1
                                        if stable_count >= 3:
                                            break
                                    else:
                                        stable_count = 0
                                        last_height = current_height
                                    scroll_attempts += 1
                                
                                # Additional scrolls
                                for _ in range(5):
                                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                    time.sleep(0.5)
                                
                                category_html = driver.page_source
                                category_soup = BeautifulSoup(category_html, "lxml")
                                
                                # Extract shops from category page
                                category_shops = extract_shops_from_soup(category_soup, is_category_page=True)
                                shops.extend(category_shops)
                                
                                if category_shops:
                                    print(f"    Found {len(category_shops)} shop(s) in category '{category_name}'")
                                else:
                                    print(f"    No shops found in category '{category_name}'")
                                    
                            except Exception as e:
                                print(f"    Error scraping category '{category_name}': {e}")
                                continue
            else:
                # For other URLs, check if this page has category links (action-card elements)
                category_links = extract_category_links_from_soup(soup, base_url=url)
                
                if category_links:
                    # This is a main page with category cards - scrape each category page
                    print(f"Found {len(category_links)} category/card link(s), scraping shops from each...")
                    
                    for category_name, category_url in category_links:
                        try:
                            print(f"  Scraping category: {category_name} ({category_url})")
                            driver.get(category_url)
                            
                            # Wait for page to load
                            time.sleep(wait_seconds)
                            
                            # Scroll to trigger lazy loading
                            for _ in range(3):
                                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                time.sleep(1)
                            
                            category_html = driver.page_source
                            category_soup = BeautifulSoup(category_html, "lxml")
                            
                            # Extract shops from category page
                            category_shops = extract_shops_from_soup(category_soup, is_category_page=True)
                            shops.extend(category_shops)
                            
                            if category_shops:
                                print(f"    Found {len(category_shops)} shop(s) in category '{category_name}'")
                            else:
                                print(f"    No shops found in category '{category_name}'")
                                
                        except Exception as e:
                            print(f"    Error scraping category '{category_name}': {e}")
                            continue
                
                # If no category links or no shops found from categories, try direct extraction
                if not shops:
                    shops = extract_shops_from_soup(soup, is_category_page=False)
            
            # If still no shops, try alphabetical listing extraction as fallback
            if not shops and detect_alphabetical_listing_page(soup):
                print("Trying alphabetical listing extraction as fallback...")
                shops = extract_shops_from_alphabetical_listing(soup)
            
            # fallback: if nothing found, save rendered HTML for inspection (only when writing files)
            if not shops:
                if write_files:
                    debug_path = "debug_rendered.html"
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"No shop blocks found — saved rendered HTML to {debug_path}")
                else:
                    # When not writing files, at least log that nothing was found
                    print(f"Warning: No shops extracted from {url}. The website structure may not match expected patterns.")

        except Exception as e:
            print(f"Error in legacy scraping method: {e}")
            shops = []
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    # Build labeled text (works for both LLM and legacy methods)
    lines = []
    for s in shops:
        lines.append(f"shop_name:{s['shop_name']}")
        lines.append(f"phone:{s['phone'] or '-'}")
        lines.append(f"floor:{s['floor'] or '-'}")
        lines.append("")
    labeled_text = "\n".join(lines)

    if not write_files:
        return shops, labeled_text

    # write CSV
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["shop_name", "phone", "floor", "image_url"])
        writer.writeheader()
        writer.writerows(shops)

    # Save plain labeled text output (no image_url)
    with open(output_text, "w", encoding="utf-8") as tf:
        tf.write(labeled_text)

    print(f"Scraped {len(shops)} shops -> {output_csv}, {output_text}")
    return output_csv, output_text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render shop page and extract shop details")
    parser.add_argument("--url", required=True, help="Mall page URL to scrape")
    parser.add_argument("--csv", default=DEFAULT_OUTPUT_CSV, help="Output CSV file")
    parser.add_argument("--txt", default=DEFAULT_OUTPUT_TEXT, help="Output labeled text file for cleaning")
    args = parser.parse_args()

    scrape_url(args.url, output_csv=args.csv, output_text=args.txt)
