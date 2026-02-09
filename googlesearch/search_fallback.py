"""
Step 3 — Google Search API (Fallback).

When Selenium is blocked or fails, use the official Google Custom Search JSON API
to retrieve search result links.

Setup:
1. Create a Programmable Search Engine at https://programmablesearchengine.google.com/
   (search the whole web) and copy the "Search engine ID" (cx).
2. Enable "Custom Search API" in Google Cloud Console and create an API key.
3. Set environment variables:
   - GOOGLE_SEARCH_API_KEY  — your API key
   - GOOGLE_SEARCH_ENGINE_ID — your search engine ID (cx)
"""

import os
from typing import List

import requests

# Google Custom Search JSON API (official)
GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_SEARCH_ENGINE_ID = os.environ.get("GOOGLE_SEARCH_ENGINE_ID", "")
GOOGLE_SEARCH_API_URL = "https://www.googleapis.com/customsearch/v1"


def search_via_google_api(query: str, max_results: int = 20) -> List[dict]:
    """
    Fallback search using Google Custom Search JSON API.
    Returns same shape as Selenium: title, link, snippet.
    """
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_ENGINE_ID:
        return []
    results = []
    # API returns up to 10 results per request; use start index for more
    start = 1
    try:
        while len(results) < max_results:
            r = requests.get(
                GOOGLE_SEARCH_API_URL,
                params={
                    "key": GOOGLE_SEARCH_API_KEY,
                    "cx": GOOGLE_SEARCH_ENGINE_ID,
                    "q": query,
                    "num": min(10, max_results - len(results)),
                    "start": start,
                },
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            items = data.get("items") or []
            if not items:
                break
            for item in items:
                link = item.get("link") or ""
                if not link or "google.com" in link:
                    continue
                results.append({
                    "title": (item.get("title") or "").strip(),
                    "link": link,
                    "snippet": (item.get("snippet") or "").strip(),
                })
                if len(results) >= max_results:
                    break
            start += len(items)
            if len(items) < 10:
                break
    except Exception:
        pass
    return results[:max_results]


def search_fallback(query: str, max_results: int = 20) -> List[dict]:
    """
    Fallback using Google Custom Search JSON API when Selenium is restricted.
    Returns list of {title, link, snippet}.
    """
    return search_via_google_api(query, max_results=max_results)
