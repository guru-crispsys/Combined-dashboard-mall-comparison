"""
Combined Dashboard - Main UI
Run: streamlit run main_ui.py --server.port 8501
Apps start automatically on first load. Click a link to open in a new tab (no collapse, opens immediately).
"""

import json
import socket
import subprocess
import sys
from pathlib import Path

import streamlit as st

# Ports and app paths (ROOT = folder containing main_ui.py)
ROOT = Path(__file__).resolve().parent
SHARED_INPUT_FILE = ROOT / "shared_dashboard_input.json"

# Prefer project .venv Python so all sub-apps use same env
def _python_executable():
    venv_exe = ROOT / ".venv" / "Scripts" / "python.exe" if sys.platform == "win32" else ROOT / ".venv" / "bin" / "python"
    if venv_exe.exists():
        return str(venv_exe)
    return sys.executable

PORT_STORE_OPENING = 8502
PORT_MALL_DASHBOARD = 8503
PORT_MAP_DASHBOARD = 8504

APPS = [
    {
        "key": "store_opening",
        "icon": "🔍",
        "title": "Store Opening Discovery",
        "desc": "Find mall and store opening data with AI. Extract 2026 tenant and event info from the web.",
        "port": PORT_STORE_OPENING,
        "cwd": ROOT / "googlesearch",
        "script": "app_streamlit.py",
    },
    {
        "key": "mall_dashboard",
        "icon": "🏬",
        "title": "Mall AI Dashboard",
        "desc": "Scrape mall directories and Facebook/Instagram. Compare data over time and generate AI insights.",
        "port": PORT_MALL_DASHBOARD,
        "cwd": ROOT / "Mall_Ai_Dashboard",
        "script": "app.py",
    },
    {
        "key": "map_dashboard",
        "icon": "🗺️",
        "title": "Map Visual Analysis",
        "desc": "Analyze mall map screenshots with OCR. Match tenants to your database and see gaps on the map.",
        "port": PORT_MAP_DASHBOARD,
        "cwd": ROOT / "Map scrapping",
        "script": "mall_analysis_app.py",
    },
]


def is_port_in_use(port: int) -> bool:
    """Return True if something is already listening on this port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_free_port(start_port: int, max_tries: int = 20) -> int:
    """
    Find a free TCP port, starting at start_port and scanning upward.
    Returns the first available port, or start_port if none found within range.
    """
    port = start_port
    for _ in range(max_tries):
        if not is_port_in_use(port):
            return port
        port += 1
    # Fallback: return the original requested port (may still be in use)
    return start_port


def load_shared_input() -> dict:
    """Load mall/search input from shared JSON. Returns dict with empty strings if missing."""
    default = {
        "mall_name": "",
        "address": "",
        "official_website": "",
        "mall_facebook_link": "",
        "mall_instagram_link": "",
        "hashtags_youtube_twitter": "",
        "googlesearch_query": "",
        "map_visual_url": "",
    }
    if not SHARED_INPUT_FILE.exists():
        return default
    try:
        with open(SHARED_INPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**default, **{k: str(v).strip() if v is not None else "" for k, v in data.items()}}
    except Exception:
        return default


def save_shared_input(data: dict) -> None:
    """Write mall/search input to shared JSON for sub-apps to read."""
    with open(SHARED_INPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def start_app(cwd: Path, script: str, preferred_port: int) -> int:
    """
    Start a Streamlit app in the background and return the actual port used.

    - We always try to start a *fresh* process so you don't accidentally
      reuse a stale server from an earlier run with old code.
    - If the preferred port is already in use, we scan upwards to find
      the next free port and use that.
    - stdout/stderr are inherited so each sub‑app's logs show in the same
      terminal where you run `streamlit run main_ui.py`.
    """
    app_path = cwd / script
    if not app_path.exists():
        # Could optionally show a Streamlit warning here, but simply return.
        return preferred_port

    actual_port = _find_free_port(preferred_port)

    subprocess.Popen(
        [
            _python_executable(),
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port",
            str(actual_port),
            "--server.headless",
            "true",
        ],
        cwd=str(cwd),
        # Inherit stdout/stderr so logs appear in the main terminal
        stdout=None,
        stderr=None,
    )
    return actual_port


st.set_page_config(page_title="Combined Dashboard", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

# One-time delivery token per app: when an app loads with a matching token, it pre-fills then clears its token so refresh won't pre-fill again.
import uuid
DELIVERY_TOKEN_FILE = ROOT / "shared_dashboard_delivery_token.json"
if "delivery_tokens" not in st.session_state:
    st.session_state.delivery_tokens = {app["key"]: str(uuid.uuid4()) for app in APPS}
try:
    DELIVERY_TOKEN_FILE.write_text(json.dumps(st.session_state.delivery_tokens), encoding="utf-8")
except Exception:
    pass

# Start apps on first load (once per browser session) so links open immediately.
# We also remember the *actual* port each app was started on, since we may have
# to move to a different free port if the preferred one is already in use.
if "app_ports" not in st.session_state:
    st.session_state.app_ports = {}
    for app in APPS:
        actual_port = start_app(app["cwd"], app["script"], app["port"])
        st.session_state.app_ports[app["key"]] = actual_port

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* Base: clean dark background */
.stApp {
    background: #0f1419;
    color: #e7e9ea;
    min-height: 100vh;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Header: clear hierarchy */
.dashboard-header {
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.08);
}
.dashboard-title {
    font-size: 1.75rem;
    font-weight: 700;
    color: #fff;
    margin: 0 0 0.25rem 0;
    letter-spacing: -0.02em;
}
.dashboard-subtitle {
    color: #8b98a5;
    font-size: 0.9375rem;
    margin: 0;
    font-weight: 400;
}

/* Cards: neat, readable */
.project-card {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    background: #192734;
    padding: 1.5rem 1.75rem;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 1rem;
    transition: border-color 0.15s ease, background 0.15s ease;
}
.project-card:hover {
    border-color: rgba(29,155,240,0.35);
    background: #1c2d3d;
}
.project-card-info { width: 100%; }
.project-card-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: #fff;
    margin: 0 0 0.5rem 0;
    line-height: 1.3;
}
.project-card-desc {
    color: #8b98a5;
    font-size: 0.875rem;
    line-height: 1.5;
    margin: 0;
}
.project-card-cta-container { width: 100%; margin-top: 0.25rem; }
.project-card-cta {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.4rem 0.9rem;
    background: #1d9bf0;
    color: #fff !important;
    border-radius: 9999px;
    text-decoration: none;
    font-weight: 600;
    font-size: 0.8125rem;
    transition: background 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
    box-shadow: 0 0 0 0 rgba(29,155,240,0.4);
}
.project-card-cta:hover {
    background: #1a8cd8;
    color: #fff !important;
    transform: scale(1.04);
    box-shadow: 0 0 0 4px rgba(29,155,240,0.25);
}

/* Input section */
.input-section { margin-bottom: 2rem; }
.input-section h3 { font-size: 1rem; font-weight: 600; color: #fff; margin: 0 0 1rem 0; }
.input-row { border-bottom: 1px solid rgba(255,255,255,0.08); padding: 0.5rem 0; margin-bottom: 0.25rem; }
.input-label { font-size: 0.875rem; color: #8b98a5; margin-bottom: 0.25rem; }

/* Footer */
.dashboard-footer {
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(255,255,255,0.06);
    color: #6e767d;
    font-size: 0.8125rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class='dashboard-header'>
    <h1 class='dashboard-title'>Webresearch Combined Dashboard</h1>
    <p class='dashboard-subtitle'>Mall research, scraping, and map analysis in one place</p>
</div>
""", unsafe_allow_html=True)

with st.expander("📝 Mall & search inputs (optional — submit to pre-fill all three apps)", expanded=True):
    st.markdown("Enter data below and click **Submit** to save. The three apps use whatever was last submitted — after you submit new data, open or refresh those apps to see it. Leave fields empty if you prefer to enter data inside each app.")
    with st.form("shared_input_form"):
        mall_name = st.text_input("Mall Name", value="", placeholder="e.g. Westfield Southcenter")
        address = st.text_input("Address", value="", placeholder="Full address")
        official_website = st.text_input("Official Web Site", value="", placeholder="https://...")
        mall_facebook_link = st.text_input("Mall Facebook Link", value="", placeholder="https://www.facebook.com/...")
        mall_instagram_link = st.text_input("Mall Instagram Link", value="", placeholder="https://www.instagram.com/...")
        hashtags_youtube_twitter = st.text_input("Hashtags for use in Youtube, X(Twitter) Posts", value="", placeholder="#mall #shopping ...")
        googlesearch_query = st.text_area("Search query for Store Opening Discovery", value="", placeholder="e.g. Latest update about [mall name] · Coming soon tenants at [mall name]", height=80)
        map_visual_url = st.text_input("Mall Map URL (for Map Visual Analysis)", value="", placeholder="e.g. https://www.simon.com/mall/midland-park-mall/map/#/")
        submitted = st.form_submit_button("Submit")
    if submitted:
        save_shared_input({
            "mall_name": (mall_name or "").strip(),
            "address": (address or "").strip(),
            "official_website": (official_website or "").strip(),
            "mall_facebook_link": (mall_facebook_link or "").strip(),
            "mall_instagram_link": (mall_instagram_link or "").strip(),
            "hashtags_youtube_twitter": (hashtags_youtube_twitter or "").strip(),
            "googlesearch_query": (googlesearch_query or "").strip(),
            "map_visual_url": (map_visual_url or "").strip(),
        })
        st.success("Saved. Open Store Opening Discovery, Mall AI Dashboard, or Map Visual Analysis to use this data.")

st.markdown("---")

# Vertical list of cards (include one-time token per app so pre-fill only when opened from here; refresh in app won't pre-fill)
_tokens = st.session_state.get("delivery_tokens", {})
for app in APPS:
    actual_port = st.session_state.app_ports.get(app["key"], app["port"])
    tok = _tokens.get(app["key"], "")
    url = f"http://localhost:{actual_port}/?from_dashboard={tok}&app={app['key']}" if tok else f"http://localhost:{actual_port}"
    button_label = f"Open {app['title']}"
    st.markdown(
        f"""
        <div class='project-card'>
            <div class='project-card-info'>
                <div class='project-card-title'>{app['icon']} {app['title']}</div>
                <div class='project-card-desc'>{app['desc']}</div>
            </div>
            <div class='project-card-cta-container'>
                <a href='{url}' target='_blank' rel='noopener noreferrer' class='project-card-cta'>{button_label}</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    '<p class="dashboard-footer">Apps start when you open this page. If a link doesn’t load, wait a few seconds and try again.</p>',
    unsafe_allow_html=True,
)

