#!/usr/bin/env bash
# Railway: Map Visual Analysis. Use this as the start command for that service.
set -e
cd "$(dirname "$0")"
exec python -m streamlit run "Map scrapping/mall_analysis_app.py" \
  --server.port "${PORT:-8504}" \
  --server.address 0.0.0.0 \
  --server.headless true
