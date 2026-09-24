#!/usr/bin/env python3
"""Print the ledger-derived golden-path maturity board; performs no writes."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.maturity import evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", default="M3.6")
    parser.add_argument("--framework", default="MAS")
    args = parser.parse_args()
    result = evaluate(args.control, args.framework)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "FULLY_PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
