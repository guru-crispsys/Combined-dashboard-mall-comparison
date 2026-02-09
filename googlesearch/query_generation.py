"""
Step 1 — Search Query Generation.

Generates targeted search queries for discovering upcoming retail store openings:
- "Coming soon store + Mall Name"
- "New store opening + Brand Name"
- Includes current year for recency (e.g. 2026)
"""

import re
from datetime import datetime
from typing import List, Optional

CURRENT_YEAR = str(datetime.now().year)


def extract_mall_name_from_query(custom_query: Optional[str]) -> Optional[str]:
    """
    Extract a mall/shopping center name from a user query when it looks mall-focused.
    Used to find and scrape the official mall website first.

    Examples:
        "latest update about Westfield Southcenter mall 2026" -> "Westfield Southcenter mall"
        "coming soon tenants and latest update about Midland Park Mall" -> "Midland Park Mall"
    """
    if not custom_query or not custom_query.strip():
        return None
    q = custom_query.strip()
    # Remove trailing year
    q_clean = re.sub(r"\s*(202[4-9])\s*$", "", q, flags=re.I).strip()
    # "latest update(s) about X"
    m = re.search(r"latest\s+updates?\s+about\s+(.+)", q_clean, re.I)
    if m:
        return m.group(1).strip()
    # "coming soon ... [latest update about] X"
    m = re.search(
        r"coming\s+soon\s+(?:tenants?\s+and\s+)?(?:latest\s+update\s+about\s+)?(.+)",
        q_clean,
        re.I,
    )
    if m:
        return m.group(1).strip()
    # "... X mall" (phrase ending with "mall")
    m = re.search(r"(.+?\s+mall)\b", q_clean, re.I)
    if m:
        return m.group(1).strip()
    # "about X mall" or "about X"
    m = re.search(r"about\s+(.+)", q_clean, re.I)
    if m:
        return m.group(1).strip()
    return None


def generate_queries(
    mall_name: Optional[str] = None,
    brand_name: Optional[str] = None,
    custom_query: Optional[str] = None,
) -> List[str]:
    """
    Generate search queries for store-opening discovery.

    Args:
        mall_name: Mall or shopping center name (e.g. "Phoenix Mall").
        brand_name: Brand or store name (e.g. "Zara").
        custom_query: Single custom query to use as-is (overrides mall/brand if set).

    Returns:
        List of query strings. At least one query is always returned.
    """
    queries = []

    if custom_query and custom_query.strip():
        q = custom_query.strip()
        if CURRENT_YEAR not in q and "2025" not in q:
            queries.append(f"{q} {CURRENT_YEAR}")
        queries.append(q)
        return queries[:2] if len(queries) > 1 else queries

    if mall_name and mall_name.strip():
        mn = mall_name.strip()
        queries.append(f"Coming soon store {mn} {CURRENT_YEAR}")
        queries.append(f"New store opening {mn} {CURRENT_YEAR}")

    if brand_name and brand_name.strip():
        bn = brand_name.strip()
        queries.append(f"New store opening {bn} {CURRENT_YEAR}")
        queries.append(f"Coming soon {bn} store {CURRENT_YEAR}")

    if not queries:
        queries.append(f"Coming soon store mall {CURRENT_YEAR}")

    return queries[:3]