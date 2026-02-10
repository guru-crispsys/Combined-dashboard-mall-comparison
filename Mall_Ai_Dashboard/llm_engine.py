import os
import requests
import json
import re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env BEFORE reading them.
# 1) Default search (current working dir and parents)
load_dotenv()

# 2) Also try the googlesearch/.env file at the project root so that
#    Mall_Ai_Dashboard can reuse the same OpenAI settings even when
#    it is run from a different working directory (e.g. via main_ui.py).
try:
    project_root = Path(__file__).resolve().parents[1]
    google_env = project_root / "googlesearch" / ".env"
    if google_env.exists():
        # Do not override variables that are already set in the environment.
        load_dotenv(dotenv_path=google_env, override=False)
except Exception:
    # Best‑effort only; failures here should not break the app.
    pass

# OpenAI API configuration (replaces Google Gemini)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()


def _call_openai_chat(
    prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    response_format: str | None = None,
    timeout_seconds: int = 120,
) -> str | None:
    """
    Helper to call OpenAI chat completions API with a single user prompt.

    Args:
        prompt: Full prompt text to send as the user message.
        temperature: Sampling temperature.
        max_tokens: Max tokens in the response.
        response_format: If "json_object", request JSON-mode; otherwise plain text.
        timeout_seconds: Request timeout.

    Returns:
        Response text (message content) or None on failure.
    """
    if not OPENAI_API_KEY:
        print("Warning: OPENAI_API_KEY is not set. Please add it to your environment or .env file.")
        return None

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    body: dict = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }

    if response_format == "json_object":
        body["response_format"] = {"type": "json_object"}

    try:
        r = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
            timeout=timeout_seconds,
        )
        r.raise_for_status()
    except requests.exceptions.Timeout:
        print("Warning: OpenAI API timed out.")
        return None
    except requests.exceptions.ConnectionError:
        print("Warning: Connection error - cannot reach OpenAI API.")
        return None
    except Exception as e:
        print(f"Warning: Error calling OpenAI API: {e}")
        return None

    try:
        resp_json = r.json()
        choices = resp_json.get("choices") or []
        if not choices:
            print("Warning: OpenAI API returned no choices.")
            return None
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        return content.strip() if isinstance(content, str) else None
    except Exception as e:
        print(f"Warning: Failed to parse OpenAI response: {e}")
        return None


def extract_shops_from_text(cleaned_text: str, url: str = "") -> list:
    """Extract shop names and details from cleaned website text using LLM.
    
    Args:
        cleaned_text: Clean text extracted from website HTML (no HTML tags)
        url: Optional URL for context
    
    Returns:
        List of dictionaries with shop_name, phone, floor, image_url
    """
    if not cleaned_text or len(cleaned_text.strip()) < 50:
        return []
    
    # Truncate text if too long (Gemini 1.5 Flash can handle up to 1M tokens, but we'll limit to 100K chars for safety)
    original_length = len(cleaned_text)
    max_text_length = 100000  # Gemini can handle much more text
    
    if len(cleaned_text) > max_text_length:
        cleaned_text = cleaned_text[:max_text_length] + "\n... (text truncated)"
        print(f"Text truncated to {max_text_length} characters (original: {original_length} chars)")
    
    prompt = f"""You are an expert data extraction assistant specializing in extracting shop/store information from mall website text.

TASK: Extract ALL shop names, stores, retailers, and businesses from the following mall website text. Be thorough and comprehensive.

Website URL (for context): {url}

Text from website:
{cleaned_text}

INSTRUCTIONS:
1. Carefully read through the entire text.
2. Identify ALL shop/store/retailer/business names mentioned anywhere on the page.
3. Pay SPECIAL attention to sections with headings like:
   - "Current Tenants"
   - "Tenants"
   - "Tenant Roster"
   - "Store Directory"
   - "Retailers"
   These sections usually contain the official list of all current tenants.
4. In those sections, rows often have the pattern:
   - "<unit code or number>  <Shop Name>  <area or square footage>"
   Example: "01    Kroger    69,133"
   Example: "FS5-2    Buffalo Wings & Rings    4,000"
   From such rows you MUST extract ONLY the shop/business name in the middle ("Kroger", "Buffalo Wings & Rings") as a tenant, and ignore the unit code and the area/square footage.
5. For each shop, try to find associated information (phone, floor, image URL) if mentioned nearby.
6. Extract shop names even if they appear in:
   - bullet lists
   - cards or tiles
   - tables with codes and sizes
   - headings or inline text
7. Look for patterns like: "Store Name", "Shop Name", retailer names, brand names, business names.
8. Skip navigation/UI text like: Home, About, Contact, Search, Sign In, Menu, Cart, See More, Learn More, Shop, Store, Terms, Privacy, Cookie, Careers, Leasing, Company, Corporate.
9. If the SAME shop name appears multiple times as separate entries (for example, multiple cards or units for "Banter by Piercing Pagoda"), you MUST output ONE LINE PER OCCURRENCE. Do NOT merge or de-duplicate shops with the same name.

OUTPUT FORMAT (PLAIN TEXT ONLY):
- Return ONLY plain text (no JSON, no markdown, no code blocks).
- Each shop MUST be on its own line.
- Each line MUST be in this exact pipe-separated format:
  Shop Name | Phone | Floor | ImageURL

Where:
- Shop Name: exact shop/store/business name.
- Phone: phone number if found near the shop, else empty string.
- Floor: floor/level info if found (e.g. "Ground Floor", "Level 2", "Food Court"), else empty string.
- ImageURL: image URL if found, else empty string.

EXAMPLE (FORMAT ONLY):
Jewellery Shop | +0452 2555110 | Ground Floor | 
Candere | +91 99526 11220 | Ground Floor | 

CRITICAL:
- Do NOT wrap the output in JSON.
- Do NOT add bullets, numbering, or explanations.
- Do NOT add headers or labels.
- Return ONLY the list of shops, one per line, using the exact pipe format."""

    # Call OpenAI (plain text response)
    raw = _call_openai_chat(
        prompt,
        temperature=0.1,
        max_tokens=8192,
        response_format=None,
        timeout_seconds=120,
    )

    if not raw:
        print("Warning: Empty response from LLM when extracting shops from text")
        return []

    try:
        # Parse plain-text pipe-separated lines into shop dicts.
        # IMPORTANT: do NOT remove duplicates – return exactly what the AI extracted.
        shops = []
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        for line in lines:
            # Skip obvious non-data lines if the model misbehaves
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if not parts:
                continue
            name = parts[0]
            if not name or len(name) < 2:
                continue

            phone = parts[1] if len(parts) > 1 else ""
            floor = parts[2] if len(parts) > 2 else ""
            image_url = parts[3] if len(parts) > 3 else ""

            shops.append({
                "shop_name": name,
                "phone": phone,
                "floor": floor,
                "image_url": image_url,
            })
        
        # Return raw list with possible duplicates, as requested.
        return shops

    except Exception as e:
        print(f"Warning: Error extracting shops from text using LLM: {str(e)}")
        return []


def extract_coming_soon_shops_from_text(cleaned_text: str, url: str = "") -> list:
    """Extract 'coming soon' shops, kiosks, and businesses from cleaned website text using AI.
    
    Args:
        cleaned_text: Clean text extracted from website HTML (no HTML tags)
        url: Optional URL for context
    
    Returns:
        List of shop/business names that are marked as "coming soon"
    """
    if not cleaned_text or len(cleaned_text.strip()) < 50:
        return []
    
    # Truncate text if too long
    original_length = len(cleaned_text)
    max_text_length = 100000
    if len(cleaned_text) > max_text_length:
        cleaned_text = cleaned_text[:max_text_length] + "\n... (text truncated)"
        print(f"Text truncated to {max_text_length} characters for coming soon extraction")
    
    prompt = f"""You are an expert data extraction assistant specializing in identifying "coming soon" shops, kiosks, and businesses from mall website text.

TASK: Extract ALL shops, stores, kiosks, retailers, and businesses that are marked as "coming soon", "opening soon", "opening", "under construction", "opening in [date]", or similar future opening indicators.

Website URL (for context): {url}

Text from website:
{cleaned_text}

INSTRUCTIONS:
1. Carefully read through the entire text
2. Look for keywords and phrases like:
   - "Coming Soon"
   - "Opening Soon"
   - "Opening"
   - "Opening in [month/year]"
   - "Opening [date]"
   - "Under Construction"
   - "Opening This [season]"
   - "Opening Next [month]"
   - "Opening [year]"
   - "Opening Soon - [shop name]"
   - "Coming Soon - [shop name]"
   - Any shop name followed by "coming soon" or "opening soon"
3. Extract the shop/business/kiosk name associated with these indicators
4. Include kiosks, pop-ups, temporary stores, and permanent stores
5. Extract even if the format is: "Shop Name - Coming Soon" or "Coming Soon: Shop Name"

Return ONLY valid JSON in this EXACT format (no markdown, no code blocks, no explanations):
{{
  "coming_soon_shops": [
    "Shop Name 1",
    "Shop Name 2",
    "Kiosk Name 1"
  ]
}}

CRITICAL EXTRACTION RULES:
1. Extract ALL shops/kiosks/businesses marked as coming soon - be comprehensive
2. Shop names are typically 2-100 characters, contain letters, and are proper business/brand names
3. Include kiosks, pop-ups, temporary stores, and permanent stores
4. Look for shops mentioned near phrases like "coming soon", "opening soon", "opening", etc.
5. Remove duplicates (same shop name should appear only once)
6. Extract shops even if they appear in different sections or formats
7. If no coming soon shops found, return: {{"coming_soon_shops": []}}
8. Return ONLY the JSON object - no markdown formatting, no code blocks, no explanations
9. Only extract shops that are explicitly marked as coming soon/opening soon - do not include existing shops

Be thorough and extract all coming soon shops, kiosks, and businesses you can find in the text."""

    # Call OpenAI in JSON mode
    raw = _call_openai_chat(
        prompt,
        temperature=0.1,
        max_tokens=8192,
        response_format="json_object",
        timeout_seconds=120,
    )

    if not raw:
        print("Warning: Empty response from AI when extracting coming soon shops")
        return []

    try:
        data = json.loads(raw)

        # Extract coming soon shops from response
        coming_soon_shops = []
        if isinstance(data, dict) and "coming_soon_shops" in data:
            shops_list = data["coming_soon_shops"]
            if isinstance(shops_list, list):
                for shop_name in shops_list:
                    if isinstance(shop_name, str):
                        shop_name = shop_name.strip()
                        if shop_name and len(shop_name) >= 2:
                            # Skip if it's just "coming soon" or "opening soon" without a shop name
                            if shop_name.lower() in ["coming soon", "opening soon", "opening", "coming"]:
                                continue
                            coming_soon_shops.append(shop_name)
        
        # Remove duplicates (case-insensitive)
        seen = set()
        unique_shops = []
        for shop in coming_soon_shops:
            name_key = shop.lower()
            if name_key not in seen:
                seen.add(name_key)
                unique_shops.append(shop)
        
        return unique_shops

    except Exception as e:
        print(f"Warning: Error extracting coming soon shops from text using AI: {str(e)}")
        return []


def validate_shop_names(shop_names: list) -> list:
    """Validate shop names using AI to filter out non-shop entries like Facebook/Instagram post text.
    
    Args:
        shop_names: List of shop names to validate
    
    Returns:
        List of validated shop names (only real shops, not post text or invalid entries)
    """
    if not shop_names or len(shop_names) == 0:
        return []
    
    # Filter out obviously invalid entries first (quick filter)
    quick_filtered = []
    invalid_patterns = [
        'see all', 'unread', 'posted', 'reel', 'instagram', 'facebook',
        'recommend', 'reviews', 'closed now', 'parking', 'crafty',
        'winter', 'puffer', 'lunar new year', 'posted a new',
        'https://', 'www.', '.com', 'reviews)', 'recommend ('
    ]
    
    for shop in shop_names:
        if not shop or not isinstance(shop, str):
            continue
        shop_lower = shop.lower().strip()
        
        # Skip if too short or too long
        if len(shop_lower) < 2 or len(shop_lower) > 200:
            continue
        
        # Skip if contains invalid patterns
        if any(pattern in shop_lower for pattern in invalid_patterns):
            continue
        
        # Skip if it's mostly numbers or symbols
        if re.match(r'^[\d\s\-\+\(\)\.\,\:\;\!\?]+$', shop_lower):
            continue
        
        # Must contain at least one letter
        if not re.search(r'[a-zA-Z]', shop_lower):
            continue
        
        quick_filtered.append(shop.strip())
    
    if not quick_filtered:
        return []
    
    # If we have many shops, validate in batches
    if len(quick_filtered) > 20:
        # For large lists, use quick filter only (AI validation would be too slow)
        return quick_filtered
    
    # Use AI to validate remaining shops
    shop_list_text = "\n".join([f"- {shop}" for shop in quick_filtered])
    
    prompt = f"""You are an expert data validator. Your task is to identify which entries are REAL shop/store/business names vs invalid entries like social media post text, notifications, or other non-shop content.

List of entries to validate:
{shop_list_text}

INSTRUCTIONS:
1. For each entry, determine if it is a REAL shop/store/business name
2. REAL shop names are: business names, store names, brand names, retailer names, kiosk names
3. INVALID entries include: social media post text, notifications, URLs, reviews text, general descriptions, navigation text

Return ONLY valid JSON in this EXACT format:
{{
  "valid_shops": [
    "Shop Name 1",
    "Shop Name 2"
  ]
}}

CRITICAL RULES:
- Only include entries that are actual shop/store/business names
- Exclude: post descriptions, notifications, URLs, review text, general text
- Exclude: entries like "See allUnreadARRA TV posted a new reel"
- Exclude: entries like "84% recommend (6,911 Reviews)"
- Include: actual shop names like "vasantham super market", "Kannan store", "D-mart", "poorvika"
- Shop names are typically 2-50 characters, proper business names
- Return ONLY the JSON object - no markdown, no code blocks, no explanations"""

    # Call OpenAI in JSON mode
    raw = _call_openai_chat(
        prompt,
        temperature=0.1,
        max_tokens=4096,
        response_format="json_object",
        timeout_seconds=60,
    )

    if not raw:
        return quick_filtered  # Fallback to quick filter

    try:
        data = json.loads(raw)

        # Extract validated shops
        if isinstance(data, dict) and "valid_shops" in data:
            validated = data["valid_shops"]
            if isinstance(validated, list):
                return [s.strip() for s in validated if s and isinstance(s, str) and len(s.strip()) >= 2]

        return quick_filtered

    except Exception as e:
        print(f"Warning: Error validating shop names with AI: {e}, using quick filter results")
        return quick_filtered


def _clean_shop_names_text(text: str) -> str:
    """Clean shop names text by removing notification text, URLs, and invalid entries.
    Returns clean, readable shop names in a well-formatted string."""
    if not text or text == "N/A" or "not analyzed" in text.lower():
        return text
    
    # Extract shop names from the text (format: "New shops added from X: shop1, shop2, shop3")
    # or "Vacant shops removed from X: shop1, shop2"
    prefix_match = re.match(r'^(.*?:\s*)(.*)$', text)
    if prefix_match:
        prefix = prefix_match.group(1)
        shops_text = prefix_match.group(2)
    else:
        prefix = ""
        shops_text = text
    
    # Split by comma and clean each shop name
    shop_parts = [s.strip() for s in shops_text.split(',')]
    valid_shops = []
    
    for shop in shop_parts:
        shop = shop.strip()
        if not shop:
            continue
        
        # Skip if contains notification text
        if any(word in shop.lower() for word in ['notification', 'unread', 'see all', 'posted', 'reels', 'including']):
            continue
        
        # Skip if contains URL
        if 'http' in shop.lower() or 'www.' in shop.lower() or '.com' in shop.lower():
            continue
        
        # Skip if too long (likely not a shop name)
        if len(shop) > 100:
            continue
        
        # Skip if looks like a phone number
        if re.match(r'^[\d\s\-\+\(\)]+$', shop):
            continue
        
        # Skip if contains backslashes or weird characters (corrupted text)
        if '\\' in shop or shop.count('"') > 2:
            continue
        
        # Must have at least 2 characters and some letters
        if len(shop) >= 2 and re.search(r'[a-zA-Z]', shop):
            # Clean up capitalization - make it more readable
            shop = shop.strip()
            # Basic capitalization fix (first letter uppercase, rest lowercase for single words)
            if len(shop.split()) == 1 and shop.islower():
                shop = shop.capitalize()
            valid_shops.append(shop)
    
    if not valid_shops:
        # Return appropriate message based on prefix
        if "new shops" in prefix.lower():
            return prefix.rstrip(': ') + ": No new shops detected"
        elif "vacant" in prefix.lower() or "removed" in prefix.lower():
            return prefix.rstrip(': ') + ": No shops removed"
        else:
            return text
    
    # Format shop names nicely - comma-separated, clear formatting
    cleaned_text = prefix + ", ".join(valid_shops)
    return cleaned_text


def _format_business_insights(insights: list) -> list:
    """Format business insights to be more readable and understandable."""
    if not insights:
        return []
    
    formatted = []
    for insight in insights:
        if not insight or insight == "N/A":
            continue
        
        # Clean up the insight text
        insight = str(insight).strip()
        
        # Remove excessive punctuation
        insight = re.sub(r'\.{2,}', '.', insight)
        insight = re.sub(r'\s+', ' ', insight)
        
        # Ensure it ends with proper punctuation
        if insight and not insight[-1] in '.!?':
            insight += '.'
        
        # Capitalize first letter
        if insight:
            insight = insight[0].upper() + insight[1:] if len(insight) > 1 else insight.upper()
        
        formatted.append(insight)
    
    return formatted if formatted else insights


def run_llm_analysis(structured_data, input_url=""):
    # Check if structured_data has source-specific data BEFORE converting to string
    # This ensures we can properly detect by_source
    if isinstance(structured_data, str):
        try:
            structured_dict = json.loads(structured_data)
        except:
            structured_dict = None
    else:
        structured_dict = structured_data
    
    # Extract only website URL from input_url (separate from Facebook/Instagram URLs)
    website_url_only = ""
    if input_url:
        import re
        from urllib.parse import urlparse
        url_pattern = re.compile(r"https?://[^\s,\n]+")
        urls = url_pattern.findall(input_url)
        # Find the first URL that's NOT Facebook or Instagram
        for url in urls:
            url_lower = url.lower()
            if 'facebook.com' not in url_lower and 'instagram.com' not in url_lower and 'fb.com' not in url_lower and 'instagr.am' not in url_lower:
                website_url_only = url
                break
        # If no website URL found, use first URL as fallback
        if not website_url_only and urls:
            website_url_only = urls[0]
    
    # Check for by_source and if it contains Facebook, Website, and/or Instagram sources
    has_source_data = False
    has_multiple_sources = False
    
    # Filter structured_data to only include Website Data for tenant analysis
    website_data_for_analysis = None
    
    if isinstance(structured_dict, dict) and "by_source" in structured_dict:
        has_source_data = True
        by_source = structured_dict.get("by_source", {})
        # Check if we have multiple sources (Facebook, Website, Instagram)
        sources = list(by_source.keys()) if by_source else []
        facebook_sources = [s for s in sources if 'facebook' in s.lower()]
        website_sources = [s for s in sources if 'website' in s.lower() or 'web' in s.lower()]
        instagram_sources = [s for s in sources if 'instagram' in s.lower()]
        has_multiple_sources = len(facebook_sources) > 0 or len(website_sources) > 0 or len(instagram_sources) > 0
        
        # Extract Website Data for tenant analysis
        if website_sources:
            website_source_key = website_sources[0]  # Use first website source
            if website_source_key in by_source:
                website_data_for_analysis = by_source[website_source_key]
                # Update main stats to use only website data for tenant analysis
                if website_data_for_analysis:
                    structured_dict["stats"] = structured_dict.get("stats", {}).copy()
                    structured_dict["new_shops"] = website_data_for_analysis.get("new_shops", [])
                    structured_dict["vacated_shops"] = structured_dict.get("vacated_shops", [])  # Vacated shops come from old data comparison
                    structured_dict["shifted_shops"] = website_data_for_analysis.get("shifted_shops", [])
                    structured_dict["still_existing"] = website_data_for_analysis.get("still_existing", [])
    
    # Convert to JSON string for the prompt
    structured_data = json.dumps(structured_dict if structured_dict else structured_data, indent=2)
    
    # Always generate reports - focus on Website and Overall (tenant analysis)
    if has_source_data:
        prompt = f"""
You are an AI mall analytics assistant analyzing tenant changes in a shopping mall. Generate a CLEAR, UNDERSTANDABLE, and PROFESSIONAL report.

CRITICAL REQUIREMENTS:
1. Extract ACTUAL data from the JSON - never use placeholders or "N/A"
2. Format all text in a CLEAR and UNDERSTANDABLE way
3. Use natural, readable language - avoid technical jargon
4. Make shop names easy to read (proper capitalization, clear formatting)

Data Structure:
{structured_data}

Input URLs:
{input_url}

INSTRUCTIONS:

1. EXTRACT TENANT DATA:
   - Find "stats" object: new_shops (count), vacated_shops (count), shifted_shops (count), still_existing (count)
   - Find "new_shops" array: Extract "shop_name" from EVERY object
   - Find "vacated_shops" array: Extract "shop_name" from EVERY object

2. CALCULATE OCCUPANCY TREND:
   - new_shops > vacated_shops → "Increase"
   - vacated_shops > new_shops → "Decrease"
   - new_shops == vacated_shops → "Stable"
   - Both are 0 → "No Change"

3. FORMAT SHOP NAMES (CLEAR AND READABLE):
   - Extract ALL shop names from arrays
   - Format as: "Shop Name 1, Shop Name 2, Shop Name 3" (comma-separated, clear)
   - Include count: "([COUNT] shops)"
   - If empty: "No new shops detected" or "No shops removed"

4. GENERATE BUSINESS INSIGHTS (UNDERSTANDABLE LANGUAGE):
   - Use actual numbers from stats
   - Write in clear, business-friendly language
   - Example: "The mall saw [X] new shops open while [Y] shops closed, resulting in a net change of [Z] shops."
   - Make insights actionable and easy to understand

Return ONLY valid JSON in this EXACT format (ONLY "overall" report - based on Website data):

{{
  "metadata": {{
    "mall_name": "Extract from URL or use 'Shopping Mall'",
    "address": "Extract from data or use 'Not Available'",
    "official_website": "{website_url_only if website_url_only else 'Not Available'}",
    "facebook_link": "Not Available",
    "instagram_link": "Not Available",
    "hashtags": ["#ShoppingMall", "#Retail"],
    "run_date": "{datetime.now().strftime('%Y-%m-%d')}"
  }},
  "overall": {{
    "occupancy_trend": "Increase or Decrease or Stable or No Change",
    "new_shops": "New shops added ([COUNT] shops): [LIST ALL SHOP NAMES FROM new_shops ARRAY, COMMA-SEPARATED, CLEAR FORMATTING]",
    "vacancy_changes": "Vacant shops removed ([COUNT] shops): [LIST ALL SHOP NAMES FROM vacated_shops ARRAY, COMMA-SEPARATED, CLEAR FORMATTING]",
    "business_insights": [
      "Clear, understandable insight about occupancy changes based on website data",
      "Net change analysis in plain language with actual numbers",
      "Business implications or trends in easy-to-understand language"
    ]
  }}
}}

FORMATTING RULES FOR CLEAR OUTPUT:

1. SHOP NAMES:
   - Extract from "shop_name" field in each array object
   - Format: "Shop Name 1, Shop Name 2, Shop Name 3"
   - Use proper capitalization
   - If many shops (>10), you can summarize: "Shop 1, Shop 2, ... and [X] more shops"

2. BUSINESS INSIGHTS:
   - Write in natural, business-friendly language
   - Example: "The mall experienced growth with 5 new shops opening, while 2 shops closed, resulting in a net increase of 3 shops."
   - Avoid technical terms - use plain English
   - Make it actionable and understandable

3. OCCUPANCY TREND:
   - Use clear labels: "Increase", "Decrease", "Stable", "No Change"
   - Match the actual data comparison

4. NO PLACEHOLDERS:
   - Never use "N/A", "Shop A", "Shop B", or placeholder text
   - Always extract real shop names from the data
   - If no data exists, use: "No new shops detected" or "No shops removed"

EXAMPLE OUTPUT (CLEAR AND UNDERSTANDABLE):

For data with 2 new shops and 1 vacated shop:
{{
  "overall": {{
    "occupancy_trend": "Increase",
    "new_shops": "New shops added (2 shops): Nike Store, Starbucks Coffee",
    "vacancy_changes": "Vacant shops removed (1 shop): Old Bookstore",
    "business_insights": [
      "The mall saw 2 new shops open while 1 shop closed, resulting in a net increase of 1 shop.",
      "This indicates positive growth in mall occupancy with new retail offerings.",
      "The occupancy trend shows an increase, suggesting healthy retail activity."
    ]
  }}
}}

IMPORTANT: Generate ONLY the "overall" report based on website data. Do NOT include "website" report.
Generate a CLEAR, UNDERSTANDABLE report from the actual data provided.
"""
    else:
        # Extract only website URL from input_url (separate from Facebook/Instagram URLs)
        if not website_url_only and input_url:
            import re
            url_pattern = re.compile(r"https?://[^\s,\n]+")
            urls = url_pattern.findall(input_url)
            # Find the first URL that's NOT Facebook or Instagram
            for url in urls:
                url_lower = url.lower()
                if 'facebook.com' not in url_lower and 'instagram.com' not in url_lower and 'fb.com' not in url_lower and 'instagr.am' not in url_lower:
                    website_url_only = url
                    break
            # If no website URL found, use first URL as fallback
            if not website_url_only and urls:
                website_url_only = urls[0]
        
        prompt = f"""
You are an AI mall analytics assistant. Generate a CLEAR, UNDERSTANDABLE, and PROFESSIONAL summary report based on website data.

CRITICAL REQUIREMENTS:
1. Extract ACTUAL data from the JSON - never use placeholders
2. Format all text in a CLEAR and UNDERSTANDABLE way
3. Use natural, readable language - avoid technical jargon
4. Make shop names easy to read (proper capitalization, clear formatting)
5. Generate ONLY "overall" report based on website scraping data

Data:
{structured_data}

Input URLs:
{input_url}

Return ONLY valid JSON in this EXACT format (ONLY "overall" report):

{{
  "metadata": {{
    "mall_name": "Mall Name (extract from URL or data)",
    "address": "Mall Address (extract if available)",
    "official_website": "{website_url_only if website_url_only else 'Not Available'}",
    "facebook_link": "Not Available",
    "instagram_link": "Not Available",
    "hashtags": ["#ShoppingMall", "#Retail"],
    "run_date": "{datetime.now().strftime('%Y-%m-%d')}"
  }},
  "overall": {{
    "occupancy_trend": "Increase or Decrease or Stable or No Change",
    "new_shops": "New shops added ([COUNT] shops): [LIST ALL SHOP NAMES FROM new_shops ARRAY, COMMA-SEPARATED, CLEAR FORMATTING]",
    "vacancy_changes": "Vacant shops removed ([COUNT] shops): [LIST ALL SHOP NAMES FROM vacated_shops ARRAY, COMMA-SEPARATED, CLEAR FORMATTING]",
    "business_insights": [
      "Clear, understandable insight about occupancy changes based on website data",
      "Net change analysis written for business readers with actual numbers",
      "Actionable business implications or trends in easy-to-understand language"
    ]
  }}
}}

FORMATTING RULES FOR CLEAR OUTPUT:

1. SHOP NAMES:
   - Extract ONLY the "shop_name" field from "new_shops" and "vacated_shops" arrays
   - Format: "Shop Name 1, Shop Name 2, Shop Name 3" (comma-separated, clear)
   - Use proper capitalization
   - SKIP if shop_name contains: notification text, URLs, or is >100 characters
   - If no valid shops found: "No new shops detected" or "No shops removed"

2. BUSINESS INSIGHTS:
   - Write in natural, business-friendly language
   - Example: "The mall saw 3 new shops open while 1 shop closed, resulting in a net increase of 2 shops."
   - Avoid technical terms - use plain English
   - Make it actionable and understandable

3. OCCUPANCY TREND:
   - Calculate from stats: new_shops count vs vacated_shops count
   - Use clear labels: "Increase", "Decrease", "Stable", "No Change"

4. NO PLACEHOLDERS:
   - Never use "N/A", "Shop A", "Shop B", or placeholder text
   - Always extract real shop names from the data
- IMPORTANT: Tenant analysis uses ONLY Website scraping data. Facebook/Instagram are post data, not tenant listings.

Generate a CLEAR, UNDERSTANDABLE report from the actual data provided.
"""

    # Call OpenAI in JSON mode
    raw = _call_openai_chat(
        prompt,
        temperature=0.1,
        max_tokens=8192,
        response_format="json_object",
        timeout_seconds=120,
    )

    if not raw:
        return json.dumps({"error": "Empty response from OpenAI API. Please check your API key and connection."})

    try:
        data = json.loads(raw)

        # 🔐 HARDEN OUTPUT (guaranteed keys)
        # For tenant analysis, we only need "overall" report based on website data
        if has_source_data:
            # Check if we have "overall" report in the response
            if isinstance(data, dict) and "overall" in data:
                # We have overall report - use it directly
                overall_data = data["overall"]
                new_shops_raw = overall_data.get("new_shops", "N/A")
                vacancy_raw = overall_data.get("vacancy_changes", "N/A")
                        
                result = {
                    "overall": {
                        "occupancy_trend": overall_data.get("occupancy_trend", "N/A"),
                            "new_shops": _clean_shop_names_text(str(new_shops_raw)) if isinstance(new_shops_raw, str) else new_shops_raw,
                            "vacancy_changes": _clean_shop_names_text(str(vacancy_raw)) if isinstance(vacancy_raw, str) else vacancy_raw,
                        "business_insights": _format_business_insights(overall_data.get("business_insights", []))
                            }
                }
                
                # Add metadata if present
                if "metadata" in data:
                    result["metadata"] = data["metadata"]
                
                return json.dumps(result)
            elif isinstance(data, dict) and "occupancy_trend" in data:
                # LLM returned single report structure - wrap it in "overall"
                new_shops_raw = data.get("new_shops", "N/A")
                vacancy_raw = data.get("vacancy_changes", "N/A")
                
                result = {
                    "overall": {
                    "occupancy_trend": data.get("occupancy_trend", "N/A"),
                    "new_shops": _clean_shop_names_text(str(new_shops_raw)) if isinstance(new_shops_raw, str) else new_shops_raw,
                    "vacancy_changes": _clean_shop_names_text(str(vacancy_raw)) if isinstance(vacancy_raw, str) else vacancy_raw,
                        "business_insights": _format_business_insights(data.get("business_insights", []))
                    }
                }
                
                # Add metadata if present
                if "metadata" in data:
                    result["metadata"] = data["metadata"]
                
                return json.dumps(result)
            else:
                # Fallback - create empty overall report
                result = {
                    "overall": {
                        "occupancy_trend": "N/A - Data not analyzed",
                        "new_shops": "N/A - Data not analyzed",
                        "vacancy_changes": "N/A - Data not analyzed",
                        "business_insights": []
                    }
                }
                if "metadata" in data:
                    result["metadata"] = data["metadata"]
                return json.dumps(result)
        else:
            # No source data - single report structure (wrap in overall for consistency)
            if isinstance(data, dict) and ("facebook" in data or "website" in data or "instagram" in data or "overall" in data):
                # Already has structure, return as-is
                result = {}
                report_types = ["facebook", "website"]
                if "instagram" in data:
                    report_types.append("instagram")
                report_types.append("overall")
                
                for report_type in report_types:
                    if report_type in data:
                        report_data = data[report_type]
                        new_shops_raw = report_data.get("new_shops", "N/A")
                        vacancy_raw = report_data.get("vacancy_changes", "N/A")
                        result[report_type] = {
                            "occupancy_trend": report_data.get("occupancy_trend", "N/A"),
                            "new_shops": _clean_shop_names_text(str(new_shops_raw)) if isinstance(new_shops_raw, str) else new_shops_raw,
                            "vacancy_changes": _clean_shop_names_text(str(vacancy_raw)) if isinstance(vacancy_raw, str) else vacancy_raw,
                            "business_insights": _format_business_insights(report_data.get("business_insights", []))
                        }
                if result:
                    if "metadata" in data:
                        result["metadata"] = data["metadata"]
                    return json.dumps(result)
                else:
                    # Fallback to single report wrapped in overall
                    new_shops_raw = data.get("new_shops", "N/A")
                    vacancy_raw = data.get("vacancy_changes", "N/A")
                    return json.dumps({
                        "overall": {
                            "occupancy_trend": data.get("occupancy_trend", "N/A"),
                            "new_shops": _clean_shop_names_text(str(new_shops_raw)) if isinstance(new_shops_raw, str) else new_shops_raw,
                            "vacancy_changes": _clean_shop_names_text(str(vacancy_raw)) if isinstance(vacancy_raw, str) else vacancy_raw,
                            "business_insights": _format_business_insights(data.get("business_insights", []))
                        }
                    })
            else:
                # Old structure - single report (wrap in overall for consistency)
                new_shops_raw = data.get("new_shops", "N/A")
                vacancy_raw = data.get("vacancy_changes", "N/A")
                return json.dumps({
                    "overall": {
                        "occupancy_trend": data.get("occupancy_trend", "N/A"),
                        "new_shops": _clean_shop_names_text(str(new_shops_raw)) if isinstance(new_shops_raw, str) else new_shops_raw,
                        "vacancy_changes": _clean_shop_names_text(str(vacancy_raw)) if isinstance(vacancy_raw, str) else vacancy_raw,
                        "business_insights": data.get("business_insights", [])
                    }
                })

    except requests.exceptions.Timeout:
        return json.dumps({"error": "LLM timed out. Try again."})

    except requests.exceptions.ConnectionError:
        return json.dumps({"error": "Connection error: cannot reach Google AI Studio API. Please check your internet connection and API key."})

    except Exception as e:
        return json.dumps({"error": str(e)})