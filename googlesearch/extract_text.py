"""
Extract and clean readable text from web pages using BeautifulSoup.

Fetches HTML with requests, parses with BeautifulSoup, removes noise
(nav, ads, scripts, styles), and returns cleaned plain text.
"""

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Default timeout and headers for requests
REQUEST_TIMEOUT = 15
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    """Download HTML from a URL. Returns None on failure."""
    try:
        r = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception:
        return None


def extract_clean_text(html: str, url: str = "") -> str:
    """
    Extract readable text from HTML and clean it with BeautifulSoup.

    - Removes script, style, nav, footer, ads, forms, iframes
    - Extracts text from body, normalizes whitespace
    - Drops short/repeated lines and trims
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Remove elements that are usually noise
    for tag in soup.find_all(
        [
            "script",
            "style",
            "noscript",
            "iframe",
            "object",
            "embed",
            "svg",
            "path",
            "meta",
            "link",
            "head",
        ]
    ):
        tag.decompose()

    # Remove common nav/footer/sidebar/ad containers (by tag or class/id patterns)
    noise_selectors = [
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
        ".nav",
        ".navbar",
        ".menu",
        ".sidebar",
        ".footer",
        ".advertisement",
        ".ad",
        ".ads",
        "#nav",
        "#navbar",
        "#menu",
        "#footer",
        "#sidebar",
        ".cookie",
        ".consent",
        ".social-share",
        ".comments",
        ".related-posts",
    ]
    for selector in noise_selectors:
        try:
            for el in soup.select(selector):
                el.decompose()
        except Exception:
            pass

    # Get text from body, or whole soup if no body
    body = soup.find("body") or soup
    text = body.get_text(separator="\n", strip=True)

    # Normalize and clean
    lines = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        # Collapse multiple spaces
        line = re.sub(r"[ \t]+", " ", line)
        if not line:
            continue
        # Skip very short lines (likely noise)
        if len(line) < 3:
            continue
        # Skip lines that look like repeated UI (e.g. "Home", "Login")
        if line.lower() in ("home", "login", "sign in", "sign up", "menu", "search", "submit"):
            continue
        # Dedupe consecutive identical lines
        key = line[:80]
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)

    # Join and collapse multiple newlines
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def extract_text_from_url(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    """
    Fetch a URL and return extracted, cleaned text.

    Returns empty string if fetch or parse fails.
    """
    html = fetch_html(url, timeout=timeout)
    if html is None:
        return ""
    return extract_clean_text(html, url)
