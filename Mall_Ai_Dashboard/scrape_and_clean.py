from scraper import scrape_url
from cleaner import clean_raw_text
import pandas as pd


def scrape_and_prepare(url: str, source: str = "Official Website"):
    """Scrape `url` and return a cleaned pandas DataFrame (no files written to disk).

    This keeps the flow unchanged externally but returns in-memory cleaned results.
    """
    if not url:
        raise ValueError("url is required for scraping")

    # Scrape in-memory (do not write files) - reduced initial wait for faster startup
    try:
        shops, labeled_text = scrape_url(url, write_files=False, wait_seconds=1.0)  # Reduced from 3.0 to 1.0
    except Exception as scrape_err:
        raise Exception(f"Failed to scrape URL {url}: {str(scrape_err)}") from scrape_err

    # Clean the labeled text in-memory and return DataFrame
    try:
        df = clean_raw_text(labeled_text)
    except Exception as clean_err:
        # Log the error but still return empty DataFrame rather than failing completely
        print(f"Warning: Failed to clean scraped text from {url}: {str(clean_err)}")
        df = pd.DataFrame(columns=["shop_name", "phone", "floor"])
    
    # Add source column if DataFrame is not empty
    if not df.empty:
        df['source'] = source
    else:
        # Create empty DataFrame with source column
        df = pd.DataFrame(columns=["shop_name", "phone", "floor", "source"])
        df['source'] = None

    return df
