#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/ge_repo"
PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Creating the project Python environment..."
  python3 -m venv .venv
fi
if ! "$PYTHON" -c "from pydantic import field_validator; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import yaml" 2>/dev/null; then
  echo "Installing required project dependencies..."
  "$PYTHON" -m pip install -r requirements-wb141.txt
fi
CONFIG="${WB141_CONFIG:-config/wb141_operations.json}"
if [ -n "${WB141_INVESTIGATION_ID:-}" ]; then
  exec "$PYTHON" tools/gaar_operate.py --config "$CONFIG" --investigation-id "$WB141_INVESTIGATION_ID" run
else
  exec "$PYTHON" tools/gaar_operate.py --config "$CONFIG" doctor
fi
