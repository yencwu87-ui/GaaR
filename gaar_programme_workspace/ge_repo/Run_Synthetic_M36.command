#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="python3"
if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
fi

"$PYTHON" tools/synthetic_m36_demo.py
echo
echo "Synthetic M3.6 dossier prepared. Open GaaR to review the human admission checkpoint."
echo "This demonstration does not establish production or MAS compliance."
read -r -p "Press Return to close..." _

