import streamlit as st
import pandas as pd
import json
import os
from urllib.parse import urlparse

from llm_engine import run_llm_analysis
from data_processor import compare_shops, merge_shops_to_tenant_list
from scrape_and_clean import scrape_and_prepare
from facebook_scraper import scrape_facebook_simple
from instagram import scrape_instagram_simple
from excel_exporter import create_mall_excel_export

st.set_page_config(page_title="Mall AI Dashboard", layout="wide")

# --- Custom styling for a cleaner, more attractive UI ---
st.markdown("""
<style>
/* Page background and content card */
.stApp { background-color: #0f1724; color: #e6eef8; }
.header { display:flex; align-items:center; gap:16px; }
.brand { font-size:28px; font-weight:700; color:#fff; }
.subtitle { color:#9fb4d6; margin-top:4px }
.card { background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02)); padding:18px; border-radius:8px; box-shadow: 0 6px 18px rgba(2,6,23,0.6); }
.metric-card { padding:12px; border-radius:8px; background: rgba(255,255,255,0.02); }
.small { font-size:13px; color:#b9cfe6 }
.download-btn { background:#0ea5a3; color:white; }
</style>
""", unsafe_allow_html=True)

col_h1, col_h2 = st.columns([3,1])
with col_h1:
    st.markdown("<div class='header'><div class='brand'>🏬 Mall Occupancy AI Dashboard</div></div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>Scrape mall directories, clean data, compare with old data, and generate AI insights.</div>", unsafe_allow_html=True)
with col_h2:
    st.markdown("<div style='text-align:right'><span class='small'>Status: <strong style='color:#7ee787'>Ready</strong></span></div>", unsafe_allow_html=True)

st.markdown("---")

# Short intro and help in a card
with st.container():
    st.markdown('''<div class='card'><strong>Quick Guide:</strong> Upload your OLD cleaned CSV, enter a mall website URL or Facebook page URL (or upload a CSV/XLSX with both website and Facebook URLs), then click "Scrape & Use as NEW". Results are kept in memory and available for download.</div>''', unsafe_allow_html=True)
    st.write("")

# Optional custom mall URL for scraping (supports website, Facebook, and Instagram URLs)
input_url = st.text_area("Mall Website URL(s), Facebook Page URL(s), or Instagram Profile URL(s)", value="", help="Enter one or more URLs separated by commas or new lines. Supports website URLs, Facebook page URLs, and Instagram profile URLs (e.g., https://example.com, https://www.facebook.com/Vishaal.Mall/, https://www.instagram.com/lulu_mall/)", height=100)

# -------------------------------------------------
# File Uploads
# -------------------------------------------------
col1, col2, col3 = st.columns(3)

with col1:
    old_file = st.file_uploader("Upload OLD Mall CSV (cleaned)", type=["csv"])

with col2:
    new_file = st.file_uploader("Upload NEW/Scraped Data CSV (optional - to skip scraping)", type=["csv"], help="Upload previously scraped data CSV to use for comparison without scraping again")

with col3:
    links_file = st.file_uploader("Upload CSV/XLSX with mall URLs (supports website, Facebook, and Instagram URLs)", type=["csv", "xlsx"], help="CSV format: 'website' column for website URLs, 'facebook' column for Facebook page URLs, 'instagram' column for Instagram URLs, or mixed columns with all types") 

# -------------------------------------------------
# Process when both files exist
# -------------------------------------------------
if 'structured_data' not in st.session_state:
    st.session_state.structured_data = None

# Initialize session state for scraped data
if 'scraped_preview_df' not in st.session_state:
    st.session_state.scraped_preview_df = None

# Initialize session state for LLM results
if 'llm_json' not in st.session_state:
    st.session_state.llm_json = None

# Initialize session state for URLs
if 'scraped_urls' not in st.session_state:
    st.session_state.scraped_urls = ""

# Display old file preview if uploaded
old_df = None
if old_file:
    # Read uploaded old file into memory (do not save to disk)
    try:
        old_df = pd.read_csv(old_file)
    except Exception:
        old_df = pd.read_excel(old_file)
    with st.expander("📄 OLD CSV Preview"):
        st.dataframe(old_df.head())

# Handle NEW file upload (scraped data file)
if new_file:
    try:
        # Read uploaded new file into memory
        uploaded_new_df = pd.read_csv(new_file)
        
        # Ensure source column exists if not present
        if 'source' not in uploaded_new_df.columns:
            uploaded_new_df['source'] = 'Uploaded Data'
        
        # Store in session state as scraped data
        st.session_state.scraped_preview_df = uploaded_new_df
        st.session_state.new_cleaned_df = uploaded_new_df
        
        with st.expander("📄 Uploaded NEW Data Preview"):
            st.dataframe(uploaded_new_df.head())
            st.info(f"✅ Loaded {len(uploaded_new_df)} records from uploaded file")
        
        # If old file exists, automatically compare
        if old_df is not None and not old_df.empty:
            try:
                # IMPORTANT: Filter to only Website Data for tenant comparison
                website_df = uploaded_new_df[uploaded_new_df['source'].str.contains('Website', case=False, na=False)].copy() if 'source' in uploaded_new_df.columns else uploaded_new_df.copy()
                
                if website_df.empty:
                    st.warning("⚠️ No website data found for tenant comparison. Only website scraping data is used for tenant analysis.")
                    structured_data = None
                else:
                    structured_data = compare_shops(old_df, website_df, preserve_source=True, website_only=True)
                    if structured_data:
                        structured_data['tenant_analysis_source'] = 'Website Data Only'
                        structured_data['stats']['tenant_analysis_note'] = 'Comparison based on Website Data only (Facebook/Instagram excluded from tenant analysis)'
                
                st.session_state.structured_data = structured_data
                st.success("✅ Comparison completed automatically! Results shown below.")
            except Exception as e:
                st.warning(f"Auto-comparison failed: {e}")
    except Exception as e:
        st.error(f"Failed to read uploaded NEW data file: {e}")
        import traceback
        st.code(traceback.format_exc())

# --- Check if we can compare existing scraped data with newly uploaded old file ---
compare_analyze_btn = None
if st.session_state.scraped_preview_df is not None and old_df is not None and not old_df.empty and st.session_state.structured_data is None:
    st.info("✅ You have scraped data and an old file. Click 'Compare & Analyze' to compare them.")
    compare_analyze_btn = st.button("🔍 Compare & Analyze", help="Compare existing scraped data with uploaded old file", type="primary")

# Handle comparison when button is clicked
if compare_analyze_btn:
    with st.spinner("Comparing scraped data with old file..."):
        try:
            new_df = st.session_state.scraped_preview_df
            if new_df is not None and not new_df.empty:
                # IMPORTANT: Filter to only Website Data for tenant comparison
                website_df = new_df[new_df['source'].str.contains('Website', case=False, na=False)].copy() if 'source' in new_df.columns else new_df.copy()
                
                if website_df.empty:
                    st.warning("⚠️ No website data found for tenant comparison. Only website scraping data is used for tenant analysis.")
                    structured_data = None
                else:
                    structured_data = compare_shops(old_df, website_df, preserve_source=True, website_only=True)
                    if structured_data:
                        structured_data['tenant_analysis_source'] = 'Website Data Only'
                        structured_data['stats']['tenant_analysis_note'] = 'Comparison based on Website Data only (Facebook/Instagram excluded from tenant analysis)'
                
                st.session_state.structured_data = structured_data
                st.session_state.new_cleaned_df = new_df
                st.success("✅ Comparison completed! Results shown below.")
            else:
                st.error("No scraped data available for comparison.")
        except Exception as e:
            st.error(f"Comparison failed: {e}")
            import traceback
            st.code(traceback.format_exc())

# --- Buttons: Scrape single URL OR scrape multiple URLs from uploaded links file ---
col_scrape, col_links = st.columns([1, 1])

with col_scrape:
    scrape_use_btn = st.button("🔎 Scrape & Use as NEW", help="Start scraping the provided URL and use results as NEW data")

with col_links:
    scrape_links_btn = st.button("🗂️ Scrape links file & Analyze", help="Scrape every URL in the uploaded links file (supports both website and Facebook URLs)")

# Single or multiple URL scrape (supports both website and Facebook URLs)
if scrape_use_btn:
    with st.spinner("Scraping site(s) and preparing NEW data (this may take several minutes)..."):
        try:
            if not input_url:
                st.error("Please provide at least one mall site URL or Facebook page URL in the input box before scraping.")
                new_df = None
            else:
                # Parse multiple URLs (comma or newline separated)
                import re
                url_pattern = re.compile(r"https?://[^\s,\n]+")
                urls = url_pattern.findall(input_url)
                
                if not urls:
                    st.error("No valid URLs found. Please enter URLs starting with http:// or https://")
                    new_df = None
                else:
                    # Separate website, Facebook, and Instagram URLs
                    website_urls = []
                    facebook_urls = []
                    instagram_urls = []
                    
                    for url in urls:
                        url = url.strip().rstrip(',')
                        if 'facebook.com' in url.lower() or 'fb.com' in url.lower():
                            facebook_urls.append(url)
                        elif 'instagram.com' in url.lower() or 'instagr.am' in url.lower():
                            instagram_urls.append(url)
                        else:
                            website_urls.append(url)
                    
                    st.info(f"Found {len(website_urls)} website URL(s), {len(facebook_urls)} Facebook URL(s), and {len(instagram_urls)} Instagram URL(s)")
                    
                    combined_data = []
                    
                    # Scrape website URLs
                    extracted_text_files = []  # Store paths to extracted text files
                    if website_urls:
                        for i, url in enumerate(website_urls, 1):
                            st.write(f"🌐 Scraping website ({i}/{len(website_urls)}): {url}")
                            try:
                                df_web = scrape_and_prepare(url=url, source="Website Data")
                                if df_web is not None and not df_web.empty:
                                    combined_data.append(df_web)
                                    st.success(f"✅ Scraped {len(df_web)} items from website")
                                
                                # Check if extracted text file was created
                                import os
                                if os.path.exists("last_extracted_text_path.txt"):
                                    with open("last_extracted_text_path.txt", "r", encoding="utf-8") as f:
                                        text_file_path = f.read().strip()
                                        if text_file_path and os.path.exists(text_file_path):
                                            extracted_text_files.append((url, text_file_path))
                                            # Clean up the temp file
                                            try:
                                                os.remove("last_extracted_text_path.txt")
                                            except:
                                                pass
                            except Exception as e:
                                st.warning(f"❌ Failed scraping website {url}: {e}")
                    
                    # Scrape Facebook URLs (up to 20 posts per page)
                    if facebook_urls:
                        for i, url in enumerate(facebook_urls, 1):
                            st.write(f"📘 Scraping Facebook ({i}/{len(facebook_urls)}): {url}")
                            try:
                                # Scrape up to 20 posts per Facebook page
                                df_fb = scrape_facebook_simple(fb_url=url, target_count=20)
                                if df_fb is not None and not df_fb.empty:
                                    combined_data.append(df_fb)
                                    st.success(f"✅ Scraped {len(df_fb)} items from Facebook page")
                            except Exception as e:
                                error_msg = str(e)
                                if "Chrome failed to start" in error_msg or "DevToolsActivePort" in error_msg:
                                    st.error(f"❌ Chrome browser error when scraping Facebook {url}")
                                    st.info("💡 **Troubleshooting tips:**\n"
                                           "- Close all Chrome browser windows\n"
                                           "- Update Google Chrome to the latest version\n"
                                           "- Restart your computer if the issue persists\n"
                                           "- Check if Chrome is installed correctly")
                                else:
                                    st.warning(f"❌ Failed scraping Facebook {url}: {error_msg}")
                    
                    # Scrape Instagram URLs (up to 20 posts per profile)
                    if instagram_urls:
                        # Add small delay to ensure previous Chrome instances are fully closed
                        import time
                        time.sleep(0.5)  # Reduced for faster startup
                        for i, url in enumerate(instagram_urls, 1):
                            st.write(f"📷 Scraping Instagram ({i}/{len(instagram_urls)}): {url}")
                            try:
                                # Scrape up to 20 posts per Instagram profile
                                df_ig = scrape_instagram_simple(ig_url=url, target_count=20)
                                if df_ig is not None and not df_ig.empty:
                                    combined_data.append(df_ig)
                                    st.success(f"✅ Scraped {len(df_ig)} items from Instagram profile (up to 20 posts)")
                            except Exception as e:
                                error_msg = str(e)
                                if "Chrome failed to start" in error_msg or "DevToolsActivePort" in error_msg:
                                    st.error(f"❌ Chrome browser error when scraping Instagram {url}")
                                    st.info("💡 **Troubleshooting tips:**\n"
                                           "- Close all Chrome browser windows\n"
                                           "- Update Google Chrome to the latest version\n"
                                           "- Restart your computer if the issue persists\n"
                                           "- Check if Chrome is installed correctly")
                                else:
                                    st.warning(f"❌ Failed scraping Instagram {url}: {error_msg}")
                    
                    # Combine all scraped data
                    if combined_data:
                        new_df = pd.concat(combined_data, ignore_index=True)
                        st.success(f"✅ Successfully combined data from {len(combined_data)} source(s). Total items: {len(new_df)}")
                        # Store URLs in session state for metadata
                        all_urls = website_urls + facebook_urls + instagram_urls
                        st.session_state.scraped_urls = ", ".join(all_urls)
                        
                        # Store extracted text files in session state
                        if extracted_text_files:
                            st.session_state.extracted_text_files = extracted_text_files
                    else:
                        st.error("Failed to scrape data from any provided URLs.")
                        new_df = None
                        # Still store extracted text files even if no shops were found
                        if extracted_text_files:
                            st.session_state.extracted_text_files = extracted_text_files
            
            if new_df is not None and not new_df.empty:
                # Ensure source column exists (for backward compatibility)
                if 'source' not in new_df.columns:
                    new_df['source'] = 'Unknown'
                
                # Store scraped data for preview
                st.session_state.scraped_preview_df = new_df
                
                # If old file exists, compare; otherwise just show preview
                if old_df is not None and not old_df.empty:
                    # IMPORTANT: Filter to only Website Data for tenant comparison
                    # Facebook and Instagram are post data, not tenant data
                    website_df = new_df[new_df['source'].str.contains('Website', case=False, na=False)].copy() if 'source' in new_df.columns else new_df.copy()
                    
                    if website_df.empty:
                        st.warning("⚠️ No website data found for tenant comparison. Only website scraping data is used for tenant analysis.")
                        structured_data = None
                    else:
                        # Use only website data for tenant comparison
                        # Keep source column to preserve source information
                        structured_data = compare_shops(old_df, website_df, preserve_source=True, website_only=True)
                        
                        # Add website-only flag to structured_data
                        if structured_data:
                            structured_data['tenant_analysis_source'] = 'Website Data Only'
                            # Update overall stats to reflect website-only comparison
                            structured_data['stats']['tenant_analysis_note'] = 'Comparison based on Website Data only (Facebook/Instagram excluded from tenant analysis)'
                        
                        st.session_state.structured_data = structured_data
                    
                    # Also merge new shops into existing tenant list (only website data)
                    try:
                        if not website_df.empty:
                            merged_tenant_list = merge_shops_to_tenant_list(old_df, website_df)
                            st.session_state.merged_tenant_list = merged_tenant_list
                            new_shops_count = len(merged_tenant_list) - len(old_df)
                            if new_shops_count > 0:
                                st.info(f"📋 **Merged Tenant List (Website Data Only):** {len(old_df)} existing + {new_shops_count} new = {len(merged_tenant_list)} total shops")
                        else:
                            st.session_state.merged_tenant_list = None
                    except Exception as e:
                        st.warning(f"Could not merge shops into tenant list: {e}")
                        st.session_state.merged_tenant_list = None
                else:
                    st.session_state.structured_data = None
                    st.session_state.merged_tenant_list = None
                    st.success("✅ Data scraped successfully! Preview below.")
            else:
                st.session_state.scraped_preview_df = None
                st.session_state.structured_data = None
                st.session_state.merged_tenant_list = None
            
            # persist cleaned DataFrame for download
            st.session_state.new_cleaned_df = new_df
        except Exception as e:
            st.error(f"Scrape-and-use failed: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.session_state.structured_data = None
            st.session_state.scraped_preview_df = None

# Links file: read URLs and scrape each, then combine (works with or without old file)
if links_file and scrape_links_btn:
    with st.spinner("Reading links file and scraping each site (this may take several minutes)..."):
            try:
                # robust URL extraction: prefer common URL column names, otherwise scan all cells
                import re
                import io

                url_pattern = re.compile(r"https?://[^\s,;\)\]\'}\"]+")

                # Separate website, Facebook, and Instagram URLs
                website_urls = []
                facebook_urls = []
                instagram_urls = []
                
                # FIRST: Read raw file content to extract URLs (works for any format)
                # This ensures we catch URLs even from non-standard CSV formats
                raw_content = None
                try:
                    # Reset file pointer to beginning
                    links_file.seek(0)
                    try:
                        raw_content = links_file.read().decode("utf-8")
                    except Exception:
                        try:
                            raw_content = links_file.getvalue().decode("utf-8")
                        except Exception:
                            pass
                    
                    # Extract URLs from raw content
                    if raw_content:
                        found = url_pattern.findall(raw_content)
                        for u in found:
                            u = u.strip().strip('\"\'')
                            # Categorize by URL domain
                            if 'facebook.com' in u.lower() or 'fb.com' in u.lower():
                                if u not in facebook_urls:
                                    facebook_urls.append(u)
                            elif 'instagram.com' in u.lower() or 'instagr.am' in u.lower():
                                if u not in instagram_urls:
                                    instagram_urls.append(u)
                            else:
                                if u not in website_urls:
                                    website_urls.append(u)
                except Exception:
                    pass

                # SECOND: Also try parsing as CSV/XLSX for structured data (may catch additional URLs)
                try:
                    # Reset file pointer again before pandas read
                    links_file.seek(0)
                    try:
                        df_links = pd.read_csv(links_file)
                    except Exception:
                        links_file.seek(0)
                        df_links = pd.read_excel(links_file)
                    
                    # Scan ALL columns and categorize URLs by their actual domain (not column name)
                    # This ensures URLs are detected even if they're in a different column
                    for col in df_links.columns:
                        for val in df_links[col].dropna().astype(str):
                            found = url_pattern.findall(val)
                            for u in found:
                                u = u.strip().strip('\"\'')
                                # Categorize by URL domain, not column name
                                if 'facebook.com' in u.lower() or 'fb.com' in u.lower():
                                    if u not in facebook_urls:
                                        facebook_urls.append(u)
                                elif 'instagram.com' in u.lower() or 'instagr.am' in u.lower():
                                    if u not in instagram_urls:
                                        instagram_urls.append(u)
                                else:
                                    if u not in website_urls:
                                        website_urls.append(u)
                except Exception:
                    # If CSV/XLSX parsing fails, that's okay - we already have raw content URLs
                    pass

                # Clean and validate URLs
                def clean_urls(url_list):
                    cleaned = []
                    for u in url_list:
                        if not u or u.lower() in ('nan', 'none', ''):
                            continue
                        u = u.strip().strip('\"\'')
                        if u and (u.startswith("http://") or u.startswith("https://")):
                            cleaned.append(u)
                    return list(dict.fromkeys(cleaned))  # dedupe

                website_urls = clean_urls(website_urls)
                facebook_urls = clean_urls(facebook_urls)
                instagram_urls = clean_urls(instagram_urls)

                total_urls = len(website_urls) + len(facebook_urls) + len(instagram_urls)
                if total_urls == 0:
                    st.error("No URLs found in uploaded file. Please ensure the file contains website URLs, Facebook URLs, and/or Instagram URLs.")
                else:
                    # Show detected URLs for debugging
                    if website_urls:
                        st.write(f"📋 Detected {len(website_urls)} website URL(s): {', '.join(website_urls[:3])}{'...' if len(website_urls) > 3 else ''}")
                    if facebook_urls:
                        st.write(f"📋 Detected {len(facebook_urls)} Facebook URL(s): {', '.join(facebook_urls[:3])}{'...' if len(facebook_urls) > 3 else ''}")
                    if instagram_urls:
                        st.write(f"📋 Detected {len(instagram_urls)} Instagram URL(s): {', '.join(instagram_urls[:3])}{'...' if len(instagram_urls) > 3 else ''}")
                    if not website_urls and not facebook_urls and not instagram_urls:
                        st.warning("⚠️ URLs were found but none passed validation. Please check the URLs in your file.")
                    combined = []
                    
                    # Scrape website URLs
                    if website_urls:
                        st.info(f"Found {len(website_urls)} website URL(s) to scrape")
                        for i, u in enumerate(website_urls, 1):
                            st.write(f"🌐 Scraping website ({i}/{len(website_urls)}): {u}")
                            try:
                                dfc = scrape_and_prepare(url=u, source="Website Data")
                                if dfc is not None and not dfc.empty:
                                    combined.append(dfc)
                                    st.success(f"✅ Scraped {len(dfc)} items from website")
                            except Exception as e:
                                st.warning(f"❌ Failed scraping website {u}: {e}")

                    # Scrape Facebook URLs
                    if facebook_urls:
                        st.info(f"Found {len(facebook_urls)} Facebook page(s) to scrape")
                        for i, u in enumerate(facebook_urls, 1):
                            st.write(f"📘 Scraping Facebook ({i}/{len(facebook_urls)}): {u}")
                            try:
                                dfc = scrape_facebook_simple(fb_url=u, target_count=30)
                                if dfc is not None and not dfc.empty:
                                    combined.append(dfc)
                                    st.success(f"✅ Scraped {len(dfc)} items from Facebook")
                                else:
                                    st.warning(f"⚠️ No data extracted from Facebook page {u}")
                            except Exception as e:
                                error_msg = str(e)
                                if "Chrome failed to start" in error_msg or "DevToolsActivePort" in error_msg:
                                    st.error(f"❌ Chrome browser error when scraping Facebook {u}")
                                    st.info("💡 **Troubleshooting tips:**\n"
                                           "- Close all Chrome browser windows\n"
                                           "- Update Google Chrome to the latest version\n"
                                           "- Restart your computer if the issue persists\n"
                                           "- Check if Chrome is installed correctly")
                                else:
                                    st.warning(f"❌ Failed scraping Facebook {u}: {error_msg}")

                    # Scrape Instagram URLs (up to 20 posts per profile)
                    if instagram_urls:
                        # Add small delay to ensure previous Chrome instances are fully closed
                        import time
                        time.sleep(0.5)  # Reduced for faster startup
                        st.info(f"Found {len(instagram_urls)} Instagram profile(s) to scrape (up to 20 posts each)")
                        for i, u in enumerate(instagram_urls, 1):
                            st.write(f"📷 Scraping Instagram ({i}/{len(instagram_urls)}): {u}")
                            try:
                                # Scrape up to 20 posts per Instagram profile
                                dfc = scrape_instagram_simple(ig_url=u, target_count=20)
                                if dfc is not None and not dfc.empty:
                                    combined.append(dfc)
                                    st.success(f"✅ Scraped {len(dfc)} items from Instagram (up to 20 posts)")
                                else:
                                    st.warning(f"⚠️ No data extracted from Instagram profile {u}")
                            except Exception as e:
                                error_msg = str(e)
                                if "Chrome failed to start" in error_msg or "DevToolsActivePort" in error_msg:
                                    st.error(f"❌ Chrome browser error when scraping Instagram {u}")
                                    st.info("💡 **Troubleshooting tips:**\n"
                                           "- Close all Chrome browser windows\n"
                                           "- Update Google Chrome to the latest version\n"
                                           "- Restart your computer if the issue persists\n"
                                           "- Check if Chrome is installed correctly")
                                else:
                                    st.warning(f"❌ Failed scraping Instagram {u}: {error_msg}")

                    # Combine all scraped data
                    if combined:
                        new_df = pd.concat(combined, ignore_index=True)
                        
                        # Store URLs in session state for metadata
                        all_urls = website_urls + facebook_urls + instagram_urls
                        st.session_state.scraped_urls = ", ".join(all_urls)
                        
                        # Ensure source column exists
                        if 'source' not in new_df.columns:
                            new_df['source'] = 'Unknown'
                        
                        st.session_state.scraped_preview_df = new_df
                        if old_df is not None and not old_df.empty:
                            # IMPORTANT: Filter to only Website Data for tenant comparison
                            website_df = new_df[new_df['source'].str.contains('Website', case=False, na=False)].copy() if 'source' in new_df.columns else new_df.copy()
                            
                            if website_df.empty:
                                st.warning("⚠️ No website data found for tenant comparison. Only website scraping data is used for tenant analysis.")
                                structured_data = None
                            else:
                                structured_data = compare_shops(old_df, website_df, preserve_source=True, website_only=True)
                                if structured_data:
                                    structured_data['tenant_analysis_source'] = 'Website Data Only'
                                    structured_data['stats']['tenant_analysis_note'] = 'Comparison based on Website Data only (Facebook/Instagram excluded from tenant analysis)'
                            
                            st.session_state.structured_data = structured_data
                        else:
                            st.session_state.structured_data = None
                        st.session_state.new_cleaned_df = new_df
                        st.success(f"✅ Successfully scraped and combined data from {len(combined)} source(s). Total items: {len(new_df)}")
                    else:
                        st.error("No data scraped from provided URLs.")
                        st.session_state.scraped_preview_df = None
            except Exception as e:
                st.error(f"Failed processing links file: {e}")
                import traceback
                st.code(traceback.format_exc())

# Show preview of scraped data if available (even without old file)
if st.session_state.scraped_preview_df is not None:
    with st.expander("📊 Scraped Data Preview", expanded=False):
        preview_df = st.session_state.scraped_preview_df
        
        # Show summary by source
        if 'source' in preview_df.columns:
            source_counts = preview_df['source'].value_counts()
            st.info(f"**Total items scraped: {len(preview_df)}**")
            for source, count in source_counts.items():
                st.write(f"  - {source}: {count} items")
        
        # Show data grouped by source with clear headings
        if 'source' in preview_df.columns:
            sources = preview_df['source'].unique()
            for source in sources:
                source_data = preview_df[preview_df['source'] == source]
                st.subheader(f"📋 {source} ({len(source_data)} items)")
                st.dataframe(source_data.head(20))
                if len(source_data) > 20:
                    st.caption(f"Showing first 20 of {len(source_data)} items")
        else:
            st.dataframe(preview_df.head(20))
            st.info(f"Total shops scraped: {len(preview_df)}")
        
        # Download button for scraped data (even without old file)
        try:
            csv_bytes = preview_df.to_csv(index=False).encode("utf-8")
            if input_url:
                try:
                    domain = urlparse(input_url).netloc.replace("www.", "").split(".")[0]
                    if domain:
                        filename = f"{domain}_combined_scraped_data.csv"
                    else:
                        filename = "mall_combined_scraped_data.csv"
                except Exception:
                    filename = "mall_combined_scraped_data.csv"
            else:
                filename = "mall_combined_scraped_data.csv"
            st.download_button("⬇️ Download Combined Scraped CSV (Website + Facebook + Instagram)", data=csv_bytes, file_name=filename, key="download_scraped")
        except Exception as e:
            st.error(f"Failed to prepare scraped CSV for download: {e}")

# Show extracted text files for download
if 'extracted_text_files' in st.session_state and st.session_state.extracted_text_files:
    with st.expander("📄 Download Extracted Text Files", expanded=True):
        st.info("These are the clean text files extracted from the website HTML (used for LLM extraction).")
        for url, filepath in st.session_state.extracted_text_files:
            try:
                import os
                if os.path.exists(filepath):
                    with open(filepath, "r", encoding="utf-8") as f:
                        file_content = f.read()
                    
                    # Get filename from path
                    filename = os.path.basename(filepath)
                    
                    st.write(f"**From:** {url}")
                    st.download_button(
                        label=f"⬇️ Download: {filename}",
                        data=file_content.encode("utf-8"),
                        file_name=filename,
                        mime="text/plain",
                        key=f"download_text_{hash(filepath)}"
                    )
                    st.caption(f"File size: {len(file_content)} characters")
                else:
                    st.warning(f"File not found: {filepath}")
            except Exception as e:
                st.error(f"Error reading file {filepath}: {e}")

# Show merged tenant list if available
if 'merged_tenant_list' in st.session_state and st.session_state.merged_tenant_list is not None:
    merged_list = st.session_state.merged_tenant_list
    with st.expander("📋 Updated Tenant List (Existing + New Shops)", expanded=True):
        st.info(f"**Total shops in merged list:** {len(merged_list)}")
        st.dataframe(merged_list)
        
        # Download button for merged tenant list
        try:
            csv_bytes = merged_list.to_csv(index=False).encode("utf-8")
            filename = "updated_tenant_list.csv"
            st.download_button(
                "⬇️ Download Updated Tenant List (CSV)",
                data=csv_bytes,
                file_name=filename,
                mime="text/csv",
                key="download_merged_tenant_list"
            )
            st.success("✅ This file contains all existing tenants plus newly extracted shops (no duplicates)")
        except Exception as e:
            st.error(f"Failed to prepare merged tenant list for download: {e}")

# Show merged tenant list if available
if 'merged_tenant_list' in st.session_state and st.session_state.merged_tenant_list is not None:
    merged_list = st.session_state.merged_tenant_list
    with st.expander("📋 Updated Tenant List (Existing + New Shops)", expanded=True):
        st.info(f"**Total shops in merged list:** {len(merged_list)}")
        st.dataframe(merged_list)
        
        # Download button for merged tenant list
        try:
            csv_bytes = merged_list.to_csv(index=False).encode("utf-8")
            filename = "updated_tenant_list.csv"
            st.download_button(
                "⬇️ Download Updated Tenant List (CSV)",
                data=csv_bytes,
                file_name=filename,
                mime="text/csv",
                key="download_merged_tenant_list"
            )
            st.success("✅ This file contains all existing tenants plus newly extracted shops (no duplicates)")
        except Exception as e:
            st.error(f"Failed to prepare merged tenant list for download: {e}")

# Prefer persisted structured_data from session_state if available
if st.session_state.structured_data:
    structured_data = st.session_state.structured_data
else:
    structured_data = None

if structured_data:
        # ---------------- Download cleaned NEW data (in-memory) ----------------
        new_df = st.session_state.get("new_cleaned_df")
        if new_df is not None:
            try:
                csv_bytes = new_df.to_csv(index=False).encode("utf-8")
                # Generate filename from URL if available, otherwise use generic name
                if input_url:
                    try:
                        domain = urlparse(input_url).netloc.replace("www.", "").split(".")[0]
                        if domain:
                            filename = f"{domain}_shops_newdata_clean.csv"
                        else:
                            filename = "mall_shops_newdata_clean.csv"
                    except Exception:
                        filename = "mall_shops_newdata_clean.csv"
                else:
                    filename = "mall_shops_newdata_clean.csv"
                st.download_button("⬇️ Download cleaned NEW CSV", data=csv_bytes, file_name=filename)
            except Exception as e:
                st.error(f"Failed to prepare cleaned CSV for download: {e}")

        st.divider()

        # Generate AI Report button
        if st.button("🤖 Generate AI Report"):
            with st.spinner("Generating AI report..."):
                input_url_to_use = input_url if input_url else st.session_state.get('scraped_urls', '')
                llm_output = run_llm_analysis(structured_data, input_url=input_url_to_use)

            try:
                llm_json = json.loads(llm_output)
                st.session_state.llm_json = llm_json  # Store in session state
                st.session_state.llm_input_url = input_url_to_use  # Store input URL for download
            except json.JSONDecodeError:
                st.error("❌ AI returned invalid JSON")
                st.text(llm_output)
                st.stop()

            if "error" in llm_json:
                st.error(llm_json["error"])
                st.stop()

        # Display AI Report from session state (so it persists after download)
        llm_json = st.session_state.get('llm_json')
        if llm_json:
            input_url_to_use = st.session_state.get('llm_input_url', input_url if input_url else st.session_state.get('scraped_urls', ''))
            
            # Check if we have separate reports (Website, Overall)
            # Show only Overall Report (based on website data for tenant analysis)
            if "overall" in llm_json:
                overall_report = llm_json["overall"]
                
                st.header("📊 Overall Report")
                st.info("This report is based on website scraping data for tenant analysis.")
                    
                st.subheader("Occupancy Trend")
                occupancy = overall_report.get("occupancy_trend", "")
                if occupancy and occupancy != "N/A - Data not analyzed":
                    st.write(occupancy)
                else:
                    st.write("N/A - Data not analyzed")
                    
                    st.subheader("New Shops Summary")
                new_shops = overall_report.get("new_shops", "")
                if new_shops and new_shops != "N/A - Data not analyzed":
                    st.write(new_shops)
                else:
                    st.write("N/A - Data not analyzed")
                    
                    st.subheader("Vacancy / Closure Analysis")
                vacancy = overall_report.get("vacancy_changes", "")
                if vacancy and vacancy != "N/A - Data not analyzed":
                    st.write(vacancy)
                else:
                    st.write("N/A - Data not analyzed")
                    
                    st.subheader("Business Insights")
                    overall_insights = overall_report.get("business_insights", [])
                    if not overall_insights:
                        st.write("• No additional business insights generated.")
                    else:
                        for insight in overall_insights:
                            st.write("•", insight)
            else:
                # Fallback - try to extract from any available structure
                report_data = llm_json.get("overall", llm_json) if "overall" in llm_json else llm_json
                
                st.header("📊 Overall Report")
                st.info("This report is based on website scraping data for tenant analysis.")
                
                st.subheader("Occupancy Trend")
                st.write(report_data.get("occupancy_trend", "N/A - Data not analyzed"))
                
                st.subheader("New Shops Summary")
                st.write(report_data.get("new_shops", "N/A - Data not analyzed"))
                
                st.subheader("Vacancy / Closure Analysis")
                st.write(report_data.get("vacancy_changes", "N/A - Data not analyzed"))
                
                st.subheader("Business Insights")
                business_insights = report_data.get("business_insights", [])
                if not business_insights:
                    st.write("• No additional business insights generated.")
                else:
                    for insight in business_insights:
                        st.write("•", insight)
            
            # ---------------- Export to Excel (comprehensive 4-tab format) ---------------- 
            # Download button outside the if/else blocks so it's always visible and doesn't close the report
            try:
                buffer = create_mall_excel_export(
                    scraped_df=st.session_state.get("new_cleaned_df"),
                    structured_data=structured_data,
                    llm_json=llm_json,
                    input_url=input_url_to_use
                )
                # Read buffer as bytes to avoid Streamlit media storage issues
                excel_bytes = buffer.getvalue()
                st.download_button(
                    "⬇️ Download Comprehensive Excel Report (4 Tabs)", 
                    data=excel_bytes, 
                    file_name="mall_research_output.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                    key="download_excel_report",
                    on_click="ignore"  # Prevent rerun so report stays visible
                )
            except Exception as e:
                st.error(f"Failed to export Excel: {e}")
                import traceback
                st.code(traceback.format_exc())