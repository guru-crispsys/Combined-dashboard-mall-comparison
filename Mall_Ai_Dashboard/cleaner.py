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


def _is_valid_shop(name: str, phone: str) -> bool:
    """Check if entry looks like a valid shop/kiosk."""
    # Must have a name
    if not name or len(name) < 2:
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

        # Deduplicate by combination of name, phone, and floor (all must match to be duplicate)
        # This allows multiple shops with same name but different phone/floor
        unique_key = (name.lower(), phone.lower() if phone else "", floor.lower() if floor else "")
        if unique_key in seen:
            continue
        seen.add(unique_key)

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

        # Deduplicate by combination of name, phone, and floor (all must match to be duplicate)
        # This allows multiple shops with same name but different phone/floor
        unique_key = (name.lower(), phone.lower() if phone else "", floor.lower() if floor else "")
        if unique_key in seen:
            continue
        seen.add(unique_key)
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
