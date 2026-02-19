import streamlit as st
import json
import requests
from PIL import Image, ImageOps, ImageEnhance
import numpy as np
import os
from pathlib import Path
# import easyocr
# from sentence_transformers import SentenceTransformer, util
import pandas as pd
import cv2
import glob
import asyncio
import sys
import time
from rapidfuzz import process, fuzz

# Windows asyncio fix for Streamlit/Playwright compatibility
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from collections import Counter
from scrape_pipeline import scrape_mall_data 
import gc

# Configuration
JSON_DATA_PATH = os.path.join(os.path.expanduser("~"), "Downloads", "tenants_detailed.json")
# Use current user's Downloads so it works on any machine (no hardcoded usernames)
IMAGES_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "mall_analysis_reports")

if not os.path.exists(IMAGES_DIR):
    os.makedirs(IMAGES_DIR, exist_ok=True)


def _load_shared_map_url() -> str:
    """If main dashboard submitted data, pre-fill the Mall Map URL."""
    shared = Path(__file__).resolve().parent.parent / "shared_dashboard_input.json"
    if not shared.exists():
        return ""
    try:
        with open(shared, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("map_visual_url") or "").strip()
    except Exception:
        return ""


# @st.cache_resource
# def load_models():
#     # Load OCR and Improved SBERT models
#     # ENABLE QUANTIZATION to fix memory error
#     reader = easyocr.Reader(['en'], gpu=False, verbose=False, quantize=True)
#     # Using 'all-MiniLM-L6-v2' for efficiency and accuracy in semantic matching
#     model = SentenceTransformer('all-MiniLM-L6-v2') 
#     return reader, model

def load_json_data():
    if not os.path.exists(JSON_DATA_PATH):
        return None
    try:
        with open(JSON_DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading JSON: {e}")
        return None

def preprocess_image(image_path):
    """
    Enhances image for better OCR accuracy while maintaining enough resolution.
    """
    img = Image.open(image_path).convert("RGB")
    
    # Advanced Enhancement Pipeline
    img_gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    
    # 1. CLAHE (Contrast Limited Adaptive Histogram Equalization) for text visibility on backgrounds
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    img_gray = clahe.apply(img_gray)
    
    # 2. Localized Sharpening
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    img_sharpened = cv2.filter2D(img_gray, -1, kernel)
    
    # Convert back to RGB for PIL processing if needed, but OCR likes gray too
    img = Image.fromarray(cv2.cvtColor(img_sharpened, cv2.COLOR_GRAY2RGB))
    
    # Increase resolution (3000px for extreme detail)
    max_dim = 3000
    w, h = img.size
    if w > max_dim or h > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    
    return img

def solve_latlon_to_pixel(valid_pts):
    """
    Gold-standard coordinate projection with normalization and iterative refinement.
    """
    if len(valid_pts) < 3:
        return None, None, None
        
    src_pts = np.array([[p['lon'], p['lat']] for p in valid_pts], dtype=np.float64)
    dst_pts = np.array([[p['x'], p['y']] for p in valid_pts], dtype=np.float64)

    # 1. Normalization (Matrix Scaling/Translation for Numeric Stability)
    src_mean = np.mean(src_pts, axis=0)
    dst_mean = np.mean(dst_pts, axis=0)
    src_std = np.std(src_pts, axis=0) + 1e-9
    dst_std = np.std(dst_pts, axis=0) + 1e-9
    
    src_norm = (src_pts - src_mean) / src_std
    dst_norm = (dst_pts - dst_mean) / dst_std

    # 2. Iterative RANSAC Solver
    if len(valid_pts) >= 4:
        # Homography with tight reprojection threshold (1.0px)
        H_norm, mask = cv2.findHomography(src_norm, dst_norm, cv2.RANSAC, 1.0)
        if H_norm is None: return None, None, None
        
        # Denormalize H
        T_src = np.array([[1/src_std[0], 0, -src_mean[0]/src_std[0]], [0, 1/src_std[1], -src_mean[1]/src_std[1]], [0, 0, 1]])
        T_dst_inv = np.array([[dst_std[0], 0, dst_mean[0]], [0, dst_std[1], dst_mean[1]], [0, 0, 1]])
        H = T_dst_inv @ H_norm @ T_src
        return H, "homography", mask
    else:
        # Affine with LMEDS for small point sets
        M, mask = cv2.estimateAffine2D(src_pts, dst_pts, method=cv2.LMEDS)
        return M, "affine", mask

def clean_hours_helper(val):
    if isinstance(val, list):
        summary = []
        for entry in val:
            if isinstance(entry, dict):
                days = entry.get('dayOfWeek', [])
                opens = entry.get('opens', '')
                closes = entry.get('closes', '')
                if days:
                    day_str = ", ".join(days)
                    summary.append(f"{day_str}: {opens} - {closes}")
        return "; ".join(summary) if summary else "Not available"
    return str(val) if val else "Not available"

def main():
    st.set_page_config(layout="wide", page_title="Mall Tenant Intelligence", page_icon="🗺️")
    
    # Custom CSS for better aesthetics and scrolling
    st.markdown("""
        <style>
        .main {
            background-color: #f8f9fa;
        }
        .stDataFrame {
            border: 1px solid #e9ecef;
            border-radius: 10px;
        }
        .stMetric {
            background-color: white;
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        </style>
    """, unsafe_allow_html=True)

    st.title("🏙️ Mall Tenant Analysis & Vision Pipeline")
    
    # reader, sbert_model = load_models()
    reader, sbert_model = None, None

    # --- Data Management ---
    if 'tenants' not in st.session_state:
        st.session_state.tenants = None

    # --- Sidebar: Configuration & Controls ---
    with st.sidebar:
        st.header("⚙️ Control Panel")
        
        # Expand Data Sourcing if no data exists
        show_sourcing = st.session_state.tenants is None
        with st.expander("1. Data Sourcing", expanded=show_sourcing):
            _prefilled_map_url = _load_shared_map_url()
            mall_url = st.text_input("Mall Map URL", value=_prefilled_map_url, placeholder="https://www.simon.com/mall/midland-park-mall/map/#/")
            
            use_vision = st.checkbox("Use Vision AI (for Image format mall maps)", value=False, help="Enable this if the mall map is a canvas or image and standard scraping fails. It captures a screenshot and uses AI to read the legend.")
            
            sc_col1, sc_col2 = st.columns(2)
            with sc_col1:
                if st.button("🔄 Run Scraper", use_container_width=True):
                    if not mall_url:
                        st.error("Please enter a valid Mall Map URL.")
                    else:
                        with st.spinner(" Scraping Mall Map Tenants Data (AI Vision)..." if use_vision else "Scraping Mall Map Tenants Data..."):
                            data = scrape_mall_data(mall_url, use_vision=use_vision)
                            if data:
                                st.session_state.tenants = data
                                st.success(f"Scraped {len(data)} tenants!")
                                st.rerun()
                            else:
                                st.error("Scraping failed. Try toggling Vision AI mode.")
            
            with sc_col2:
                if st.button("🗑️ Reset", use_container_width=True, help="Clear current session data"):
                    st.session_state.tenants = None
                    if 'analysis_results' in st.session_state:
                        del st.session_state['analysis_results']
                    st.rerun()

            st.markdown("---")
            st.markdown("**OR Manual Image Source**")
            manual_map = st.file_uploader("Upload Official Map Image", type=['png', 'jpg', 'jpeg'], help="Upload a map with a legend to manually populate the database.")
            
            if manual_map:
                if st.button("Scrape from Uploaded Image", use_container_width=True):
                    with st.spinner("Extracting tenants from image..."):
                        # Save temp file
                        temp_path = os.path.join(os.getcwd(), "manual_upload_temp.png")
                        with open(temp_path, "wb") as f:
                            f.write(manual_map.getbuffer())
                        
                        # Dynamic import
                        import sys
                        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                        if root_dir not in sys.path:
                            sys.path.append(root_dir)
                        from Mall_Ai_Dashboard.llm_engine import extract_shops_from_image_via_llm
                        
                        data = extract_shops_from_image_via_llm(temp_path)
                        if data:
                            # Convert to standard format
                            processed_data = []
                            for d in data:
                                processed_data.append({
                                    "name": d['name'],
                                    "floor": d.get('floor', 'Level 1'),
                                    "location_id": d.get('location_id', ''),
                                    "description": d.get('description', ''),
                                    "hours": "Not available",
                                    "latitude": None,
                                    "longitude": None
                                })
                            st.session_state.tenants = processed_data
                            st.success(f"Extracted {len(processed_data)} tenants!")
                            st.rerun()
                        else:
                            st.error("Failed to extract data from image.")

            # Optional: Allow loading from disk if it exists, but keep it hidden/secondary
            if os.path.exists(JSON_DATA_PATH) and st.session_state.tenants is None:
                if st.button("📂 Restore from Disk", use_container_width=True, help="Load previous scrape result from local storage"):
                    st.session_state.tenants = load_json_data()
                    st.rerun()

        with st.expander("2. Analysis Settings", expanded=True):
            similarity_threshold = st.slider("Matching Sensitivity", 0.3, 0.9, 0.6, 0.05, 
                                             help="Higher means stricter matching between OCR and Database")
        
        st.info("💡 **Feature Enabled**: If ≥3 tenants are detected in a screenshot, the app will automatically overlay missing tenants onto the image.")

    # --- Tenant State ---
    tenants = st.session_state.tenants
    
    if not tenants:
        st.header("🛍️ Welcome to Mall Intelligence")
        st.info("The database is currently empty. Please enter a Mall Map URL in the sidebar and click **Run Scraper** to begin.")
        
        st.markdown("""
        ### Getting Started
        1. **Paste a Mall URL** (e.g., from simon.com) into the sidebar.
        2. **Run the Scraper** to fetch current tenants and floor maps.
        3. **Analyze Images** in the tabs above once the database is populated.
        
        *No default data is loaded automatically to ensure you always work with fresh information.*
        """)
        return

    df_tenants = pd.DataFrame(tenants)
    if 'hours' in df_tenants.columns:
        df_tenants['hours'] = df_tenants['hours'].apply(clean_hours_helper)

    # --- Main Application Tabs ---
    tab_db, tab_loc, tab_comp = st.tabs([
        "📊 Tenant Database", 
        "📍 Location Detail",
        "🔄 Comparison Tool", 
    ])

    with tab_db:
        st.subheader(f"🗂️ Master Tenant Database ({len(tenants)} entries)")
        st.markdown("Use the table below to explore all scraped mall tenants.")
        
        # Enhanced Table with Scrolling
        if not df_tenants.empty:
            cols_to_show = ['name', 'floor', 'location_id', 'hours', 'latitude', 'longitude', 'description']
            valid_cols = [c for c in cols_to_show if c in df_tenants.columns]
            
            st.dataframe(
                df_tenants[valid_cols],
                use_container_width=True,
                height=600, # Increased height for better vertical viewing
                column_config={
                    "name": st.column_config.TextColumn("Tenant Name", width="medium"),
                    "floor": st.column_config.TextColumn("Floor/Level", width="small"),
                    "hours": st.column_config.TextColumn("Operating Hours", width="large"),
                    "latitude": st.column_config.NumberColumn("Latitude", format="%.6f"),
                    "longitude": st.column_config.NumberColumn("Longitude", format="%.6f"),
                    "description": st.column_config.TextColumn("Description", width="large"),
                }
            )
            
            # Download Link for the full DB
            csv_db = df_tenants.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Full Database as CSV",
                data=csv_db,
                file_name="mall_tenants_full.csv",
                mime="text/csv",
            )
        
    with tab_loc:
        st.subheader("📍 Detailed Location & Coordinate Data")
        st.markdown("This table provides specific georeferenced coordinates and location IDs for each tenant.")
        
        if not df_tenants.empty:
            # Filter for specific columns requested by the user
            loc_req_cols = ['name', 'location_id', 'latitude', 'longitude', 'floor']
            # Ensure columns exist in dataframe
            available_loc_cols = [c for c in loc_req_cols if c in df_tenants.columns]
            
            df_loc = df_tenants[available_loc_cols].copy()
            
            # Display the table
            st.dataframe(
                df_loc,
                use_container_width=True,
                height=500,
                column_config={
                    "name": st.column_config.TextColumn("Tenant Name", width="medium"),
                    "location_id": st.column_config.TextColumn("Location ID", width="small"),
                    "latitude": st.column_config.NumberColumn("Latitude", format="%.6f"),
                    "longitude": st.column_config.NumberColumn("Longitude", format="%.6f"),
                    "floor": st.column_config.TextColumn("Floor", width="small"),
                }
            )
            
            # Provide specific download button for this table
            csv_loc_data = df_loc.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Location Coordinate Table (CSV)",
                data=csv_loc_data,
                file_name="tenant_location_coordinates.csv",
                mime="text/csv",
                key="download_loc_csv"
            )

    with tab_comp:
        st.subheader("🔄 Tenant Inventory Comparison")
        st.markdown("Compare an **old tenant file** with the **newly scraped data** to see what's changed.")
        
        uploaded_file = st.file_uploader("Upload Old Tenant File (Excel, CSV, or Text)", type=['xlsx', 'xls', 'csv', 'txt'], key="old_inventory")
        
        if uploaded_file:
            try:
                # Load the old data based on file extension
                file_ext = os.path.splitext(uploaded_file.name)[1].lower()
                
                if file_ext in ['.xlsx', '.xls']:
                    df_old = pd.read_excel(uploaded_file)
                elif file_ext == '.csv':
                    df_old = pd.read_csv(uploaded_file)
                elif file_ext == '.txt':
                    # For TXT files, assume one name per line or tab-separated
                    lines = uploaded_file.getvalue().decode("utf-8").splitlines()
                    df_old = pd.DataFrame({"Tenant Name": lines})
                else:
                    st.error(f"Unsupported file format: {file_ext}")
                    st.stop()
                
                with st.expander(f"📄 Preview Uploaded Data ({file_ext})", expanded=False):
                    st.dataframe(df_old.head(10), use_container_width=True)
                
                # Column selection for matching
                name_cols = [c for c in df_old.columns if 'name' in c.lower() or 'tenant' in c.lower() or 'store' in c.lower()]
                selected_col = st.selectbox(
                    "Select the column containing Tenant Names in your Excel file:", 
                    options=df_old.columns, 
                    index=df_old.columns.get_loc(name_cols[0]) if name_cols else 0
                )
                
                if st.button("🚀 Run Comparison Analysis", type="primary"):
                    # 1. Prepare sets for comparison (clean names)
                    old_names_raw = df_old[selected_col].dropna().astype(str).tolist()
                    old_names_clean = {n.strip().lower() for n in old_names_raw if n.strip()}
                    
                    current_names_map = {n.strip().lower(): n for n in df_tenants['name'] if n}
                    current_names_clean = set(current_names_map.keys())
                    
                    # 2. Logic: Common, New, Missing
                    common_clean = old_names_clean.intersection(current_names_clean)
                    new_clean = current_names_clean - old_names_clean
                    missing_clean = old_names_clean - current_names_clean
                    
                    # 3. Format results for display
                    common_list = sorted([current_names_map[n] for n in common_clean])
                    new_list = sorted([current_names_map[n] for n in new_clean])
                    
                    # For missing, we need the original casing from the old file if possible
                    missing_map = {n.strip().lower(): n for n in old_names_raw if n.strip()}
                    missing_list = sorted([missing_map[n] for n in missing_clean])
                    
                    # 4. Display Metrics
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Common Tenants", len(common_list), help="Present in both old file and new scrape")
                    m2.metric("New Tenants ✨", len(new_list), help="Present in new scrape but NOT in old file")
                    # m3.metric("Missing Tenants ⚠️", len(missing_list), help="Present in old file but NOT in new scrape")
                    
                    # 5. Result Tables
                    res_col1, res_col2, res_col3 = st.columns(3)
                    
                    with res_col1:
                        st.markdown("### ✅ Common Tenants")
                        st.markdown("*Found in both lists*")
                        if common_list:
                            st.dataframe(pd.DataFrame({"Tenant Name": common_list}), use_container_width=True, height=450)
                        else:
                            st.write("No common tenants found.")
                            
                    with res_col2:
                        st.markdown("### 🆕 New Tenants")
                        st.markdown("*Newly added to the mall*")
                        if new_list:
                            st.dataframe(pd.DataFrame({"Tenant Name": new_list}), use_container_width=True, height=450)
                        else:
                            st.write("No new tenants found.")
                            
                            
            except Exception as e:
                st.error(f"Failed to process the Excel file. Error: {e}")
        else:
            st.info("💡 Please upload an Excel file (.xlsx or .xls) to start the comparison.")


if __name__ == "__main__":
    main()
 