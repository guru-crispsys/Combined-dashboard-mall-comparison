"""
Google Search Scraper using Selenium.

Performs automated web searches with dynamic queries.
Chrome is configured to NOT show "Chrome is being controlled by automated test software".
"""

import time
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

try:
    from webdriver_manager.chrome import ChromeDriverManager
    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False

from config import (
    CHROME_HEADLESS,
    CHROME_IMPLICIT_WAIT,
    CHROME_PAGE_LOAD_TIMEOUT,
    CHROME_WINDOW_SIZE,
    GOOGLE_SEARCH_URL,
    MAX_RESULTS_PER_QUERY,
    SCROLL_PAUSE_SECONDS,
)


def get_chrome_options(headless: Optional[bool] = None) -> Options:
    """
    Build Chrome options that hide automation indicators.

    - Removes "Chrome is being controlled by automated test software" banner
    - Disables automation extension flag
    - Reduces detection via blink features
    """
    opts = Options()

    # Hide "Chrome is being controlled by automated test software"
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Reduce automation fingerprint
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=" + CHROME_WINDOW_SIZE)
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-notifications")

    if headless if headless is not None else CHROME_HEADLESS:
        opts.add_argument("--headless=new")

    return opts


def create_driver(headless: Optional[bool] = None) -> webdriver.Chrome:
    """Create a Chrome WebDriver with stealth options."""
    options = get_chrome_options(headless=headless)

    if USE_WEBDRIVER_MANAGER:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(CHROME_PAGE_LOAD_TIMEOUT)
    driver.implicitly_wait(CHROME_IMPLICIT_WAIT)

    # Override navigator.webdriver in JS (optional, extra stealth)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )

    return driver


def search_google(
    query: str,
    max_results: int = MAX_RESULTS_PER_QUERY,
    driver: Optional[webdriver.Chrome] = None,
    headless: Optional[bool] = None,
) -> List[dict]:
    """
    Run a Google search with the given query and return structured results.

    Args:
        query: Search string (e.g. "Coming soon store Phoenix Mall").
        max_results: Maximum number of result links to return.
        driver: Optional existing Chrome driver; if None, one is created and closed.
        headless: Override config headless setting.

    Returns:
        List of dicts with keys: title, link, snippet (optional).
    """
    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)

    results = []
    try:
        encoded = quote_plus(query)
        url = f"{GOOGLE_SEARCH_URL}?q={encoded}&num={min(max_results, 100)}"
        driver.get(url)
        time.sleep(SCROLL_PAUSE_SECONDS)

        # Accept cookies / consent if present (common on google.com)
        try:
            consent_btn = driver.find_elements(
                By.XPATH,
                "//button[contains(., 'Accept') or contains(., 'Accept all') or contains(., 'I agree')]"
            )
            if consent_btn:
                consent_btn[0].click()
                time.sleep(1)
        except Exception:
            pass

        # Main result containers (organic results)
        # Google uses div with data-hveid or g class for result blocks
        result_selectors = [
            "div.g",  # Classic organic result block
            "div[data-hveid]",
        ]

        seen_links = set()
        for selector in result_selectors:
            blocks = driver.find_elements(By.CSS_SELECTOR, selector)
            for block in blocks:
                if len(results) >= max_results:
                    break
                try:
                    # Link
                    link_el = block.find_elements(By.CSS_SELECTOR, "a[href^='http']")
                    if not link_el:
                        continue
                    href = link_el[0].get_attribute("href") or ""
                    # Skip Google redirect and non-http
                    if not href.startswith("http") or "google.com" in href:
                        continue
                    if href in seen_links:
                        continue
                    seen_links.add(href)

                    # Title (often in h3)
                    title_el = block.find_elements(By.CSS_SELECTOR, "h3")
                    title = title_el[0].text.strip() if title_el else ""

                    # Snippet
                    snippet_el = block.find_elements(
                        By.CSS_SELECTOR,
                        "div[data-sncf], span[data-sncf], .VwiC3b, div.IsZvec",
                    )
                    snippet = snippet_el[0].text.strip() if snippet_el else ""

                    results.append({
                        "title": title,
                        "link": href,
                        "snippet": snippet,
                    })
                except Exception:
                    continue
            if len(results) >= max_results:
                break

        # Fallback: any visible links in main content area
        if len(results) < max_results:
            try:
                main = driver.find_elements(By.ID, "main") or driver.find_elements(By.ID, "rso")
                if main:
                    links = main[0].find_elements(By.CSS_SELECTOR, "a[href^='http']")
                    for a in links:
                        if len(results) >= max_results:
                            break
                        href = (a.get_attribute("href") or "").split("?")[0]
                        if not href or "google.com" in href or href in seen_links:
                            continue
                        seen_links.add(href)
                        title = a.text.strip() or href
                        results.append({"title": title, "link": href, "snippet": ""})
            except Exception:
                pass

    finally:
        if own_driver and driver:
            driver.quit()

    return results[:max_results]


# Domains we do not treat as official mall sites
NON_OFFICIAL_DOMAIN_FRAGMENTS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "tripadvisor.", "yelp.", "wikipedia.org",
    "google.com", "maps.google", "news.google", "linkedin.com",
    "foursquare.com", "patch.com", "yahoo.com", "bing.com",
    "amazon.com", "ebay.com", "reddit.com", "pinterest.com",
)
# Domain/title hints that suggest an official mall or shopping center site
OFFICIAL_MALL_HINTS = ("mall", "shopping", "centre", "center", "plaza", "retail", "property")


def _is_likely_official_mall_site(link: str, title: str) -> bool:
    """Return True if link/title look like an official mall/shopping center website."""
    try:
        host = urlparse(link).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    for frag in NON_OFFICIAL_DOMAIN_FRAGMENTS:
        if frag in host:
            return False
    title_lower = (title or "").lower()
    for hint in OFFICIAL_MALL_HINTS:
        if hint in host or hint in title_lower:
            return True
    # First organic result for "X official website" is often the real site even without hint
    return True


def find_official_mall_website(
    mall_name: str,
    driver: webdriver.Chrome,
    max_results: int = 10,
) -> Optional[dict]:
    """
    Search for the official website of a mall/shopping center and return the first
    result that looks like an official site (not social, wiki, or news).

    Returns:
        {"link": str, "title": str} or None if none found.
    """
    if not mall_name or not mall_name.strip():
        return None
    query = f'"{mall_name.strip()}" official website'
    results = search_google(query, max_results=max_results, driver=driver)
    for r in results:
        link = (r.get("link") or "").strip()
        title = (r.get("title") or "").strip()
        if not link or "google.com" in link:
            continue
        if _is_likely_official_mall_site(link, title):
            return {"link": link, "title": title or link}
    # If no "official" candidate, return first result that isn't clearly third-party
    for r in results:
        link = (r.get("link") or "").strip()
        title = (r.get("title") or "").strip()
        if not link or "google.com" in link:
            continue
        try:
            host = urlparse(link).netloc.lower()
        except Exception:
            continue
        if any(f in host for f in NON_OFFICIAL_DOMAIN_FRAGMENTS):
            continue
        return {"link": link, "title": title or link}
    return None


# CSS classes for Google AI Overview (Google changes DOM frequently; multiple fallbacks)
AI_OVERVIEW_CONTENT_SELECTORS = [
    "div[role='complementary']",  # AI Mode container (common structure)
    "div.WaaZC",  # Main AI overview text
    "div[jsname='dvXlsc']",
    "[data-attrid='description']",
    "div.ygGdYd",
    "div.related-question-pair",  # Q&A style overview
    "div[data-ved][data-tts-response]",  # AI response attribute
    "div.LGOjhe",  # AI overview content block
    "div.Sal6Tb",  # Alternative overview block
    "div.X5LH0c",  # AI-generated summary
    "div.O9g1cc",  # Overview section
]
AI_OVERVIEW_LINK_SELECTORS = [
    "div.VqeGe",
    "div[role='complementary'] a[href^='http']",
]
# Button/link text to expand more AI content
AI_OVERVIEW_EXPAND_TEXTS = ("Show more", "Show More", "Dive deeper", "Dive Deeper", "More", "more")


def extract_ai_overview(
    driver: webdriver.Chrome,
    expand_first: bool = True,
    wait_after_load: float = 2.0,
    initial_wait: float = 5.0,
) -> dict:
    """
    Extract text from Google's AI Overview / AI mode on the current search results page.

    AI Overview loads asynchronously—waits for it to appear before extracting.
    Optionally clicks "Show more" / "Dive deeper" to expand content.
    Returns {"text": str, "related_links": list}. Empty if no AI overview is present.

    Note: Google's DOM changes frequently; selectors may need updating.
    """
    text_parts: List[str] = []
    related_links: List[str] = []
    text = ""

    try:
        # Wait for AI Overview to load (it renders asynchronously after page load)
        time.sleep(initial_wait)

        # Scroll to top so AI Overview is in view (can help with lazy loading)
        try:
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
        except Exception:
            pass

        if expand_first:
            # Click "Show more" / "Dive deeper" if present to expand AI overview
            for label in AI_OVERVIEW_EXPAND_TEXTS:
                try:
                    el = driver.find_elements(
                        By.XPATH,
                        f"//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{label.lower()}')]",
                    )
                    for e in el:
                        try:
                            if e.is_displayed() and e.is_enabled():
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", e)
                                time.sleep(0.3)
                                e.click()
                                time.sleep(wait_after_load)
                                break
                        except Exception:
                            continue
                    else:
                        continue
                    break
                except Exception:
                    pass

        # Collect text from known AI overview content blocks
        for selector in AI_OVERVIEW_CONTENT_SELECTORS:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, selector)
                for el in els:
                    try:
                        if not el.is_displayed():
                            continue
                        t = (el.text or "").strip()
                        if t and len(t) > 30:  # Skip tiny UI chunks
                            text_parts.append(t)
                    except Exception:
                        continue
            except Exception:
                pass
            if text_parts:
                break

        # Fallback: look for first substantial text block in main/search area (AI Overview is usually at top)
        if not text_parts:
            try:
                main_selectors = ["#rso", "#main", "#search"]
                for main_sel in main_selectors:
                    mains = driver.find_elements(By.CSS_SELECTOR, main_sel)
                    for main in mains[:1]:
                        blocks = main.find_elements(By.CSS_SELECTOR, "div")
                        for block in blocks[:15]:  # Check first 15 divs
                            try:
                                if not block.is_displayed():
                                    continue
                                t = (block.text or "").strip()
                                # AI Overview is typically 100+ chars, exclude nav/ads
                                if t and 100 <= len(t) <= 5000 and "Sign in" not in t and "Settings" not in t:
                                    text_parts.append(t)
                                    break
                            except Exception:
                                continue
                        if text_parts:
                            break
                    if text_parts:
                        break
            except Exception:
                pass

        # Related links (sources cited in AI overview)
        for selector in AI_OVERVIEW_LINK_SELECTORS:
            try:
                divs = driver.find_elements(By.CSS_SELECTOR, selector)
                for div in divs:
                    try:
                        links = div.find_elements(By.CSS_SELECTOR, "a[href^='http']")
                        for a in links:
                            href = (a.get_attribute("href") or "").strip()
                            if href and "google.com" not in href:
                                related_links.append(href)
                    except Exception:
                        continue
            except Exception:
                pass

        # Dedupe and join text (prefer longer/more complete parts)
        seen: set = set()
        unique_parts = []
        for p in text_parts:
            p_clean = p.strip()
            if p_clean and p_clean not in seen and len(p_clean) > 30:
                seen.add(p_clean)
                unique_parts.append(p_clean)
        # Sort by length descending to put most substantial content first
        unique_parts.sort(key=len, reverse=True)
        text = "\n\n".join(unique_parts[:3]).strip() if unique_parts else ""  # Top 3 blocks to avoid duplication

    except Exception as e:
        print(f"  [AI Overview] Error: {e}")

    return {"text": text, "related_links": list(dict.fromkeys(related_links))}


def run_search(query: str, max_results: int = MAX_RESULTS_PER_QUERY) -> List[dict]:
    """
    Convenience function: run a single search with a new driver.

    Use this for dynamic prompts, e.g.:
        run_search("Coming soon store Phoenix Mall")
        run_search("New store opening Zara")
    """
    return search_google(query=query, max_results=max_results)


def _sanitize_filename(s: str, max_len: int = 60) -> str:
    """Make a safe filename from a string."""
    import re
    s = re.sub(r"[^\w\s\-.]", "", s)
    s = re.sub(r"[\s_\-]+", "_", s).strip("_")
    return (s[:max_len] if len(s) > max_len else s) or "page"


if __name__ == "__main__":
    import sys
    from pathlib import Path

    from extract_text import extract_text_from_url

    prompt = sys.argv[1] if len(sys.argv) > 1 else "Coming soon store mall"
    max_links = int(sys.argv[2]) if len(sys.argv) > 2 else 5  # optional: how many links to extract

    # Output directory for extracted text files (one file per link)
    out_dir = Path("extracted_output")
    out_dir.mkdir(exist_ok=True)

    print(f"Searching for: {prompt}\n")
    results = run_search(prompt, max_results=max(10, max_links))

    for i, r in enumerate(results[:max_links], 1):
        link = r["link"]
        title = r.get("title") or link
        print("=" * 70)
        print(f"[{i}] {title}")
        print(f"    URL: {link}")
        print("-" * 70)
        print("Extracting and cleaning text from page...")
        text = extract_text_from_url(link)
        if text:
            # Save to separate text file
            slug = _sanitize_filename(title or link)
            fname = out_dir / f"extract_{i}_{slug}.txt"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(f"URL: {link}\n")
                f.write(f"Title: {title}\n")
                f.write("=" * 70 + "\n\n")
                f.write(text)
            print(f"Saved to: {fname}")
        else:
            print("(Could not fetch or extract text from this URL.)")
        print()
