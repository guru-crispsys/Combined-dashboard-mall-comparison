#!/usr/bin/env bash
# Railway: Store Opening Discovery (googlesearch). Use this as the start command for that service.
set -e
cd "$(dirname "$0")"
exec python -m streamlit run googlesearch/app_streamlit.py \
  --server.port "${PORT:-8502}" \
  --server.address 0.0.0.0 \
  --server.headless true
