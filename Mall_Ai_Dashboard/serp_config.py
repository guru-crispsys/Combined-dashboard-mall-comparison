"""
SERP API configuration for Mall AI Dashboard.
Used to fetch latest news and blog results for mall name + address.
"""
import os

# SerpApi key: use env SERP_API_KEY or this default (replace with your key if needed)
SERP_API_KEY = os.getenv("SERP_API_KEY", "6c2cc7f0e07e0b4d65b6a01a82190763d5d0378494a3e607eeb49e5f15091a06").strip()
