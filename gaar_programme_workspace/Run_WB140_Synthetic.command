#!/bin/bash
set -euo pipefail
trap 'task_status=$?; if [ "$task_status" -ne 0 ]; then echo "Setup or demo failed. See the error above. No successful result is claimed."; if [ -t 0 ]; then read -r -p "Press Enter to close." ignored_error_input; fi; fi' EXIT
cd "$(dirname "$0")/ge_repo"
if [ ! -x .venv/bin/python ]; then
  echo "Creating the project Python environment..."
  python3 -m venv .venv
fi
task_python=.venv/bin/python
if ! "$task_python" -c 'import pydantic, cryptography; assert pydantic.__version__.split(".")[0] == "2"; assert 43 <= int(cryptography.__version__.split(".")[0]) < 50' >/dev/null 2>&1; then
  echo "Installing the demo dependencies into the project environment (internet required for setup)..."
  "$task_python" -m pip install -r requirements-wb140-demo.txt
fi
export WB_WEB_KNOWLEDGE=off
"$task_python" tools/wb140_demo.py
echo "Synthetic investigation finished. Read the printed result and artifact directory."
if [ -t 0 ]; then
  read -r -p "Press Enter to close." ignored_input
fi
