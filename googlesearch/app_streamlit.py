"""
Live dashboard for retail store-opening discovery (Streamlit).

Run: streamlit run app_streamlit.py
"""

import csv
import io
import json
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from pipeline import run_pipeline, run_pipeline_gemini_only

def _load_shared_query() -> str:
    """Pre-fill when opened from main UI (has app param); clear token after use to prevent refresh pre-fill."""
    APP_KEY = "store_opening"
    root = Path(__file__).resolve().parent.parent
    shared = root / "shared_dashboard_input.json"
    token_file = root / "shared_dashboard_delivery_token.json"
    
    # Check if shared data exists
    if not shared.exists():
        return ""
    
    try:
        data = json.loads(shared.read_text(encoding="utf-8"))
        query = (data.get("googlesearch_query") or "").strip()
        
        if not query:
            return ""
        
        # Check if we're coming from main UI (has app param)
        try:
            try:
                params = st.query_params
            except AttributeError:
                params = st.experimental_get_query_params()
            
            param_app = params.get("app")
            if isinstance(param_app, list):
                param_app = param_app[0] if param_app else None
            
            # If app param matches, we're coming from main UI - pre-fill and clear token
            if param_app == APP_KEY:
                param_token = params.get("from_dashboard")
                if isinstance(param_token, list):
                    param_token = param_token[0] if param_token else None
                
                # Try to validate and clear token (but pre-fill regardless)
                if token_file.exists() and param_token:
                    try:
                        tokens = json.loads(token_file.read_text(encoding="utf-8"))
                        if tokens.get(APP_KEY) == param_token:
                            # Token matches - clear it so refresh won't pre-fill again
                            tokens[APP_KEY] = ""
                            token_file.write_text(json.dumps(tokens), encoding="utf-8")
                        else:
                            # Token doesn't match - might be refresh, but still pre-fill on first load
                            # Create cleared token so next refresh won't pre-fill
                            tokens[APP_KEY] = ""
                            token_file.write_text(json.dumps(tokens), encoding="utf-8")
                    except Exception:
                        # If token file read fails, create cleared token anyway
                        try:
                            tokens = {APP_KEY: ""}
                            token_file.write_text(json.dumps(tokens), encoding="utf-8")
                        except Exception:
                            pass
                else:
                    # No token file or no token param - create cleared token so refresh won't pre-fill
                    try:
                        tokens = {APP_KEY: ""}
                        token_file.write_text(json.dumps(tokens), encoding="utf-8")
                    except Exception:
                        pass
                
                return query
            else:
                # No app param or doesn't match - check if token was already cleared (refresh scenario)
                if token_file.exists():
                    try:
                        tokens = json.loads(token_file.read_text(encoding="utf-8"))
                        if tokens.get(APP_KEY) == "":
                            # Token was cleared - this is a refresh, don't pre-fill
                            return ""
                    except Exception:
                        pass
                # No app param but token not cleared - might be direct access, don't pre-fill
                return ""
        except Exception:
            # If query param reading fails, don't pre-fill (safety)
            return ""
    except Exception:
        return ""

st.set_page_config(page_title="Store Opening Discovery", page_icon="🔍", layout="wide")
st.title("Retail Store Opening Discovery")
st.caption("Get current 2026 data · Uses OpenAI for AI analysis")

_prefilled_query = _load_shared_query()

with st.form("search_form"):
    use_web_search = st.checkbox(
        "🔍 Search web for live data (recommended)",
        value=True,
        help="Searches Google and scrapes real web pages for current info. Without this, AI uses its knowledge which may be outdated.",
    )
    custom_query = st.text_input(
        "Search query",
        value=_prefilled_query,
        placeholder="e.g. Latest update about Westfield Southcenter Mall · or Coming soon tenants at [mall name]",
    )
    submitted = st.form_submit_button("Get Results")

if submitted:
    if use_web_search:
        with st.spinner("Searching web, extracting pages, and analyzing with AI (this may take 1–2 min)..."):
            out = run_pipeline(
                mall_name=None,
                brand_name=None,
                custom_query=custom_query.strip() or None,
                skip_ai_relevance_check=True,  # Extract from all pages for more complete results
                save_extracted_text=False,  # don't write extracted_output/ files
                export_csv=False,  # don't write structured_output CSV
                export_excel=False,  # don't write structured_output Excel
            )
    else:
        with st.spinner("Sending prompt to AI and parsing result..."):
            out = run_pipeline_gemini_only(
                mall_name=None,
                brand_name=None,
                custom_query=custom_query.strip() or None,
                save_extracted_text=False,  # don't write extracted_output/ files
                export_csv=False,  # don't write structured_output CSV
                export_excel=False,  # don't write structured_output Excel
            )
    rows = out.get("store_openings") or []
    events = out.get("temporary_events") or []
    updates = out.get("latest_updates") or []
    st.success(
        f"Found **{len(updates)}** latest update(s) · **{len(rows)}** new tenant(s) / shop opening(s) · **{len(events)}** event(s)."
    )

    # Result tabs: New openings & events (one tab), Latest updates
    tab_openings_events, tab_updates = st.tabs(["New openings & events", "Latest updates"])

    def _has_value(v):
        """Show field only if it has real content (not empty, not 'Unknown')."""
        if v is None:
            return False
        if isinstance(v, list):
            return len(v) > 0
        s = str(v).strip()
        return len(s) > 0 and s.lower() != "unknown"

    def _source_host(row):
        try:
            return urlparse((row or {}).get("source_url") or "").netloc.lower()
        except Exception:
            return ""

    def _is_official_mall_site(row):
        host = _source_host(row)
        if not host:
            return False
        non_official = ("facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "tiktok.com", "tripadvisor.", "yelp.", "wikipedia.org", "google.com", "maps.google", "news.google")
        if any(f in host for f in non_official):
            return False
        mall_hints = ("mall", "shopping", "centre", "center", "plaza")
        return any(h in host for h in mall_hints) or "Official website:" in str((row or {}).get("source_title") or "")

    with tab_openings_events:
        st.subheader("New shop openings / new tenants")
        if rows:
            official_rows = [r for r in rows if _is_official_mall_site(r)]
            other_rows = [r for r in rows if r not in official_rows]
            if official_rows:
                st.markdown("**From official mall website**")
                st.dataframe(official_rows, width="stretch")
            if other_rows:
                st.markdown("**From other sources (Google search)**")
                st.dataframe(other_rows, width="stretch")
                st.caption("Each row has source_url / source_title so you can see the exact site.")
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=["mall_name", "brand_name", "expected_opening", "location_context", "confidence", "source_url", "source_title"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
            st.download_button("Download new tenants as CSV", data=buf.getvalue(), file_name="store_openings.csv", mime="text/csv", key="dl_openings")
        else:
            st.info("No new tenants or shop openings extracted. Try a query like \"new shop opening in [mall name]\".")

        st.subheader("Temporary events")
        if events:
            official_events = [e for e in events if _is_official_mall_site(e)]
            other_events = [e for e in events if e not in official_events]
            if official_events:
                st.markdown("**From official mall website**")
                st.dataframe(official_events, width="stretch")
            if other_events:
                st.markdown("**From other sources (Google search)**")
                st.dataframe(other_events, width="stretch")
            buf_events = io.StringIO()
            w_events = csv.DictWriter(buf_events, fieldnames=["mall_name", "event_name", "date_or_range", "description", "event_type", "source_url", "source_title"], extrasaction="ignore")
            w_events.writeheader()
            w_events.writerows(events)
            st.download_button("Download events as CSV", data=buf_events.getvalue(), file_name="temporary_events.csv", mime="text/csv", key="dl_events")
        else:
            st.info("No temporary events extracted (concerts, circus, pop-ups, movie releases, etc.).")

    with tab_updates:
        if updates:
            for i, u in enumerate(updates):
                mall = u.get("mall_name") or "Mall"
                addr = u.get("address") or ""
                src_title = (u.get("source_title") or "")
                is_official = "Official website" in src_title or _is_official_mall_site(u)
                subtitle = addr[:50].strip() if _has_value(addr) else ("Official website" if is_official else "Other source")
                with st.expander(f"**{mall}** — {subtitle}", expanded=(i == 0)):
                    if _has_value(u.get("address")):
                        st.markdown(f"**Address:** {u['address']}")
                    if _has_value(u.get("hours_weather")):
                        st.markdown(f"**Hours / Weather:** {u['hours_weather']}")
                    if _has_value(u.get("events")):
                        st.markdown(f"**Events:** {u['events']}")
                    if _has_value(u.get("key_updates")):
                        st.markdown(f"**Key updates:** {u['key_updates']}")
                    stores_info = u.get("stores_mentioned")
                    if isinstance(stores_info, list) and stores_info:
                        st.markdown("**Stores mentioned:**")
                        for store_entry in stores_info:
                            if isinstance(store_entry, dict):
                                name = (store_entry.get("store_name") or "Unknown store").strip()
                                reason = (store_entry.get("why_mentioned") or "").strip()
                                if reason:
                                    st.markdown(f"- **{name}:** {reason}")
                                else:
                                    st.markdown(f"- **{name}**")
                            else:
                                st.markdown(f"- {store_entry}")
                    elif _has_value(stores_info):
                        st.markdown(f"**Stores mentioned:** {stores_info}")
                    if _has_value(u.get("accessibility")):
                        st.markdown(f"**Accessibility:** {u['accessibility']}")
                    if is_official:
                        st.caption("Source: **Official mall website**")
                    if u.get("source_url"):
                        st.caption(f"Link: [{u.get('source_title', 'Link')}]({u['source_url']})")
        else:
            st.info("No latest updates extracted. Try a query like \"latest update about [mall name]\".")

    if not updates and not rows and not events:
        st.info("No updates, new tenants, or events extracted. Try a different query.")
else:
    st.info("Enter a mall name, brand name, or custom prompt and click **Get Results**. For current 2026 data, enable **Search web for live data**.")
