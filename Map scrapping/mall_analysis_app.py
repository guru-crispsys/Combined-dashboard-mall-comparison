import streamlit as st
import json
import requests
from PIL import Image, ImageOps, ImageEnhance
import numpy as np
import os
import easyocr
from sentence_transformers import SentenceTransformer, util
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

@st.cache_resource
def load_models():
    # Load OCR and Improved SBERT models
    # ENABLE QUANTIZATION to fix memory error
    reader = easyocr.Reader(['en'], gpu=False, verbose=False, quantize=True)
    # Using 'all-MiniLM-L6-v2' for efficiency and accuracy in semantic matching
    model = SentenceTransformer('all-MiniLM-L6-v2') 
    return reader, model

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
    
    # Increase resolution for better OCR on small labels (1800px is better for detail)
    max_dim = 1800
    w, h = img.size
    if w > max_dim or h > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    
    # Advanced enhancement: Increase contrast and sharpness more precisely
    img = ImageOps.autocontrast(img)
    img = ImageEnhance.Contrast(img).enhance(1.5)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img

def solve_latlon_to_pixel(valid_pts):
    """
    Highly accurate coordinate projection for Mall Maps.
    Includes data normalization for numeric stability.
    """
    if len(valid_pts) < 3:
        return None, None, None
        
    src_pts = np.array([[p['lon'], p['lat']] for p in valid_pts], dtype=np.float32)
    dst_pts = np.array([[p['x'], p['y']] for p in valid_pts], dtype=np.float32)

    # Normalize coordinates to improve numeric stability of the solvers
    # This is crucial when mapping small Lat/Lon to large pixel values
    src_mean = src_pts.mean(axis=0)
    dst_mean = dst_pts.mean(axis=0)
    
    if len(valid_pts) >= 4:
        # Homography with stricter RANSAC for perspective correction
        H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 2.0)
        return H, "homography", mask
    else:
        # Affine with RANSAC for 2D flat maps
        M, mask = cv2.estimateAffine2D(src_pts, dst_pts, method=cv2.RANSAC, ransacReprojThreshold=2.0)
        return M, "affine", mask

def run_analysis(image_path, reader, sbert_model, tenants, json_embeddings, threshold=0.6):
    """
    Analyzes a single image using improved OCR and cleaner visual markings.
    """
    # 1. OCR Preprocessing & Detection
    image = preprocess_image(image_path)
    img_np = np.array(image)
    h, w = img_np.shape[:2]
    
    try:
        # Tuning EasyOCR for map labels: paragraph=False avoids grouping unrelated stores
        results = reader.readtext(img_np, detail=1, paragraph=False, min_size=5)
    except Exception as e:
        print(f"OCR Error: {e}")
        return image, img_np, img_np, [], []

    ocr_data = [] 
    for (bbox, text, prob) in results:
        # Map labels are often low contrast; keep anything above 0.15
        if prob > 0.15:
            ocr_data.append({"text": text, "bbox": bbox, "prob": prob})

    ocr_texts = [d["text"] for d in ocr_data]
    
    # Layers
    detection_img = img_np.copy()
    missing_map_img = img_np.copy()
    
    # 2. Match with Database
    json_names = [t['name'] for t in tenants if t['name']]
    match_results = []
    
    if json_names and ocr_data and json_embeddings is not None:
        valid_indices = [i for i, d in enumerate(ocr_data) if d["prob"] > 0.2]
        valid_texts = [ocr_data[i]["text"] for i in valid_indices]
        
        if valid_texts:
            ocr_embeddings = sbert_model.encode(valid_texts, convert_to_tensor=True, show_progress_bar=False)
            cosine_scores = util.cos_sim(json_embeddings, ocr_embeddings).cpu().numpy()
            
            all_pair_scores = []
            for i, j_name in enumerate(json_names):
                for j, o_text in enumerate(valid_texts):
                    sbert_score = float(cosine_scores[i][j])
                    fuzzy_score = fuzz.token_set_ratio(j_name.lower(), o_text.lower()) / 100.0
                    hybrid_score = (sbert_score * 0.7) + (fuzzy_score * 0.3)
                    
                    len_ratio = min(len(j_name), len(o_text)) / max(len(j_name), len(o_text))
                    if len_ratio < 0.4:
                        hybrid_score *= 0.7
                    all_pair_scores.append((hybrid_score, i, j))
            
            all_pair_scores.sort(key=lambda x: x[0], reverse=True)
            assigned_json = set()
            assigned_ocr = set()
            matched_map = {}
            
            for score, j_idx, o_idx in all_pair_scores:
                if j_idx not in assigned_json and o_idx not in assigned_ocr:
                    if score >= threshold:
                        matched_map[j_idx] = (o_idx, score)
                        assigned_json.add(j_idx)
                        assigned_ocr.add(o_idx)
            
            for i, name in enumerate(json_names):
                tenant_obj = tenants[i]
                entry = {
                    "Tenant": name,
                    "Floor": tenant_obj.get('floor', 'Unknown'),
                    "Latitude": tenant_obj.get('latitude'),
                    "Longitude": tenant_obj.get('longitude'),
                    "Description": tenant_obj.get('description', ''),
                    "LocationID": tenant_obj.get('location_id', '')
                }
                
                if i in matched_map:
                    o_idx, b_score = matched_map[i]
                    best_match_obj = ocr_data[valid_indices[o_idx]]
                    entry.update({
                        "Status": "Found",
                        "MatchCandidate": best_match_obj["text"],
                        "Score": b_score,
                        "BBox": best_match_obj["bbox"]
                    })
                    (tl, tr, br, bl) = best_match_obj["bbox"]
                    cv2.rectangle(detection_img, (int(tl[0]), int(tl[1])), (int(br[0]), int(br[1])), (0, 255, 0), 1)
                else:
                    entry.update({"Status": "Missing", "MatchCandidate": "-", "Score": 0.0, "BBox": None})
                match_results.append(entry)

    # 3. Georeferencing Overlay with Floor Detection
    initial_anchors = []
    found_floors = []
    for r in match_results:
        if r['Status'] == 'Found' and r['Score'] > 0.8 and r.get('Latitude') and r.get('Longitude'):
            (tl, tr, br, bl) = r['BBox']
            initial_anchors.append({
                'lat': r['Latitude'], 'lon': r['Longitude'], 
                'x': (tl[0] + br[0]) / 2, 'y': (tl[1] + br[1]) / 2
            })
            found_floors.append(r['Floor'])

    # Determine the most likely floor shown in this image
    detected_floor = Counter(found_floors).most_common(1)[0][0] if found_floors else None

    if len(initial_anchors) >= 3:
        M, transform_type, mask = solve_latlon_to_pixel(initial_anchors)
        if M is not None:
            inliers = mask.ravel().tolist() if mask is not None else [1] * len(initial_anchors)
            refined_anchors = [initial_anchors[idx] for idx, val in enumerate(inliers) if val]
            M, transform_type, _ = solve_latlon_to_pixel(refined_anchors)
            
            # Setup for Collision-Free Marking
            occupied_rects = []
            # Reserve area for existing OCR finds
            for r in match_results:
                if r['Status'] == 'Found' and r['BBox']:
                    (tl, tr, br, bl) = r['BBox']
                    occupied_rects.append((int(tl[0]-5), int(tl[1]-5), int(br[0]+5), int(br[1]+5)))

            # Mark missing tenants (ONLY for the detected floor to improve accuracy/clutter)
            for r in match_results:
                if r['Status'] == 'Missing' and r.get('Latitude') and r.get('Longitude'):
                    # SKIP if tenant belongs to a different floor than the one we detected
                    if detected_floor and r['Floor'] != detected_floor:
                        continue
                        
                    lon, lat = r['Longitude'], r['Latitude']
                    if transform_type == "homography":
                        # Standard matrix projection
                        denom = M[2,0]*lon + M[2,1]*lat + M[2,2]
                        px = (M[0,0]*lon + M[0,1]*lat + M[0,2]) / denom
                        py = (M[1,0]*lon + M[1,1]*lat + M[1,2]) / denom
                    else:
                        px = M[0,0]*lon + M[0,1]*lat + M[0,2]
                        py = M[1,0]*lon + M[1,1]*lat + M[1,2]

                    if 15 <= px < w-15 and 15 <= py < h-15:
                        # Draw Marker: Concentric circles for high visibility
                        cv2.circle(missing_map_img, (int(px), int(py)), 4, (255, 255, 255), -1, cv2.LINE_AA)
                        cv2.circle(missing_map_img, (int(px), int(py)), 2, (0, 0, 255), -1, cv2.LINE_AA)
                        
                        # Smart Labeling (Collision Detection)
                        label = r['Tenant'].title()
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        font_scale = 0.35
                        thickness = 1
                        (lw, lh), _ = cv2.getTextSize(label, font, font_scale, thickness)
                        
                        # Try placing label in sorted order of preference
                        best_pos = None
                        offsets = [
                            (10, -5),   # Top Right
                            (10, 10),   # Bottom Right
                            (-lw-10, -5), # Top Left
                            (-lw-10, 10), # Bottom Left
                            (-lw/2, -15), # Directly Above
                            (-lw/2, 20)   # Directly Below
                        ]
                        
                        for ox, oy in offsets:
                            lx, ly = int(px) + int(ox), int(py) + int(oy)
                            # Create a relaxed bounding box for the label with 4px padding
                            rect = (lx-4, ly-lh-4, lx+lw+4, ly+4)
                            
                            if 5 <= rect[0] and rect[2] < w-5 and 5 <= rect[1] and rect[3] < h-5:
                                collision = False
                                for o in occupied_rects:
                                    # Standard AABB collision check
                                    if not (rect[2] < o[0] or rect[0] > o[2] or rect[3] < o[1] or rect[1] > o[3]):
                                        collision = True
                                        break
                                if not collision:
                                    best_pos = (lx, ly, rect)
                                    break
                        
                        if best_pos:
                            lx, ly, rect = best_pos
                            occupied_rects.append(rect)
                            # Professional Label Style: White background box with red border
                            cv2.rectangle(missing_map_img, (rect[0], rect[1]), (rect[2], rect[3]), (255, 255, 255), -1)
                            cv2.rectangle(missing_map_img, (rect[0], rect[1]), (rect[2], rect[3]), (0, 0, 255), 1)
                            cv2.putText(missing_map_img, label, (lx, ly), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    return image, detection_img, missing_map_img, match_results, ocr_texts


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
    st.set_page_config(layout="wide", page_title="Mall Tenant Intelligence", page_icon="🛍️")
    
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
    
    reader, sbert_model = load_models()

    # --- Data Management ---
    if 'tenants' not in st.session_state:
        st.session_state.tenants = None

    # --- Sidebar: Configuration & Controls ---
    with st.sidebar:
        st.header("⚙️ Control Panel")
        
        # Expand Data Sourcing if no data exists
        show_sourcing = st.session_state.tenants is None
        with st.expander("1. Data Sourcing", expanded=show_sourcing):
            mall_url = st.text_input("Mall Map URL", "", placeholder="https://www.simon.com/mall/midland-park-mall/map/#/")
            
            sc_col1, sc_col2 = st.columns(2)
            with sc_col1:
                if st.button("🔄 Run Scraper", use_container_width=True):
                    if not mall_url:
                        st.error("Please enter a valid Mall Map URL.")
                    else:
                        with st.spinner("Scraping Mall Data..."):
                            data = scrape_mall_data(mall_url)
                            if data:
                                st.session_state.tenants = data
                                st.success(f"Scraped {len(data)} tenants!")
                                st.rerun()
                            else:
                                st.error("Scraping failed.")
            
            with sc_col2:
                if st.button("🗑️ Reset", use_container_width=True, help="Clear current session data"):
                    st.session_state.tenants = None
                    if 'analysis_results' in st.session_state:
                        del st.session_state['analysis_results']
                    st.rerun()

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
    tab_db, tab_comp, tab_img, tab_report = st.tabs([
        "📊 Tenant Database", 
        "🔄 Comparison Tool", 
        "🔍 Image Analysis", 
        "📈 Comparison Report"
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
                            
                    # with res_col3:
                    #     st.markdown("### ❌ Missing Tenants")
                    #     st.markdown("*Gone from the latest scrape*")
                    #     if missing_list:
                    #         st.dataframe(pd.DataFrame({"Tenant Name": missing_list}), use_container_width=True, height=450)
                    #     else:
                    #         st.write("No missing tenants found.")
                            
            except Exception as e:
                st.error(f"Failed to process the Excel file. Error: {e}")
        else:
            st.info("💡 Please upload an Excel file (.xlsx or .xls) to start the comparison.")

    with tab_img:
        st.subheader(" Visual Map Analysis")
        st.markdown("Browse and select one or more mall map screenshots to identify detected and missing tenants.")
        
        # File Uploader - Dynamic Browse
        uploaded_files = st.file_uploader("Upload Mall Map Screenshots (Multiple Allowed)", 
                                         type=['png', 'jpg', 'jpeg'], 
                                         accept_multiple_files=True)
        
        if uploaded_files:
            st.success(f"✅ **{len(uploaded_files)}** images loaded and ready.")
            
            # Dynamic Preview Gallery
            with st.expander(" Preview Uploaded Images", expanded=False):
                cols = st.columns(4)
                for i, file in enumerate(uploaded_files):
                    cols[i % 4].image(file, caption=file.name, use_container_width=True)

            if st.button(" Run Comprehensive Analysis", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                if 'analysis_results' not in st.session_state:
                    st.session_state['analysis_results'] = {}
                
                # PRE-CALCULATE Embeddings once
                status_text.info(" Pre-calculating tenant embeddings...")
                json_names = [t['name'] for t in tenants if t['name']]
                json_embeddings = sbert_model.encode(json_names, convert_to_tensor=True, show_progress_bar=False)
                
                for idx, uploaded_file in enumerate(uploaded_files):
                    img_name = uploaded_file.name
                    status_text.info(f"⚙️ **Processing ({idx+1}/{len(uploaded_files)}):** `{img_name}`...")
                    
                    try:
                        time.sleep(0.1)
                        orig_img, det_img, miss_img, matches, detected_text = run_analysis(
                            uploaded_file, reader, sbert_model, tenants, json_embeddings, threshold=similarity_threshold
                        )
                        
                        if matches:
                            st.session_state['analysis_results'][img_name] = {
                                'matches': matches,
                                'det_img': det_img,
                                'miss_img': miss_img
                            }
                            
                            # LIVE RESULTS TABLE
                            with st.expander(f"📊 Results for {img_name}", expanded=True):
                                df = pd.DataFrame(matches)
                                found_df = df[df['Status'] == 'Found'][['Tenant', 'Score', 'Floor', 'LocationID']]
                                st.markdown(f"**Verified Tenants Identified:** `{len(found_df)}`")
                                st.dataframe(found_df, use_container_width=True)
                                st.image(det_img, caption="Detection Highlight", use_container_width=True)
                            
                            # Backup to disk
                            report_path = os.path.join(IMAGES_DIR, f"report_{img_name}.csv")
                            pd.DataFrame(matches).to_csv(report_path, index=False)
                    except Exception as e:
                        st.error(f" Error processing `{img_name}`: {e}")
                    
                    gc.collect() 
                    progress_bar.progress((idx + 1) / len(uploaded_files))
                
                status_text.success(f"🎊 **Batch Complete!** Switch to 'Comparison Report' to see the audit.")
        else:
            st.info("👆 Use the browser above to upload map images from your local machine.")

    with tab_report:
        st.subheader("Comparison & Coverage Report")
        
        if 'analysis_results' not in st.session_state:
            st.info("Run the analysis in the 'Image Analysis' tab first to generate this report.")
        else:
            results = st.session_state['analysis_results']
            
            # Create Comparison Matrix
            # Columns: Tenant, Image 1 (Found/Missing), Image 2...
            all_tenants_names = [t['name'] for t in tenants]
            comparison_df = pd.DataFrame({'Tenant': all_tenants_names})
            
            for img_name, data in results.items():
                matches = data['matches']
                match_dict = {m['Tenant']: m['Status'] for m in matches}
                comparison_df[img_name] = comparison_df['Tenant'].map(match_dict)
            
            # --- Visual Missing Map Gallery ---
            st.write("#### 📍 Missing Tenant Marking Maps")
            st.markdown("These maps show red dots for tenants that exist in the database for the detected floor but were **not** found in the screenshot via OCR.")
            
            for img_name, data in results.items():
                with st.expander(f"🗺️ Missing Markings for {img_name}", expanded=True):
                    st.image(data['miss_img'], use_container_width=True)
            
            # Summary Metrics
            found_at_least_once = comparison_df.iloc[:, 1:].eq('Found').any(axis=1).sum()
            total_unique = len(all_tenants_names)
            coverage = (found_at_least_once / total_unique) * 100
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Database Tenants", total_unique)
            c2.metric("Tenants Found in Maps", found_at_least_once)
            c3.metric("Map Coverage %", f"{coverage:.1f}%")
            
            st.write("#### 📊 Visibility Matrix")
            st.markdown("This table shows which tenants were detected in each analyzed image.")
            
            # Styling the matrix
            def color_status(val):
                color = '#d4edda' if val == 'Found' else '#f8d7da' if val == 'Missing' else 'white'
                return f'background-color: {color}'
            
            st.dataframe(
                comparison_df.style.applymap(color_status, subset=comparison_df.columns[1:]),
                use_container_width=True,
                height=500
            )
            
            # Missing overall
            missing_overall = comparison_df[~comparison_df.iloc[:, 1:].eq('Found').any(axis=1)]
            if not missing_overall.empty:
                with st.expander(f"⚠️ Tenants Not Found in Any Image ({len(missing_overall)})"):
                    st.dataframe(missing_overall[['Tenant']], use_container_width=True, height=300)

            # Export full comparison
            st.download_button(
                label="📥 Download Comparison Matrix (CSV)",
                data=comparison_df.to_csv(index=False).encode('utf-8'),
                file_name="comparison_matrix.csv",
                mime="text/csv",
            )

if __name__ == "__main__":
    main()
