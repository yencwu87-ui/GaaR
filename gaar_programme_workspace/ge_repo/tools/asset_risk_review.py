#!/usr/bin/env python3
"""Read-only reconciliation of scoped asset exports. Uses no LLM or network."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.risk_review import reconcile_assets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = reconcile_assets(json.loads(args.input.read_text()))
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return 0 if result["status"] == "COMPUTED_ON_SUPPLIED_EXPORTS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
