import pandas as pd


def normalize_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip().lower()


def _ensure_df(obj):
    """If `obj` is a path (str), read CSV; if it's already a DataFrame, return it."""
    if isinstance(obj, pd.DataFrame):
        df = obj.copy()
    elif isinstance(obj, str):
        df = pd.read_csv(obj)
    else:
        # try to build DataFrame
        df = pd.DataFrame(obj)
    return df


def compare_shops(old_csv, new_csv, preserve_source=False, website_only=False):
    old_df = _ensure_df(old_csv)
    new_df = _ensure_df(new_csv)

    # Normalize column names
    old_df.columns = old_df.columns.str.lower()
    new_df.columns = new_df.columns.str.lower()

    # Check if source column exists in new_df
    has_source = preserve_source and 'source' in new_df.columns
    
    # Keep original new_df for source-specific comparisons
    original_new_df = new_df.copy()
    
    # If website_only is True, filter BOTH old_df and new_df to only include website data
    # This ensures vacated shops = website tenants from OLD that are no longer in website NEW
    # Facebook and Instagram are post data, not shop/tenant data — exclude from comparison
    if website_only:
        if has_source:
            website_sources = [s for s in original_new_df['source'].unique() if 'website' in str(s).lower() or 'web' in str(s).lower()]
            if website_sources:
                new_df = original_new_df[original_new_df['source'].isin(website_sources)].copy()
        # Also filter old_df to website-only if it has source (e.g. from previous merged export)
        if 'source' in old_df.columns:
            old_website_sources = [s for s in old_df['source'].unique() if s and ('website' in str(s).lower() or 'web' in str(s).lower())]
            if old_website_sources:
                old_df = old_df[old_df['source'].isin(old_website_sources)].copy()
    
    # Normalize shop names for comparison
    old_df["shop_key"] = old_df["shop_name"].apply(normalize_text)
    new_df["shop_key"] = new_df["shop_name"].apply(normalize_text)
    # Also normalize original_new_df for source-specific comparisons
    if has_source:
        original_new_df["shop_key"] = original_new_df["shop_name"].apply(normalize_text)

    # --------------------
    # Overall comparison (website data only if website_only=True)
    # --------------------
    new_shops = new_df[
        ~new_df["shop_key"].isin(old_df["shop_key"])
    ]

    vacated_shops = old_df[
        ~old_df["shop_key"].isin(new_df["shop_key"])
    ]

    still_existing = new_df[
        new_df["shop_key"].isin(old_df["shop_key"])
    ]

    merged = pd.merge(
        old_df,
        new_df,
        on="shop_key",
        suffixes=("_old", "_new")
    )

    shifted_shops = merged[
        merged["floor_old"] != merged["floor_new"]
    ][
        ["shop_name_old", "floor_old", "floor_new"]
    ].rename(columns={"shop_name_old": "shop_name"})

    result = {
        "stats": {
            "old_count": len(old_df),
            "new_count": len(new_df),
            "new_shops": len(new_shops),
            "vacated_shops": len(vacated_shops),
            "shifted_shops": len(shifted_shops),
            "still_existing": len(still_existing)
        },
        "new_shops": new_shops[["shop_name", "phone", "floor"]].to_dict("records") if not new_shops.empty else [],
        "vacated_shops": vacated_shops[["shop_name", "phone", "floor"]].to_dict("records") if not vacated_shops.empty else [],
        "shifted_shops": shifted_shops.to_dict("records") if not shifted_shops.empty else [],
        "still_existing": still_existing[["shop_name", "phone", "floor"]].to_dict("records") if not still_existing.empty else []
    }

    # --------------------
    # Separate comparisons by source (only Website for tenant analysis)
    # --------------------
    if has_source:
        source_comparisons = {}
        # Use original_new_df to get all sources for display purposes
        sources = original_new_df['source'].unique()
        
        # Only include Website Data for tenant analysis
        # Facebook and Instagram are post data, not tenant data
        website_sources = [s for s in sources if 'website' in str(s).lower() or 'web' in str(s).lower()]
        
        for source in sources:
            source_new_df = original_new_df[original_new_df['source'] == source]
            
            # For tenant analysis, only process Website sources
            # Facebook/Instagram are kept for display but not used in tenant comparison
            if website_only and source.lower() not in [s.lower() for s in website_sources]:
                # Skip Facebook/Instagram for tenant analysis
                continue
            
            source_new_shops = source_new_df[
                ~source_new_df["shop_key"].isin(old_df["shop_key"])
            ]
            
            source_still_existing = source_new_df[
                source_new_df["shop_key"].isin(old_df["shop_key"])
            ]
            
            source_merged = pd.merge(
                old_df,
                source_new_df,
                on="shop_key",
                suffixes=("_old", "_new")
            )
            
            source_shifted = source_merged[
                source_merged["floor_old"] != source_merged["floor_new"]
            ][
                ["shop_name_old", "floor_old", "floor_new"]
            ].rename(columns={"shop_name_old": "shop_name"}) if not source_merged.empty else pd.DataFrame()
            
            source_comparisons[source] = {
                "stats": {
                    "old_count": len(old_df),
                    "new_count": len(source_new_df),
                    "new_shops": len(source_new_shops),
                    "vacated_shops": 0,  # Vacated shops are from old data, not source-specific
                    "shifted_shops": len(source_shifted),
                    "still_existing": len(source_still_existing)
                },
                "new_shops": source_new_shops[["shop_name", "phone", "floor"]].to_dict("records") if not source_new_shops.empty else [],
                "vacated_shops": [],  # Vacated shops are from old data
                "shifted_shops": source_shifted.to_dict("records") if not source_shifted.empty else [],
                "still_existing": source_still_existing[["shop_name", "phone", "floor"]].to_dict("records") if not source_still_existing.empty else []
            }
        
        result["by_source"] = source_comparisons

    return result


def merge_shops_to_tenant_list(existing_tenant_list, newly_extracted_shops):
    """Merge newly extracted shops into existing tenant list.
    
    Args:
        existing_tenant_list: DataFrame or path to CSV with existing tenants (columns: shop_name, phone, floor, etc.)
        newly_extracted_shops: DataFrame or list of dicts with newly extracted shops
    
    Returns:
        DataFrame with merged tenant list (existing + new shops, no duplicates)
    """
    # Convert inputs to DataFrames
    existing_df = _ensure_df(existing_tenant_list)
    new_df = _ensure_df(newly_extracted_shops)
    
    if existing_df.empty:
        # If no existing tenants, just return the new shops
        return new_df.copy()
    
    if new_df.empty:
        # If no new shops, return existing list
        return existing_df.copy()
    
    # Normalize column names
    existing_df.columns = existing_df.columns.str.lower()
    new_df.columns = new_df.columns.str.lower()
    
    # Ensure both have shop_name column
    if 'shop_name' not in existing_df.columns:
        raise ValueError("Existing tenant list must have 'shop_name' column")
    if 'shop_name' not in new_df.columns:
        raise ValueError("Newly extracted shops must have 'shop_name' column")
    
    # Normalize shop names for duplicate detection
    existing_df["shop_key"] = existing_df["shop_name"].apply(normalize_text)
    new_df["shop_key"] = new_df["shop_name"].apply(normalize_text)
    
    # Find shops that are truly new (not in existing list)
    new_shops_only = new_df[~new_df["shop_key"].isin(existing_df["shop_key"])].copy()
    
    # Remove the shop_key column before merging
    if 'shop_key' in existing_df.columns:
        existing_df = existing_df.drop(columns=['shop_key'])
    if 'shop_key' in new_shops_only.columns:
        new_shops_only = new_shops_only.drop(columns=['shop_key'])
    
    # Combine existing tenants with new shops
    merged_df = pd.concat([existing_df, new_shops_only], ignore_index=True)
    
    # Remove any duplicate shop names (case-insensitive) that might have been created
    merged_df["shop_key"] = merged_df["shop_name"].apply(normalize_text)
    merged_df = merged_df.drop_duplicates(subset=['shop_key'], keep='first')
    merged_df = merged_df.drop(columns=['shop_key'])
    
    return merged_df
