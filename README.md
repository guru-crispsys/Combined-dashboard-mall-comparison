# Combined Dashboard

One place to run all mall analysis tools: Store Opening Discovery, Mall AI Dashboard, and Map Visual Analysis. Use a single Python environment so every app has the same dependencies and runs without module errors.

---

## Prerequisites

- **Python 3.10+** (3.10 recommended)
- Windows (PowerShell) or macOS/Linux (bash)

---

## One-time setup

### 1. Clone or open the project

```powershell
cd C:\Users\gurui\Documents\combined-dashboard
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Activate the environment

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\activate
```

**macOS/Linux:**
```bash
source .venv/bin/activate
```

You should see `(.venv)` at the start of your prompt.

### 4. Install all dependencies

Install requirements for every app in one go:

```powershell
pip install -r "Map scrapping\requirements.txt" -r "Mall_Ai_Dashboard\requirements.txt" -r "googlesearch\requirements.txt"
```

**On macOS/Linux** (use forward slashes):
```bash
pip install -r "Map scrapping/requirements.txt" -r "Mall_Ai_Dashboard/requirements.txt" -r "googlesearch/requirements.txt"
```

This installs everything needed for:
- **Map scrapping** (easyocr, sentence-transformers, opencv, etc.)
- **Mall AI Dashboard** (streamlit, selenium, openpyxl, etc.)
- **googlesearch** (selenium, google-genai, openai, etc.)

---

## How to run

Always **activate the venv first**, then start the main UI.

### Option A: Main UI (recommended)

One command starts the hub; sub-apps start automatically when you open the page:

```powershell
.\.venv\Scripts\activate
streamlit run main_ui.py --server.port 8501
```

Then open **http://localhost:8501** in your browser. Click each card to open that app in a new tab. The main UI launches the three apps on their ports in the background.

### Option B: run_all.py

```powershell
.\.venv\Scripts\activate
python run_all.py
```

This starts the main UI and the three apps; it may also open the browser for you.

---

## Ports and apps

| Port | App | Description |
|------|-----|-------------|
| **8501** | Main UI | Hub with links to all apps |
| **8502** | Store Opening Discovery | Search for mall/store opening data, extract and analyze with AI |
| **8503** | Mall AI Dashboard | Scrape mall directories, compare data, Facebook/Instagram scrapers, AI insights |
| **8504** | Map Visual Analysis | OCR + SBERT on mall map screenshots, match tenants, show missing on map |

---

## Project structure

```
combined-dashboard/
├── main_ui.py              # Entry point: run this to open the combined dashboard
├── run_all.py              # Alternative launcher (starts main UI + all apps)
├── README.md               # This file
├── googlesearch/           # Store Opening Discovery
│   ├── app_streamlit.py
│   └── requirements.txt
├── Mall_Ai_Dashboard/       # Mall AI Dashboard
│   ├── app.py
│   └── requirements.txt
└── Map scrapping/          # Map Visual Analysis
    ├── mall_analysis_app.py
    └── requirements.txt
```

---

## Troubleshooting

- **"No module named 'easyocr'" or "No module named 'sentence_transformers'"**  
  You're not using the project venv. Activate it (step 3) and run from the project folder (step “How to run”). If you use the main UI, it uses the same Python that started `main_ui.py`, so launching via `streamlit run main_ui.py` after activating `.venv` fixes this.

- **Port already in use**  
  Stop any other Streamlit or Python processes using 8501–8504, or change the ports in `main_ui.py` / `run_all.py`.

- **Reinstall dependencies**  
  With venv activated: run the same `pip install -r ...` command from step 4 again.

---

## Quick reference

| Task | Command |
|------|---------|
| Create env | `python -m venv .venv` |
| Activate (Windows) | `.\.venv\Scripts\activate` |
| Install all deps | `pip install -r "Map scrapping\requirements.txt" -r "Mall_Ai_Dashboard\requirements.txt" -r "googlesearch\requirements.txt"` |
| Run dashboard | `streamlit run main_ui.py --server.port 8501` |
