"""
AI-based analysis of extracted text using OpenAI or Gemini API.

- Step 7: Evaluates whether text refers to upcoming retail store openings.
- Step 8: Extracts structured store details (Mall, Brand, Expected Opening, Location, Confidence).
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import OPENAI_API_KEY, OPENAI_MODEL, GEMINI_API_KEY, GEMINI_MODEL, MAX_TEXT_CHUNK_FOR_AI

# Current date for prompts (ensures AI focuses on live/upcoming data, not past)
CURRENT_DATE_STR = datetime.now().strftime("%B %d, %Y")  # e.g. "February 03, 2026"
CURRENT_YEAR = str(datetime.now().year)

# Prefer OpenAI when key is set
OPENAI_AVAILABLE = False
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        OPENAI_AVAILABLE = True
    except Exception:
        _openai_client = None
else:
    _openai_client = None

# Fallback to Gemini
try:
    from google import genai
    _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    GEMINI_AVAILABLE = True
except Exception:
    _gemini_client = None
    GEMINI_AVAILABLE = False

# Either OpenAI or Gemini must be available
AI_AVAILABLE = OPENAI_AVAILABLE or GEMINI_AVAILABLE

# Source label for structured output (shows which AI provider was used)
AI_SOURCE_NAME = "OpenAI" if OPENAI_AVAILABLE else "Gemini"


PROMPT_IS_STORE_OPENING = """You are analyzing web content for retail intelligence.

Does the following text contain information about an UPCOMING or PLANNED retail store opening in a mall or shopping center? 
Answer with a single word: YES or NO.

Consider: new store announcements, "coming soon", "opening soon", planned openings, mall tenant news, brand expansion in malls.
Ignore: store closures, general mall news with no specific new store, unrelated retail news.

Text:
---
{text}
---

Answer (YES or NO):"""


PROMPT_EXTRACT_STRUCTURED = """You are extracting structured data about upcoming retail store openings from web content.

From the text below, extract ALL mentioned or implied upcoming store openings, "coming soon" tenants, new retail, or mall expansion. For each one provide:
- mall_name: Name of the mall or shopping center (required: infer from context if the article is about a specific mall)
- brand_name: Brand or store name (use "Unknown" if only "coming soon" or "new stores" mentioned without a name)
- expected_opening: Date or timeframe if mentioned (e.g. "March 2026", "Q2 2025", "Coming soon", "Unknown")
- location_context: Floor, zone, or nearby store references if mentioned (e.g. "Level 2 near H&M", or "Unknown")
- confidence: High if specific store and date, Medium if mall/store mentioned, Low if only general "coming soon"

If the text discusses a mall and mentions "coming soon", new stores, or redevelopment, extract at least one row with the mall name and whatever details are given. Use "Unknown" for missing fields.
Return ONLY a valid JSON array of objects, no other text. Example:
[{{"mall_name":"Phoenix Mall","brand_name":"Zara","expected_opening":"March 2026","location_context":"Level 2 near H&M","confidence":"High"}}]

Text:
---
{text}
---

JSON array:"""

# Combined extraction: store openings + vacated tenants + temporary events + latest mall updates
PROMPT_EXTRACT_COMBINED = """You are extracting retail intelligence from web content about a mall or shopping center.

From the text below, extract FOUR things:

1) store_openings: Array of UPCOMING or PLANNED new store openings (new tenants coming, new shop opening). Each object: mall_name, brand_name, expected_opening, location_context, confidence. Use "Unknown" for missing fields. If none, use [].

2) vacated_tenants: Array of stores that have CLOSED, VACATED, or are LEAVING the mall. Each object: mall_name, brand_name, closed_date (e.g. "January 2026", "Closed", "Unknown"), notes (brief reason or context if mentioned). Use "Unknown" for missing fields. If none, use [].

3) temporary_events: Array of TEMPORARY or UPCOMING events at or near the mall (concerts, circus, pop-ups, movie releases, seasonal photo ops, promotions). Each object: mall_name, event_name, date_or_range (e.g. "March 12–22, 2026", "June 12, 2026", "February 2026"), description (brief: e.g. "Broadway-style animal-free circus"), event_type (e.g. "concert", "circus", "movie", "pop-up", "promotion", "other"). Use "Unknown" or "" for missing fields. If none, use [].

4) latest_updates: Object with the LATEST general updates about the mall (hours, weather, operations). Include ONLY what the text actually mentions; for any field not mentioned use empty string "". Do not use "Unknown" for latest_updates—leave blank if no info:
- mall_name: Name of the mall/shopping center (use "" if not clear)
- address: Full address if given
- hours_weather: Hours changes, early closures, weather-related adjustments
- events: Any general events or announcements (if not already in temporary_events)
- key_updates: Other key info (operations, redevelopment, food court, tenant changes)
- stores_mentioned: Array of objects describing notable or featured stores. Each object MUST include store_name and why_mentioned (brief reason this store is highlighted, e.g. "Standalone Sephora opening in 2026", "Anchor tenant", "Food court upgrade"). Use [] if none mentioned.
- accessibility: Wheelchair access, parking, restrooms if mentioned

Extract ALL of: new tenants/coming soon, vacated/closed tenants, temporary events, and general latest updates. For latest_updates show each piece of information only when present in the text; omit fields with no info (use "").

IMPORTANT: Today is {current_date}. Include ONLY entries with dates in {current_year} or later (e.g. 2025, 2026). EXCLUDE any openings, events, or closures from 2023, 2024, or earlier—that data is outdated.

Return ONLY a single valid JSON object, no other text. Example:
{{"store_openings":[{{"mall_name":"Phoenix Mall","brand_name":"Zara","expected_opening":"March 2026","location_context":"Level 2","confidence":"High"}}],"vacated_tenants":[{{"mall_name":"Midland Park Mall","brand_name":"Sears","closed_date":"2024","notes":"Anchor closed"}}],"temporary_events":[{{"mall_name":"Midland Park Mall","event_name":"Venardos Circus Far Beyond","date_or_range":"March 12–22, 2026","description":"Animal-free circus in parking lot","event_type":"circus"}}],"latest_updates":{{"mall_name":"Midland Park Mall","address":"4511 N. Midkiff Drive, Texas","hours_weather":"Early closures in late January 2026","events":"","key_updates":"Over 90 stores, food court","stores_mentioned":[{{"store_name":"Dillard's","why_mentioned":"Anchor department store operating"}}],"accessibility":"Wheelchair-accessible entrances"}}}}

Text:
---
{text}
---

JSON object:"""


# Prompt for AI to generate mall/retail intel from user request (no web search)
PROMPT_GENERATE_MALL_INTEL = """You are a retail and mall intelligence assistant. Today's date is {current_date}.

CRITICAL: The user needs CURRENT and LIVE data. You MUST:
- Include ONLY information about upcoming openings, events, and updates from {current_year} onward (future or very recent).
- Do NOT include any data from 2023, 2024, or other past years—that is outdated.
- If you do not have specific, current information, say "I do not have current information" for that category—do NOT make up or use old training data.
- For expected_opening and event dates: use only {current_year} or later (e.g. "February 2026", "Spring 2026").

Provide detailed, factual information:

1) **Upcoming store openings / coming soon shops**: New tenants, brands opening, expected opening dates (2026+ only), suite or location.
2) **Temporary events**: Upcoming concerts, circus, pop-ups, seasonal events—dates must be {current_year} or later.
3) **Closed or vacated tenants**: Only recent closures (2025–{current_year}) with dates and notes.
4) **Latest mall updates**: Current hours, address, operations, redevelopment, food court, notable stores, accessibility.

Be specific with mall names, brand names, and dates. If you lack current information, state that clearly—do not use outdated data.

User request:
---
{user_prompt}
---

Your detailed response:"""


def _truncate_for_ai(text: str, max_chars: int = MAX_TEXT_CHUNK_FOR_AI) -> str:
    if not text or len(text) <= max_chars:
        return text or ""
    return text[:max_chars] + "\n\n[... text truncated for analysis ...]"


def _is_outdated_date(date_str: str) -> bool:
    """Returns True if date_str contains 2023 or 2024 (outdated for 2026 users)."""
    if not date_str:
        return False
    s = str(date_str)
    return "2023" in s or "2024" in s


def _call_ai(prompt: str, debug_label: str = "AI") -> Optional[str]:
    """Call OpenAI (preferred) or Gemini. Returns response text or None."""
    if OPENAI_AVAILABLE and _openai_client:
        try:
            response = _openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            if response and response.choices:
                text = response.choices[0].message.content
                if text:
                    return text.strip()
            print(f"  [{debug_label}] No text in OpenAI response")
        except Exception as e:
            print(f"  [{debug_label}] OpenAI ERROR: {e}")
            if GEMINI_AVAILABLE and _gemini_client:
                if debug_label == "AI":
                    debug_label = "Gemini (fallback)"
    if GEMINI_AVAILABLE and _gemini_client:
        try:
            response = _gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            if response and getattr(response, "text", None):
                return response.text.strip()
            print(f"  [{debug_label}] No text in Gemini response: {type(response)}")
        except Exception as e:
            print(f"  [{debug_label}] Gemini ERROR: {e}")
    else:
        print(f"  [{debug_label}] SKIP: No AI available. Set OPENAI_API_KEY or GEMINI_API_KEY.")
    return None


def generate_mall_intel(user_prompt: str, debug: bool = True) -> Optional[str]:
    """
    Send the user's prompt to AI (OpenAI or Gemini) and get a generated response (no web search).
    Returns the raw text from the AI, or None if unavailable.
    """
    if not user_prompt or not str(user_prompt).strip():
        if debug:
            print("  [Generate] SKIP: empty user prompt")
        return None
    prompt = PROMPT_GENERATE_MALL_INTEL.format(
        user_prompt=str(user_prompt).strip(),
        current_date=CURRENT_DATE_STR,
        current_year=CURRENT_YEAR,
    )
    return _call_ai(prompt, debug_label="Generate")


def is_about_store_opening(text: str, debug: bool = True) -> bool:
    """
    Step 7: AI content analysis.
    Returns True if the text appears to refer to upcoming store openings.
    """
    if not text or not text.strip():
        if debug:
            print("  [Relevance] SKIP: empty text")
        return False
    truncated = _truncate_for_ai(text)
    prompt = PROMPT_IS_STORE_OPENING.format(text=truncated)
    answer = _call_ai(prompt, debug_label="Relevance")
    if not answer:
        if debug:
            print("  [Relevance] Got no answer from Gemini -> treating as NO")
        return False
    is_yes = answer.upper().strip().startswith("YES")
    if debug:
        print(f"  [Relevance] Answer: {answer.strip()[:50]} -> {'YES' if is_yes else 'NO'}")
    return is_yes


def extract_combined(text: str, source_url: str = "", source_title: str = "", debug: bool = True) -> Dict[str, Any]:
    """
    Extract store openings, vacated tenants, temporary events, and latest mall updates in one Gemini call.
    Returns {"store_openings": [...], "vacated_tenants": [...], "temporary_events": [...], "latest_updates": {...} or None}.
    """
    if not text or not text.strip():
        if debug:
            print("  [Extract] SKIP: empty text")
        return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}
    truncated = _truncate_for_ai(text)
    prompt = PROMPT_EXTRACT_COMBINED.format(
        text=truncated,
        current_date=CURRENT_DATE_STR,
        current_year=CURRENT_YEAR,
    )
    raw = _call_ai(prompt, debug_label="Extract")
    if not raw:
        if debug:
            print("  [Extract] No response from Gemini -> empty")
        return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}

    raw = raw.strip()
    if debug:
        print(f"  [Extract] Raw response (first 400 chars): {raw[:400]}...")
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        if debug:
            print(f"  [Extract] JSON parse error: {e}. Trying to find {{...}} in response.")
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as e2:
                if debug:
                    print(f"  [Extract] JSON parse failed: {e2}")
                return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}
        else:
            return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}

    if not isinstance(data, dict):
        if debug:
            print(f"  [Extract] Response is not a dict (type={type(data).__name__})")
        return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}

    # Parse store_openings array
    store_openings = data.get("store_openings") or []
    if not isinstance(store_openings, list):
        store_openings = []
    result_rows = []
    for item in store_openings:
        if not isinstance(item, dict):
            continue
        row = {
            "mall_name": str(item.get("mall_name", "Unknown")).strip() or "Unknown",
            "brand_name": str(item.get("brand_name", "Unknown")).strip() or "Unknown",
            "expected_opening": str(item.get("expected_opening", "Unknown")).strip() or "Unknown",
            "location_context": str(item.get("location_context", "Unknown")).strip() or "Unknown",
            "confidence": str(item.get("confidence", "Medium")).strip() or "Medium",
        }
        if source_url:
            row["source_url"] = source_url
        if source_title:
            row["source_title"] = source_title
        if not _is_outdated_date(row.get("expected_opening", "")):
            result_rows.append(row)

    # Parse vacated_tenants array
    vacated_raw = data.get("vacated_tenants") or []
    if not isinstance(vacated_raw, list):
        vacated_raw = []
    vacated_rows = []
    for item in vacated_raw:
        if not isinstance(item, dict):
            continue
        row = {
            "mall_name": str(item.get("mall_name", "Unknown")).strip() or "Unknown",
            "brand_name": str(item.get("brand_name", "Unknown")).strip() or "Unknown",
            "closed_date": str(item.get("closed_date", "Unknown")).strip() or "Unknown",
            "notes": str(item.get("notes", "")).strip() or "",
        }
        if source_url:
            row["source_url"] = source_url
        if source_title:
            row["source_title"] = source_title
        if not _is_outdated_date(row.get("closed_date", "")):
            vacated_rows.append(row)

    # Parse temporary_events array
    events_raw = data.get("temporary_events") or []
    if not isinstance(events_raw, list):
        events_raw = []
    temporary_events_rows = []
    for item in events_raw:
        if not isinstance(item, dict):
            continue
        row = {
            "mall_name": str(item.get("mall_name", "Unknown")).strip() or "Unknown",
            "event_name": str(item.get("event_name", "")).strip() or "Unknown",
            "date_or_range": str(item.get("date_or_range", "")).strip() or "Unknown",
            "description": str(item.get("description", "")).strip() or "",
            "event_type": str(item.get("event_type", "other")).strip() or "other",
        }
        if source_url:
            row["source_url"] = source_url
        if source_title:
            row["source_title"] = source_title
        if not _is_outdated_date(row.get("date_or_range", "")):
            temporary_events_rows.append(row)

    # Parse latest_updates object (one per source)
    latest = data.get("latest_updates")
    update_record = None
    if isinstance(latest, dict) and any(str(v).strip() for v in latest.values() if v):
        stores_field = latest.get("stores_mentioned", [])
        structured_stores: List[Dict[str, str]] = []
        if isinstance(stores_field, list):
            for entry in stores_field:
                if isinstance(entry, dict):
                    store_name = str(entry.get("store_name") or entry.get("name") or "").strip()
                    reason = str(entry.get("why_mentioned") or entry.get("reason") or "").strip()
                    if store_name or reason:
                        structured_stores.append({
                            "store_name": store_name or "Unknown",
                            "why_mentioned": reason,
                        })
                elif isinstance(entry, str):
                    name = entry.strip()
                    if name:
                        structured_stores.append({"store_name": name, "why_mentioned": ""})
        elif isinstance(stores_field, dict):
            store_name = str(stores_field.get("store_name") or stores_field.get("name") or "").strip()
            reason = str(stores_field.get("why_mentioned") or stores_field.get("reason") or "").strip()
            if store_name or reason:
                structured_stores.append({
                    "store_name": store_name or "Unknown",
                    "why_mentioned": reason,
                })
        elif isinstance(stores_field, str):
            segments = [seg.strip() for seg in re.split(r"[,;\n]", stores_field) if seg.strip()]
            for seg in segments:
                structured_stores.append({"store_name": seg, "why_mentioned": ""})

        update_record = {
            "mall_name": str(latest.get("mall_name", "")).strip() or "Unknown",
            "address": str(latest.get("address", "")).strip() or "",
            "hours_weather": str(latest.get("hours_weather", "")).strip() or "",
            "events": str(latest.get("events", "")).strip() or "",
            "key_updates": str(latest.get("key_updates", "")).strip() or "",
            "stores_mentioned": structured_stores,
            "accessibility": str(latest.get("accessibility", "")).strip() or "",
            "source_url": source_url,
            "source_title": source_title,
        }
        if debug:
            print(f"  [Extract] Parsed {len(result_rows)} store-opening(s), {len(vacated_rows)} vacated tenant(s), {len(temporary_events_rows)} event(s), + 1 latest_update.")

    return {"store_openings": result_rows, "vacated_tenants": vacated_rows, "temporary_events": temporary_events_rows, "latest_updates": update_record}


def extract_store_details(text: str, source_url: str = "", source_title: str = "", debug: bool = True) -> List[Dict[str, Any]]:
    """
    Step 8 & 9: Structured data extraction + confidence.
    Returns list of dicts with keys: mall_name, brand_name, expected_opening, location_context, confidence.
    """
    if not text or not text.strip():
        if debug:
            print("  [Extract] SKIP: empty text")
        return []
    truncated = _truncate_for_ai(text)
    prompt = PROMPT_EXTRACT_STRUCTURED.format(text=truncated)
    raw = _call_ai(prompt, debug_label="Extract")
    if not raw:
        if debug:
            print("  [Extract] No response from Gemini -> 0 rows")
        return []

    # Parse JSON from response (sometimes model wraps in markdown code block)
    raw = raw.strip()
    if debug:
        print(f"  [Extract] Raw response (first 300 chars): {raw[:300]}...")
    for prefix in ("```json", "```"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        if debug:
            print(f"  [Extract] JSON parse error: {e}. Trying to find [...] in response.")
        # Try to find first [...] array
        match = re.search(r"\[[\s\S]*\]", raw)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as e2:
                if debug:
                    print(f"  [Extract] JSON parse failed again: {e2}")
                return []
        else:
            return []

    if not isinstance(data, list):
        if debug:
            print(f"  [Extract] Response is not a list (type={type(data).__name__}) -> 0 rows")
        return []

    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row = {
            "mall_name": str(item.get("mall_name", "Unknown")).strip() or "Unknown",
            "brand_name": str(item.get("brand_name", "Unknown")).strip() or "Unknown",
            "expected_opening": str(item.get("expected_opening", "Unknown")).strip() or "Unknown",
            "location_context": str(item.get("location_context", "Unknown")).strip() or "Unknown",
            "confidence": str(item.get("confidence", "Medium")).strip() or "Medium",
        }
        if source_url:
            row["source_url"] = source_url
        if source_title:
            row["source_title"] = source_title
        result.append(row)
    if debug:
        print(f"  [Extract] Parsed {len(result)} store-opening row(s).")
    return result


def analyze_extracted_text(
    text: str,
    source_url: str = "",
    source_title: str = "",
    skip_relevance_check: bool = False,
    debug: bool = True,
) -> Dict[str, Any]:
    """
    Full pipeline: check relevance (optional), then extract store openings + vacated tenants + temporary events + latest updates.
    Returns {"store_openings": [...], "vacated_tenants": [...], "temporary_events": [...], "latest_updates": {...} or None}.
    When skip_relevance_check=True, always runs extraction (new openings, vacated tenants, events, general updates).
    """
    if not text or not text.strip():
        return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}
    if not skip_relevance_check and not is_about_store_opening(text, debug=debug):
        if debug:
            print("  [Analyze] Page filtered out by relevance check (not about store opening).")
        return {"store_openings": [], "vacated_tenants": [], "temporary_events": [], "latest_updates": None}
    return extract_combined(text, source_url=source_url, source_title=source_title, debug=debug)
