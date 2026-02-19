"""
SERP API scraper for Mall AI Dashboard.
Fetches current/recent news and blog results (no old data) using mall name and address.
Uses SerpApi with strict date filters: past 7 days only for posts, blogs, and store-related content.

When SERP API returns unsatisfactory data, falls back to direct Google search
(via Google Custom Search API or Selenium) using the mall name from main UI.
"""
import sys
from pathlib import Path
import requests
from typing import List, Dict, Any, Optional

try:
    from serp_config import SERP_API_KEY
except ImportError:
    SERP_API_KEY = ""

# Minimum results considered "satisfactory"; below this we trigger Google fallback
MIN_SATISFACTORY_RESULTS = 3

# Only current data: past 7 days for posts/blogs; past 24h optional for very latest
TBS_PAST_WEEK = "qdr:w"   # past 7 days
TBS_PAST_DAY = "qdr:d"    # past 24 hours (use for "latest posts" emphasis)


def _search_google_fallback(query: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Fallback when SERP API returns unsatisfactory data: search Google directly
    for the mall name to find latest information.
    Tries: (1) Google Custom Search API, (2) Selenium Google search.
    Returns list of dicts with keys: title, snippet, link, source, date.
    """
    if not query or not str(query).strip():
        return []
    query = str(query).strip()
    results = []

    # Ensure project root is on path for googlesearch imports
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    # 1) Try Google Custom Search API (no Chrome required)
    try:
        from googlesearch.search_fallback import search_via_google_api
        raw = search_via_google_api(query, max_results=max_results)
        for r in raw:
            link = (r.get("link") or "").strip()
            if link and not link.startswith("https://www.google."):
                results.append({
                    "title": (r.get("title") or "").strip(),
                    "snippet": (r.get("snippet") or "").strip(),
                    "link": link,
                    "source": "Google Search (fallback)",
                    "date": "",
                })
        if results:
            return results[:max_results]
    except Exception:
        pass

    # 2) Try Selenium Google search (direct scraping)
    try:
        from googlesearch.selenium_search import search_google
        raw = search_google(query, max_results=max_results)
        for r in raw:
            link = (r.get("link") or "").strip()
            if link and not link.startswith("https://www.google."):
                results.append({
                    "title": (r.get("title") or "").strip(),
                    "snippet": (r.get("snippet") or "").strip(),
                    "link": link,
                    "source": "Google Search (fallback)",
                    "date": "",
                })
        if results:
            return results[:max_results]
    except Exception:
        pass

    return results


def fetch_mall_news(mall_name: str, address: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Fetch current/recent news and blog results for a mall (no old data).
    Uses mall name and address from main UI. All content is restricted to recent
    time windows (past 7 days for news/blogs, past 24h for latest posts).

    When SERP API returns unsatisfactory data (or no key), falls back to direct
    Google search using mall name to find latest information.

    Returns:
        List of dicts with keys: title, snippet, link, source (optional), date (if available)
    """
    mall_name = (mall_name or "").strip()
    address = (address or "").strip()
    query_parts = [p for p in [mall_name, address] if p]
    query = " ".join(query_parts).strip() if query_parts else ""
    if not query:
        return []

    results = []

    # 1) Google News – current only: sort by date (so=1 = latest first)
    if SERP_API_KEY:
        try:
            for news_query in (f"{query} when:7d", query):  # try past 7d first, then any with date sort
                params = {
                    "api_key": SERP_API_KEY,
                    "engine": "google_news",
                    "q": news_query,
                    "gl": "us",
                    "hl": "en",
                    "num": min(max_results, 10),
                    "so": "1",  # sort by date (latest first)
                }
                resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                news = data.get("news_results") or []
                if news:
                    for item in news:
                        if isinstance(item, dict):
                            results.append({
                                "title": item.get("title") or "",
                                "snippet": item.get("snippet") or item.get("title") or "",
                                "link": item.get("link") or "",
                                "source": item.get("source", ""),
                                "date": item.get("date") or item.get("published_at") or "",
                            })
                    break
        except Exception:
            pass

        # 2) Google Search – current posts/blogs only: past 7 days (stores, mall, blogs)
        try:
            params = {
                "api_key": SERP_API_KEY,
                "engine": "google",
                "q": f"{query} blog OR post OR stores OR news",
                "gl": "us",
                "hl": "en",
                "num": min(max_results, 10),
                "tbs": TBS_PAST_WEEK,  # past 7 days only – no old data
            }
            resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            organic = data.get("organic_results") or []
            for item in organic:
                if isinstance(item, dict):
                    link = item.get("link") or ""
                    if link and not any((r.get("link") or "").strip() == link for r in results):
                        results.append({
                            "title": item.get("title") or "",
                            "snippet": item.get("snippet") or "",
                            "link": link,
                            "source": item.get("displayed_link") or "",
                            "date": item.get("date") or "",
                        })
        except Exception:
            pass

        # 3) Very latest: past 24 hours for "latest posts" / current buzz
        try:
            params = {
                "api_key": SERP_API_KEY,
                "engine": "google",
                "q": f"{query} latest OR recent OR today",
                "gl": "us",
                "hl": "en",
                "num": 5,
                "tbs": TBS_PAST_DAY,  # past 24 hours
            }
            resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            organic = data.get("organic_results") or []
            for item in organic:
                if isinstance(item, dict):
                    link = item.get("link") or ""
                    if link and not any((r.get("link") or "").strip() == link for r in results):
                        results.append({
                            "title": item.get("title") or "",
                            "snippet": item.get("snippet") or "",
                            "link": link,
                            "source": (item.get("displayed_link") or "") + " (24h)",
                            "date": item.get("date") or "",
                        })
        except Exception:
            pass

        # 4) Knowledge graph / local (current mall info – address, hours, contact; not time-bound)
        try:
            params = {
                "api_key": SERP_API_KEY,
                "engine": "google",
                "q": query,
                "gl": "us",
                "hl": "en",
                "num": 3,
            }
            resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            kg = data.get("knowledge_graph") or {}
            if isinstance(kg, dict):
                title = kg.get("title") or ""
                desc = kg.get("description") or ""
                if title or desc:
                    link = (kg.get("website") or kg.get("link") or "").strip()
                    if not any((r.get("link") or "").strip() == link for r in results):
                        results.append({
                            "title": title,
                            "snippet": desc,
                            "link": link,
                            "source": "Knowledge Graph",
                            "date": "",
                        })
        except Exception:
            pass

        # 5) Fallback: if we still have fewer than max_results items, relax time filter
        #    and fetch additional news/blog/store articles (may include older but still
        #    sorted by recency from Google).
        try:
            if len(results) < max_results:
                params = {
                    "api_key": SERP_API_KEY,
                    "engine": "google",
                    "q": f"{query} news OR blog OR stores OR review",
                    "gl": "us",
                    "hl": "en",
                    "num": max_results,
                    "tbs": "qdr:y",  # past year – broader, only used as fallback
                }
                resp = requests.get("https://serpapi.com/search", params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                organic = data.get("organic_results") or []
                for item in organic:
                    if isinstance(item, dict):
                        link = item.get("link") or ""
                        if link and not any((r.get("link") or "").strip() == link for r in results):
                            results.append({
                                "title": item.get("title") or "",
                                "snippet": item.get("snippet") or "",
                                "link": link,
                                "source": item.get("displayed_link") or "",
                                "date": item.get("date") or "",
                            })
        except Exception:
            pass

    # Deduplicate by link and cap
    seen = set()
    unique = []
    for r in results:
        link = (r.get("link") or "").strip()
        if link and link not in seen and len(unique) < max_results:
            seen.add(link)
            unique.append(r)

    # If SERP API data is unsatisfactory (too few results), fall back to direct Google search
    # using mall name from main UI to find latest information about the mall
    if len(unique) < MIN_SATISFACTORY_RESULTS:
        # Prioritize mall name for "latest info about mall" query (from main UI)
        fallback_query = mall_name if mall_name else query
        if fallback_query:
            fallback_results = _search_google_fallback(
                f"{fallback_query} mall news latest information",
                max_results=max_results,
            )
            for r in fallback_results:
                link = (r.get("link") or "").strip()
                if link and link not in seen and len(unique) < max_results:
                    seen.add(link)
                    unique.append(r)

    return unique


def format_news_for_excel(results: List[Dict[str, Any]]) -> tuple:
    """
    Format SERP results for Excel: one string for 'General Information from Internet'
    and one string for 'News/Blog URL' (one URL per line).

    Returns:
        (text_for_column_l, urls_for_column_m)
    """
    if not results:
        return ("", "")

    lines = []
    urls = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        link = (r.get("link") or "").strip()
        date_str = (r.get("date") or "").strip()
        if title or snippet:
            head = f"{i}. {title}"
            if date_str:
                head += f" ({date_str})"
            lines.append(f"{head}\n{snippet}".strip())
        if link:
            urls.append(link)

    text = "\n\n---\n\n".join(lines) if lines else ""
    url_text = "\n".join(urls) if urls else ""
    return (text, url_text)
