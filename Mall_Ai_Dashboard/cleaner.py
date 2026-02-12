import csv
import os
import re

# -----------------------------
# INPUT → OUTPUT file mapping
# -----------------------------
FILES = [
    ("mall_shops_olddata.csv", "mall_shops_olddata_clean.csv"),
    ("mall_shops_newdata.csv", "mall_shops_newdata_clean.csv"),
]


def _is_email(s: str) -> bool:
    return bool(re.search(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", s))


def _is_phone_like(s: str) -> bool:
    if not s:
        return False
    # remove common separators
    digits = re.sub(r"[^0-9]", "", s)
    # consider it phone-like if it has at least 6 digits and most characters are digits/punct
    if len(digits) >= 6:
        # if original contains many letters, probably not a phone
        letters = re.sub(r"[^A-Za-z]", "", s)
        if len(letters) <= 2:
            return True
    return False


def _normalize_floor(f: str) -> str:
    if not f:
        return "-"
    fv = f.strip()
    if not fv or fv.lower() in ("-", "na", "n/a"):
        return "-"
    v = fv.lower()
    if "ground" in v:
        return "Ground Floor"
    if "first" in v:
        return "First Floor"
    if "second" in v:
        return "Second Floor"
    if "third" in v:
        return "Third Floor"
    if "food" in v:
        return "Food Court"
    if "fun" in v or "kids" in v:
        return "Fun Zone"
    if "multiplex" in v:
        return "Multiplex"
    # fallback: capitalize words
    return fv


def _normalize_phone(p: str) -> str:
    p = (p or "").strip()
    if not p or p.lower() in ("-", "na", "n/a"):
        return "-"
    # collapse multiple spaces, keep plus if present
    p = re.sub(r"\s+", " ", p)
    return p


def _normalize_name(n: str) -> str:
    return re.sub(r"\s+", " ", (n or "").strip())


def _is_address(name: str) -> bool:
    """Check if name looks like an address."""
    address_indicators = [
        "road", "street", "avenue", "lane", "drive", "boulevard",
        "madurai", "tamilnadu", "india", "tamil nadu",
        "pin", "pincode", "postal", "zip",
        r"\d{5,6}",  # 5-6 digit postal codes
        "no \d+",  # "No 31" pattern
        "chokkikulam", "gokhale"
    ]
    name_lower = name.lower()
    for indicator in address_indicators:
        if re.search(indicator, name_lower):
            return True
    return False


def _is_navigation_item(name: str) -> bool:
    """Check if name is a navigation/footer item, not a shop."""
    navigation_items = {
        "quick links", "events", "mall maps", "extra links",
        "about the mall", "offers", "event enquiry", "leasing enquiry",
        "monday to sunday", "cbra india", "vishaal mall",
        "about us", "contact us", "home", "directions",
        "hours", "visit us", "gift cards", "hotels"
    }
    return name.lower().strip() in navigation_items


def _is_mall_name_or_section_header(name: str) -> bool:
    """Check if name is a mall name, section header, or title rather than a shop name."""
    if not name:
        return False
    
    name_original = name.strip()
    name_lower = name_original.lower()
    
    # Skip if name contains source indicators like "Website Data", "Facebook Data", "Instagram Data"
    source_indicators = ['website data', 'facebook data', 'instagram data', 'web data', 'fb data', 'ig data']
    if any(indicator in name_lower for indicator in source_indicators):
        return True
    
    # Skip if name has multiple consecutive commas (likely metadata, not shop name)
    # Pattern like "OakViewMall,,,Website Data" or "Name,,,something"
    if ',,' in name_original or name_original.count(',') >= 2:
        return True
    
    # Skip if name ends with colon (section headers like "Bellevue Square:", "Lincoln Square:")
    if name_original.endswith(':'):
        return True
    
    # Skip if name starts with asterisk (section markers like "*Bellevue Place:")
    if name_original.startswith('*'):
        return True
    
    # Remove trailing colon and asterisk for pattern matching
    name_clean = name_original.rstrip(':').rstrip('*').strip()
    name_lower = name_clean.lower()
    
    # Common mall/section name patterns - names ending with location keywords
    location_endings = ['square', 'place', 'mall', 'center', 'centre', 'plaza', 'commons', 'district', 'village', 'town', 'park']
    
    # Check if name ends with a location keyword (like "Bellevue Square", "Lincoln Square")
    for ending in location_endings:
        if name_lower.endswith(' ' + ending) or name_lower == ending:
            # But allow if it contains shop-like words (store, shop, etc.) - these are actual shops
            if not any(word in name_lower for word in ['store', 'shop', 'boutique', 'outlet', 'restaurant', 'cafe', 'bar', '&']):
                return True
    
    # Pattern: [Location Name] + [Location Type] (e.g., "Bellevue Square", "Lincoln Square", "Bellevue Place")
    mall_patterns = [
        r'^[a-z]+\s+(square|place|mall|center|centre|plaza|commons|district|village|town|park)$',
        r'^[a-z]+\s+[a-z]+\s+(square|place|mall|center|centre|plaza)$',
    ]
    
    for pattern in mall_patterns:
        if re.match(pattern, name_lower):
            # But allow if it contains shop-like words
            if not any(word in name_lower for word in ['store', 'shop', 'boutique', 'outlet', 'restaurant', 'cafe', 'bar', '&']):
                return True
    
    # Common section header keywords
    section_keywords = [
        'square', 'place', 'commons', 'district', 'village',
        'food court', 'dining', 'entertainment', 'retail', 'shopping',
        'level', 'floor', 'wing', 'section', 'area', 'zone'
    ]
    
    # If name contains only section keywords and is short (2-3 words), likely a header
    words = name_lower.split()
    if len(words) <= 3:
        # Check if it's mostly section keywords
        section_word_count = sum(1 for word in words if any(keyword in word for keyword in section_keywords))
        if section_word_count >= len(words) * 0.7:  # 70% or more are section keywords
            # But allow if it contains shop-like words
            if not any(word in name_lower for word in ['store', 'shop', 'boutique', 'outlet', 'restaurant', 'cafe', 'bar', '&']):
                return True
    
    return False


def _is_domain_or_url(name: str) -> bool:
    """Check if name is a domain/URL (like vicspopcornomaha.com, www.example.com).
    
    This function is conservative - it only filters out CLEAR domains/URLs, not shop names
    that might contain .com as part of their branding (like "Shop.com" store).
    """
    if not name:
        return False
    
    name_lower = name.lower().strip()
    name_original = name.strip()
    
    # Skip if it starts with http:// or https:// (clear URL)
    if name_lower.startswith(('http://', 'https://')):
        return True
    
    # Skip if it starts with www. (clear domain)
    if name_lower.startswith('www.'):
        return True
    
    # Only filter domains that are clearly NOT shop names:
    # 1. Must contain a dot (for TLD)
    # 2. Must NOT contain spaces (domains don't have spaces)
    # 3. Must be all lowercase (shop names with .com branding usually have capitals)
    # 4. Must end with a TLD pattern
    if '.' in name_lower and ' ' not in name_lower:
        # Check if it ends with a TLD
        tld_pattern = r'\.[a-z]{2,}$'
        if re.search(tld_pattern, name_lower):
            # Only filter if it's all lowercase (domains are lowercase)
            # Shop names with .com branding usually have capitals (e.g., "Shop.com", "Store.com")
            if name_original == name_lower:
                # All lowercase with TLD = likely a domain
                # But check if it's very short (might be a shop name like "a.com")
                if len(name_lower) > 8:  # Domains are usually longer
                    return True
                # Very short names might be shop names, so be conservative
                return False
            # Has capitals = likely a shop name with .com branding, keep it
            return False
    
    return False


def _normalize_for_dedup(name: str) -> str:
    """Normalize shop name for fuzzy deduplication (remove common words, normalize spacing)."""
    if not name:
        return ""
    
    # Convert to lowercase
    normalized = name.lower().strip()
    
    # Remove common words that don't help with matching
    common_words = ["the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with", "by"]
    words = normalized.split()
    words = [w for w in words if w not in common_words]
    
    # Remove punctuation and special characters for comparison
    normalized = re.sub(r'[^\w\s]', '', ' '.join(words))
    
    # Remove extra spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    return normalized


def _are_similar_shops(name1: str, name2: str) -> bool:
    """Check if two shop names are similar (fuzzy matching for deduplication)."""
    if not name1 or not name2:
        return False
    
    # Normalize both names
    norm1 = _normalize_for_dedup(name1)
    norm2 = _normalize_for_dedup(name2)
    
    if not norm1 or not norm2:
        return False
    
    # Exact match after normalization
    if norm1 == norm2:
        return True
    
    # Extract key words (remove common words)
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    if not words1 or not words2:
        return False
    
    # Check if they share significant words
    common_words = words1.intersection(words2)
    
    # If they share at least 2 words, they might be the same shop
    if len(common_words) >= 2:
        return True
    
    # Check for word similarity (like "popcorn" vs "popper", "corn" vs "popcorn")
    unique1 = words1 - words2
    unique2 = words2 - words1
    
    # Check if unique words are similar (same root, contains, or similar meaning)
    for u1 in unique1:
        for u2 in unique2:
            # Check if words are similar (one contains the other or shares root)
            if u1 in u2 or u2 in u1:
                # If they share at least one common word, consider them similar
                if len(common_words) >= 1:
                    return True
            # Check if words share a common root (first 4+ characters)
            if len(u1) > 4 and len(u2) > 4:
                if u1[:4] == u2[:4] or u1[:5] == u2[:5]:
                    if len(common_words) >= 1:
                        return True
    
    # Special case: if one name contains all words from the other (with variations)
    # Example: "vics popcorn" vs "corn vics popper" - "vics" is common, "popcorn" vs "popper" are similar
    if len(common_words) >= 1:
        # Check if remaining words are similar
        for u1 in unique1:
            for u2 in unique2:
                # Check for similar words (popcorn/popper, corn/popcorn)
                if (u1.startswith(u2[:3]) or u2.startswith(u1[:3])) and len(u1) > 3 and len(u2) > 3:
                    return True
    
    return False


def _is_valid_shop(name: str, phone: str) -> bool:
    """Check if entry looks like a valid shop/kiosk."""
    # Must have a name
    if not name or len(name) < 2:
        return False
    
    # Skip if it's a domain/URL
    if _is_domain_or_url(name):
        return False
    
    # Skip if it's an address
    if _is_address(name):
        return False
    
    # Skip if it's a navigation item
    if _is_navigation_item(name):
        return False
    
    # Prefer entries with phone numbers, but allow some without if name looks valid
    if phone == "-" or not phone or phone.lower() in ("-", "na", "n/a"):
        # Without phone, check if name looks like a shop
        generic_words = {"quick links", "events", "links", "enquiry", "about", "contact", "mall"}
        if name.lower() in generic_words:
            return False
        # If name is too generic without phone, skip
        if len(name.split()) <= 1 and name.lower() in {"mall", "links", "events"}:
            return False
    
    return True


def clean_raw_file(input_file, output_file):
    shops = []
    current_shop = {}

    with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()

            # Blank line = end of one shop record
            if not line:
                if current_shop:
                    shops.append(current_shop)
                    current_shop = {}
                continue

            if ":" in line:
                key, value = line.split(":", 1)
                current_shop[key.strip().lower()] = value.strip()

    # Append last record
    if current_shop:
        shops.append(current_shop)

    seen = set()
    seen_names = []  # Keep list of normalized names for fuzzy matching
    cleaned_rows = []

    for shop in shops:
        raw_name = shop.get("shop_name", "")
        raw_phone = shop.get("phone", "")
        raw_floor = shop.get("floor", "")

        name = _normalize_name(raw_name)
        phone = _normalize_phone(raw_phone)
        floor = _normalize_floor(raw_floor)

        # Skip empty names
        if not name:
            continue

        # Remove emails and obvious junk
        if _is_email(name) or _is_email(phone):
            continue

        # Remove rows where name is actually a phone number
        if _is_phone_like(name):
            continue

        # If name contains URL/website markers, skip
        if "http" in name.lower() or "www." in name.lower():
            continue

        # Remove entries that are short noise
        if len(name) <= 1:
            continue

        # NEW: Filter out addresses and navigation items
        if _is_address(name):
            continue
        if _is_navigation_item(name):
            continue
        
        # NEW: Filter out mall names and section headers
        if _is_mall_name_or_section_header(name):
            continue
        
        # NEW: Validate it's a real shop/kiosk
        if not _is_valid_shop(name, phone):
            continue

        # Deduplicate: first check exact match, then fuzzy match for similar shop names
        unique_key = (name.lower(), phone.lower() if phone else "", floor.lower() if floor else "")
        if unique_key in seen:
            continue
        
        # Check for fuzzy matches with existing shops (same phone or no phone)
        is_duplicate = False
        normalized_name = _normalize_for_dedup(name)
        for existing_name, existing_phone, existing_floor in seen_names:
            # Only fuzzy match if phones match (or both have no phone)
            phones_match = (phone == existing_phone) or (not phone and not existing_phone) or (phone == "-" and existing_phone == "-")
            if phones_match and _are_similar_shops(name, existing_name):
                is_duplicate = True
                break
        
        if is_duplicate:
            continue
        
        seen.add(unique_key)
        seen_names.append((name, phone, floor))
        cleaned_rows.append((name, phone, floor))

    # Write cleaned CSV
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["shop_name", "phone", "floor"])
        for row in cleaned_rows:
            writer.writerow(row)

    print(f"✅ Cleaned & saved: {output_file}")


def clean_raw_text(text: str):
    """Clean labeled `text` (key:value blocks) and return a pandas DataFrame (shop_name, phone, floor)."""
    import pandas as pd

    shops = []
    current_shop = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_shop:
                shops.append(current_shop)
                current_shop = {}
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current_shop[key.strip().lower()] = value.strip()
    if current_shop:
        shops.append(current_shop)

    rows = []
    seen = set()
    seen_names = []  # Keep list of normalized names for fuzzy matching
    for shop in shops:
        raw_name = shop.get("shop_name", "")
        raw_phone = shop.get("phone", "")
        raw_floor = shop.get("floor", "")

        name = _normalize_name(raw_name)
        phone = _normalize_phone(raw_phone)
        floor = _normalize_floor(raw_floor)

        if not name:
            continue
        if _is_email(name) or _is_email(phone):
            continue
        if _is_phone_like(name):
            continue
        if "http" in name.lower() or "www." in name.lower():
            continue
        if len(name) <= 1:
            continue
        
        # NEW: Filter out addresses and navigation items
        if _is_address(name):
            continue
        if _is_navigation_item(name):
            continue
        
        # NEW: Filter out mall names and section headers
        if _is_mall_name_or_section_header(name):
            continue
        
        # NEW: Validate it's a real shop/kiosk
        if not _is_valid_shop(name, phone):
            continue

        # Deduplicate: first check exact match, then fuzzy match for similar shop names
        unique_key = (name.lower(), phone.lower() if phone else "", floor.lower() if floor else "")
        if unique_key in seen:
            continue
        
        # Check for fuzzy matches with existing shops (same phone or no phone)
        is_duplicate = False
        normalized_name = _normalize_for_dedup(name)
        for existing_name, existing_phone, existing_floor in seen_names:
            # Only fuzzy match if phones match (or both have no phone)
            phones_match = (phone == existing_phone) or (not phone and not existing_phone) or (phone == "-" and existing_phone == "-")
            if phones_match and _are_similar_shops(name, existing_name):
                is_duplicate = True
                break
        
        if is_duplicate:
            continue
        
        seen.add(unique_key)
        seen_names.append((name, phone, floor))
        rows.append({"shop_name": name, "phone": phone, "floor": floor})

    df = pd.DataFrame(rows, columns=["shop_name", "phone", "floor"]).astype(str)
    return df


def clean_all():
    """Run cleaning for all files defined in FILES.

    Returns a list of (input_file, output_file, status) tuples where status is True if cleaned.
    """
    results = []
    for input_file, output_file in FILES:
        if os.path.exists(input_file):
            try:
                clean_raw_file(input_file, output_file)
                results.append((input_file, output_file, True))
            except Exception:
                results.append((input_file, output_file, False))
        else:
            results.append((input_file, output_file, False))
    return results


def clean_records():
    return clean_all()


def main():
    for inp, outp, ok in clean_all():
        if not ok:
            print(f" File not found or failed: {inp}")


if __name__ == "__main__":
    main()
