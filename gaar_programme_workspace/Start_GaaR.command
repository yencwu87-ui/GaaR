#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/ge_repo"
trap 'task_status=$?; if [ "$task_status" -ne 0 ]; then echo "Startup stopped. Read the error above; no successful run is claimed."; if [ -t 0 ]; then read -r -p "Press Enter to close." ignored_input; fi; fi' EXIT
if [ ! -x .venv/bin/python ]; then
  echo "First use: creating an isolated Python environment..."
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'from pydantic import field_validator; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import yaml' >/dev/null 2>&1; then
  echo "Installing the required software libraries (internet needed on first setup)..."
  .venv/bin/python -m pip install -r requirements-wb141.txt
fi
exec .venv/bin/python tools/gaar_console.py "$@"
