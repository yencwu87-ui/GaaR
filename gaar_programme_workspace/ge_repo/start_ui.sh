#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c 'import streamlit' >/dev/null 2>&1; then
  echo "Streamlit is not installed in this Python environment."
  echo "Run: $PYTHON -m pip install -r requirements.txt"
  exit 1
fi

exec "$PYTHON" -m streamlit run app.py "$@"
