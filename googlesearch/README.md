# Retail Store Opening Discovery Pipeline

Identifies publicly available information about **upcoming retail store openings in malls** using automated web search (Selenium), web scraping (Requests + BeautifulSoup), and **Gemini AI** for analysis. Outputs structured data (Mall, Brand, Expected Opening, Location, Confidence) and exports to **CSV/Excel**.

## Pipeline Overview

1. **Query generation** — e.g. "Coming soon store + Mall Name", "New store opening + Brand Name"
2. **Selenium web search** (primary) — collect result links
3. **Requests** — download each page HTML
4. **BeautifulSoup** — extract and clean readable text
5. **Gemini API** — detect store-opening content and extract structured details
6. **Output** — extracted text files, CSV, Excel, and optional Streamlit dashboard

## Setup

1. **Python 3.8+**

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Chrome** — installed for Selenium (ChromeDriver is auto-managed via `webdriver-manager`).

4. **Gemini API key** — default key is in `config.py` for local use. For production, set:
   ```bash
   set GEMINI_API_KEY=your_key
   ```

## Usage

### Full pipeline (recommended)

Runs search → extract text → Gemini analysis → CSV/Excel export and saves extracted text to `extracted_output/`:

```bash
# Single custom query (e.g. from CMD)
python pipeline.py "Coming soon store Midland Park Mall"

# Or: mall name + brand name
python pipeline.py "Phoenix Mall" "Zara"
```

Output:

- **extracted_output/** — one `.txt` file per fetched page (cleaned text)
- **structured_output/store_openings.csv** — structured store-opening records
- **structured_output/store_openings.xlsx** — same data in Excel

### Search + extract text only (no AI)

```bash
python selenium_search.py "Coming soon store mall" 5
```

Saves cleaned text to `extracted_output/` and prints to console. No Gemini, no CSV/Excel.

### Live dashboard (Streamlit)

```bash
streamlit run app_streamlit.py
```

Enter mall name, brand name, or a custom query and click **Run pipeline**. View and download results in the browser.

## Configuration (`config.py`)

| Setting | Purpose |
|--------|----------|
| `GEMINI_API_KEY` | Gemini API key (or set env `GEMINI_API_KEY`) |
| `GEMINI_MODEL` | Model name (e.g. `gemini-1.5-flash`) |
| `CHROME_HEADLESS` | Run Chrome without visible window |
| `EXTRACTED_OUTPUT_DIR` | Folder for extracted text files |
| `STRUCTURED_OUTPUT_DIR` | Folder for CSV/Excel |

## Example structured output

| Mall        | Brand | Expected Opening | Location Context   | Confidence |
|------------|-------|-------------------|--------------------|------------|
| Phoenix Mall | Zara  | March 2026        | Level 2 near H&M   | High       |

## Chrome automation banner

Selenium is configured so Chrome **does not show** "Chrome is being controlled by automated test software" (see `selenium_search.get_chrome_options()`).

## Technology stack

- **Selenium** — web search and automation  
- **Requests + BeautifulSoup** — page fetch and text extraction  
- **Gemini API** (`google-generativeai`) — content analysis and structured extraction  
- **Streamlit** — optional live dashboard  
- **openpyxl** — Excel export  
