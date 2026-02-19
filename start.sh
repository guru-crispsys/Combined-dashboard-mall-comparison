#!/usr/bin/env bash
# Railway / Railpack start script: run main Streamlit UI on PORT (set by Railway).
set -e
exec python -m streamlit run main_ui.py \
  --server.port "${PORT:-8501}" \
  --server.address 0.0.0.0 \
  --server.headless true
