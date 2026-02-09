"""
Launcher: starts main UI (port 8501) and both projects on separate ports.
- Main UI:        http://localhost:8501
- Store Opening:  http://localhost:8502  (googlesearch)
- Mall Dashboard: http://localhost:8503  (Mall_Ai_Dashboard)

Run: python run_all.py
Then open the main UI and click a button to open each project in a new tab.
"""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN_PORT = 8501
PORT_STORE_OPENING = 8502
PORT_MALL_DASHBOARD = 8503

def main():
    streamlit_cmd = [sys.executable, "-m", "streamlit", "run"]
    procs = []

    # Start Store Opening Discovery (googlesearch) - cwd so imports (pipeline, etc.) work
    app1_dir = ROOT / "googlesearch"
    app1 = app1_dir / "app_streamlit.py"
    if not app1.exists():
        print(f"Warning: {app1} not found. Skipping Store Opening Discovery.")
    else:
        p1 = subprocess.Popen(
            streamlit_cmd + [str(app1), "--server.port", str(PORT_STORE_OPENING), "--server.headless", "true"],
            cwd=str(app1_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(("Store Opening Discovery", p1, PORT_STORE_OPENING))
        print(f"Started Store Opening Discovery on http://localhost:{PORT_STORE_OPENING}")

    # Start Mall AI Dashboard - cwd so imports (llm_engine, etc.) work
    app2_dir = ROOT / "Mall_Ai_Dashboard"
    app2 = app2_dir / "app.py"
    if not app2.exists():
        print(f"Warning: {app2} not found. Skipping Mall AI Dashboard.")
    else:
        p2 = subprocess.Popen(
            streamlit_cmd + [str(app2), "--server.port", str(PORT_MALL_DASHBOARD), "--server.headless", "true"],
            cwd=str(app2_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(("Mall AI Dashboard", p2, PORT_MALL_DASHBOARD))
        print(f"Started Mall AI Dashboard on http://localhost:{PORT_MALL_DASHBOARD}")

    # Give child apps a moment to bind
    time.sleep(1.5)

    # Start main UI
    main_ui = ROOT / "main_ui.py"
    if not main_ui.exists():
        print(f"Error: {main_ui} not found.")
        for _, p, _ in procs:
            p.terminate()
        sys.exit(1)

    print(f"Starting main UI on http://localhost:{MAIN_PORT}")
    webbrowser.open(f"http://localhost:{MAIN_PORT}")
    subprocess.run(
        streamlit_cmd + [str(main_ui), "--server.port", str(MAIN_PORT)],
        cwd=str(ROOT),
    )

    # If main UI exits, terminate children
    for name, p, port in procs:
        if p.poll() is None:
            p.terminate()
            print(f"Stopped {name} (port {port})")

if __name__ == "__main__":
    main()
