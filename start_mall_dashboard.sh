#!/usr/bin/env bash
# Railway: Mall AI Dashboard. Use this as the start command for that service.
set -e
cd "$(dirname "$0")"
exec python -m streamlit run Mall_Ai_Dashboard/app.py \
  --server.port "${PORT:-8503}" \
  --server.address 0.0.0.0 \
  --server.headless true
