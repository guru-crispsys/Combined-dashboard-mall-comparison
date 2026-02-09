"""
Combined Dashboard - Main UI
Run: streamlit run main_ui.py --server.port 8501
Apps start automatically on first load. Click a link to open in a new tab (no collapse, opens immediately).
"""

import socket
import subprocess
import sys
from pathlib import Path

import streamlit as st

# Ports and app paths (ROOT = folder containing main_ui.py)
ROOT = Path(__file__).resolve().parent
PORT_STORE_OPENING = 8502
PORT_MALL_DASHBOARD = 8503

APPS = [
    {
        "key": "store_opening",
        "title": "Store Opening Discovery",
        "desc": "Search web for mall/store opening data, extract and analyze with AI. Get 2026 tenant and event info.",
        "port": PORT_STORE_OPENING,
        "cwd": ROOT / "googlesearch",
        "script": "app_streamlit.py",
    },
    {
        "key": "mall_dashboard",
        "title": "Mall AI Dashboard",
        "desc": "Scrape mall directories, compare with old data, run Facebook/Instagram scrapers, and generate AI insights.",
        "port": PORT_MALL_DASHBOARD,
        "cwd": ROOT / "Mall_Ai_Dashboard",
        "script": "app.py",
    },
]


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_app(cwd: Path, script: str, port: int) -> bool:
    """Start Streamlit app in background. Returns True if started or already running."""
    if is_port_in_use(port):
        return True
    app_path = cwd / script
    if not app_path.exists():
        return False
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", str(port), "--server.headless", "true"],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


st.set_page_config(page_title="Combined Dashboard", layout="wide", initial_sidebar_state="expanded")

# Start both apps on first load (once per session) so links open immediately with no popup blocking
if "apps_started" not in st.session_state:
    st.session_state.apps_started = True
    for app in APPS:
        start_app(app["cwd"], app["script"], app["port"])

st.markdown("""
<style>
/* Base */
.stApp { background: linear-gradient(160deg, #0c1222 0%, #1a2332 40%, #0f172a 100%); color: #e2e8f0; min-height: 100vh; }
/* Header */
.dashboard-header { margin-bottom: 2.5rem; }
.dashboard-title { font-size: 2.25rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em; margin: 0 0 0.35rem 0; }
.dashboard-subtitle { color: #64748b; font-size: 1rem; margin: 0; font-weight: 500; }

/* Cards: same height, flex layout */
.project-card {
    height: 280px;
    display: flex;
    flex-direction: column;
    background: linear-gradient(165deg, rgba(30,41,59,0.85) 0%, rgba(15,23,42,0.95) 100%);
    padding: 1.75rem;
    border-radius: 16px;
    border: 1px solid rgba(148,163,184,0.12);
    box-shadow: 0 4px 24px rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.03) inset;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.project-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 0 1px rgba(14,165,233,0.15);
    border-color: rgba(14,165,233,0.2);
}
.project-card-title { font-size: 1.2rem; font-weight: 700; color: #f1f5f9; margin: 0 0 0.75rem 0; line-height: 1.3; }
.project-card-desc {
    flex: 1;
    color: #94a3b8;
    font-size: 0.9rem;
    line-height: 1.5;
    margin: 0 0 1.25rem 0;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
}
.project-card-cta {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: auto;
    padding: 0.75rem 1.25rem;
    background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
    color: white !important;
    border-radius: 10px;
    text-decoration: none;
    font-weight: 600;
    font-size: 0.95rem;
    transition: opacity 0.2s, transform 0.2s;
    box-shadow: 0 2px 12px rgba(14,165,233,0.35);
}
.project-card-cta:hover { opacity: 0.95; transform: scale(1.02); color: white !important; }

/* Footer */
.dashboard-footer { margin-top: 2.5rem; padding-top: 1.25rem; border-top: 1px solid rgba(148,163,184,0.1); color: #64748b; font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class='dashboard-header'>
    <h1 class='dashboard-title'>Combined Dashboard</h1>
    <p class='dashboard-subtitle'>Click a card to open the app in a new tab</p>
</div>
""", unsafe_allow_html=True)

# Equal-height cards: fixed height + flex so button stays at bottom
cols = st.columns(2)
for idx, app in enumerate(APPS):
    url = f"http://localhost:{app['port']}"
    with cols[idx]:
        st.markdown(
            f"""
            <div class='project-card'>
                <div class='project-card-title'>{app['title']}</div>
                <div class='project-card-desc'>{app['desc']}</div>
                <a href='{url}' target='_blank' rel='noopener noreferrer' class='project-card-cta'>Open in new tab →</a>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown(
    '<p class="dashboard-footer">Apps start automatically when you open this page. If a tab shows "can\'t connect", wait a few seconds and click the link again.</p>',
    unsafe_allow_html=True,
)
