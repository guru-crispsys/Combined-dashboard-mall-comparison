# 🏬 Mall Occupancy AI Dashboard

A comprehensive web application for scraping mall directories from both websites and Facebook pages, cleaning shop data, comparing occupancy changes over time, and generating AI-powered insights with separate reports for Facebook, Website, and Overall data.

## Overview

This dashboard helps track mall occupancy trends by:
- Scraping shop information from mall websites and Facebook pages
- Cleaning and normalizing scraped data
- Comparing old vs. new shop data to identify changes
- Generating AI-powered analytics with separate reports for each data source

## Features

- **🔍 Web Scraping**: Automatically extracts shop information (name, phone, floor) from mall websites using Selenium
- **📘 Facebook Scraping**: Extracts shop information from Facebook page posts and directories
- **🔗 Multi-Source Support**: Supports scraping from both website URLs and Facebook page URLs simultaneously
- **🧹 Data Cleaning**: Removes duplicates, normalizes floor names, filters invalid entries (emails, phone numbers mislabeled as shop names)
- **📊 Comparison Analysis**: Compares old and new shop data to identify:
  - New shops added
  - Vacated/closed shops
  - Shops that shifted floors
  - Shops still existing
- **🤖 AI Insights with Multi-Report Generation**: Uses Ollama LLM to generate THREE separate reports:
  - **Facebook Report**: Analysis based on Facebook scraped data only
  - **Website Report**: Analysis based on Website scraped data only
  - **Overall Report**: Combined analysis of both Facebook and Website data
  - Each report includes:
    - Occupancy trends (increase/decrease)
    - New shops summary
    - Vacancy/closure analysis
    - Business insights
- **📥 Data Export**: Download cleaned CSV files and AI-generated Excel reports (with all three reports)
- **🌐 Batch Processing**: Scrape multiple mall URLs from uploaded CSV/XLSX files (supports mixed website and Facebook URLs)

## Installation

### Prerequisites

- Python 3.10 or higher
- Chrome browser installed (for Selenium webdriver)
- Ollama installed and running locally (for AI analysis)

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd mall_ai_dashboard
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   ```

3. **Activate the virtual environment**:
   
   On Windows:
   ```bash
   venv\Scripts\activate
   ```
   
   On macOS/Linux:
   ```bash
   source venv/bin/activate
   ```

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Install and start Ollama**:
   - Download Ollama from [https://ollama.ai](https://ollama.ai)
   - Start the Ollama service
   - Pull the required model:
     ```bash
     ollama pull qwen2.5:1.5b
     ```

## Usage

### Running the Dashboard

Start the Streamlit application:

```bash
streamlit run app.py
```

The dashboard will open in your default web browser. The default port is configured in `.streamlit/config.toml` (default: 8502). You can change the port by editing the config file or using:

```bash
streamlit run app.py --server.port 8503
```

### Workflow

1. **Upload OLD Data**: Upload a cleaned CSV file containing previous mall shop data
2. **Provide Mall URL(s)**: 
   - Enter mall website URLs and/or Facebook page URLs in the text area (separated by commas or new lines)
   - OR upload a CSV/XLSX file with multiple URLs (supports both website and Facebook URLs in any column)
3. **Scrape & Analyze**:
   - Click "🔎 Scrape & Use as NEW" to scrape URLs from the text area
   - Click "🗂️ Scrape links file & Analyze" to process multiple URLs from uploaded file
4. **View Results**: See comparison metrics and structured data grouped by source (Facebook, Website)
5. **Generate AI Report**: Click "🤖 Generate AI Report" to get LLM-powered insights
   - You'll receive THREE separate reports: Facebook Report, Website Report, and Overall Report
6. **Download**: Export cleaned CSV files and AI reports as Excel (includes all three reports)

### Expected CSV Format

**OLD/NEW CSV files should have the following columns:**
- `shop_name`: Name of the shop
- `phone`: Contact phone number (optional, use "-" for missing)
- `floor`: Floor location (e.g., "Ground Floor", "First Floor", etc.)

**Links File CSV/XLSX format:**
- Can have columns named `website`, `facebook`, or any other name
- URLs are automatically detected and categorized by domain (facebook.com URLs vs others)
- Supports mixed formats (Facebook URLs can be in any column)

### Command Line Usage

#### Scrape a single mall URL:
```bash
python scraper.py --url "https://example-mall.com/directory" --csv output.csv --txt output.txt
```

#### Clean raw data files:
```bash
python cleaner.py
```

Note: The `data/clean.py` file exists but is not actively used in the current implementation. Use `cleaner.py` instead.

## Project Structure

```
mall_ai_dashboard/
│
├── app.py                    # Main Streamlit dashboard application
├── scraper.py                # Web scraping functionality using Selenium
├── cleaner.py                # Data cleaning utilities (in-memory processing)
├── scrape_and_clean.py       # Combined scraping and cleaning workflow
├── data_processor.py         # Comparison logic for old vs new shop data (with source separation)
├── llm_engine.py             # Ollama LLM integration for AI analysis (generates 3 reports)
├── facebook_scraper.py       # Facebook page scraping functionality
├── requirements.txt          # Python dependencies
├── .streamlit/
│   └── config.toml           # Streamlit configuration (port settings)
│
└── data/
    └── clean.py              # Legacy data cleaning module (not actively used)
```

## Components

### `app.py`
Main Streamlit dashboard that provides the web interface for:
- File uploads (OLD CSV, links file with URLs)
- URL input (supports both website and Facebook URLs)
- Scraping controls (single URL or batch processing)
- Results visualization (grouped by source)
- AI report generation (displays 3 separate reports)
- Data downloads (CSV and Excel exports)

### `scraper.py`
Handles web scraping using Selenium:
- Renders JavaScript-heavy pages
- Extracts shop information (name, phone, floor)
- Supports headless mode
- Returns structured data or writes to files

### `facebook_scraper.py`
Handles Facebook page scraping:
- Logs into Facebook using cookies (saves cookies for future sessions)
- Scrolls and extracts posts from Facebook pages
- Extracts shop information from Facebook page content
- Returns structured DataFrame with source marking

### `cleaner.py`
Data cleaning and normalization (in-memory processing):
- Removes duplicates
- Normalizes floor names (Ground Floor, First Floor, etc.)
- Filters invalid entries (emails, URLs, phone numbers in name fields)
- Normalizes phone numbers and shop names
- Used by `scrape_and_clean.py` for automatic cleaning

### `data_processor.py`
Comparison engine that:
- Identifies new shops
- Finds vacated shops
- Detects floor shifts
- Calculates occupancy statistics
- **Separates data by source** (Facebook vs Website) when `preserve_source=True`
- Creates `by_source` structure for multi-report generation

### `llm_engine.py`
Ollama LLM integration:
- Sends structured data to local Ollama instance
- Detects source-specific data (`by_source` structure)
- Generates THREE separate reports when source data is available:
  - Facebook Report (from Facebook Page data)
  - Website Report (from Website Data)
  - Overall Report (combined data)
- Parses JSON responses with robust error handling
- Ensures all three reports are always generated when source data exists

### `scrape_and_clean.py`
Orchestrates the complete workflow:
- Scrapes URLs in-memory
- Cleans data automatically
- Adds source column to track data origin
- Returns pandas DataFrame ready for comparison

## Configuration

### Port Configuration

Edit `.streamlit/config.toml` to change the default port:

```toml
[server]
port = 8502
```

Or specify port when running:
```bash
streamlit run app.py --server.port 8503
```

### LLM Settings

Edit `llm_engine.py` to customize:
- `OLLAMA_URL`: Default is `http://localhost:11434/api/generate`
- `OLLAMA_MODEL`: Default is `qwen2.5:1.5b`
- `num_predict`: Token limit for LLM responses (default: 800 for 3 reports)

### Scraping Settings

Edit `scraper.py` to adjust:
- `HEADLESS`: Set environment variable `HEADLESS=0` to see browser window
- `wait_seconds`: Time to wait for page load (default: 3.0)

Edit `facebook_scraper.py` for Facebook scraping:
- `target_count`: Number of posts to extract (default: 30)
- Cookie persistence for Facebook login sessions

### Git & data files

Generated data and reports (CSV/JSON/XLSX) are ignored via `.gitignore` so that large or sensitive mall data is not committed. If you need to version-control specific sample datasets, place them in a dedicated folder and adjust `.gitignore` accordingly.

## Dependencies

- `streamlit` - Web dashboard framework
- `pandas` - Data manipulation and analysis
- `selenium` - Web browser automation
- `webdriver-manager` - Automatic ChromeDriver management
- `beautifulsoup4` - HTML parsing
- `lxml` - XML/HTML parser backend
- `requests` - HTTP library for LLM API calls
- `openpyxl` - Excel file support
- `python-dotenv` - Environment variable management

## Troubleshooting

### Ollama Connection Error
- Ensure Ollama is running: `ollama serve`
- Verify the model is installed: `ollama list`
- Check `OLLAMA_URL` in `llm_engine.py` matches your Ollama configuration

### Facebook Scraping Issues
- Facebook may require login - cookies are saved in `fb_cookies.pkl`
- If login fails, delete `fb_cookies.pkl` and try again
- Facebook may show CAPTCHA - the scraper will attempt to handle it
- Some Facebook pages may have privacy restrictions

### ChromeDriver Issues
- The application uses `webdriver-manager` to automatically handle ChromeDriver
- Ensure Chrome browser is installed and up to date
- If issues persist, manually download ChromeDriver and specify the path

### No Shops Found During Scraping
- Check if the website uses JavaScript to load content (should be handled automatically)
- Verify the URL is accessible
- Inspect `debug_rendered.html` if generated for manual review
- Some websites may have anti-scraping measures

### LLM Returns Single Report Instead of Three
- Ensure you've scraped data from both Facebook and Website sources
- Check that the `source` column is preserved in the data
- Verify `compare_shops()` is called with `preserve_source=True`
- Check LLM response parsing in `llm_engine.py` - it should handle the 3-report structure

### Memory Issues with Large Datasets
- The application processes data in-memory for faster performance
- For very large datasets (>10,000 shops), consider processing in batches

## License

[Specify your license here]

## Contributing

[Add contribution guidelines if applicable]

## Author

[Add your name/information here]
