#!/usr/bin/env python3
"""Requirement basis: the instrument passages that most likely back each control, quoted verbatim.

    python tools/gaar_basis.py summary
    python tools/gaar_basis.py show --framework MAS --control M3.6
    python tools/gaar_basis.py report > basis.json
    python tools/gaar_basis.py tier1                                 the pilot's controls: confirm these first
    python tools/gaar_basis.py confirm --framework MAS --control M3.12 --candidate 1 --decision CONFIRMED --by "Name"

A decision covers one control and is recorded on its own (there is no bulk accept). Decisions: CONFIRMED, REJECTED,
NO_BASIS_IN_INSTRUMENT.

A proposed basis is a lead for a person to confirm, never an anchor on its own.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance import basis  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("summary"); sub.add_parser("report")
    s = sub.add_parser("show"); s.add_argument("--framework", required=True); s.add_argument("--control", required=True)
    sub.add_parser("tier1")
    c = sub.add_parser("confirm")
    c.add_argument("--framework", required=True); c.add_argument("--control", required=True)
    c.add_argument("--candidate", type=int, default=1); c.add_argument("--decision", required=True, choices=basis.DECISIONS)
    c.add_argument("--by", required=True); c.add_argument("--note", default="")
    a = p.parse_args()
    if a.command == "confirm":
        print(json.dumps(basis.confirm(a.framework, a.control, a.candidate, a.decision, a.by, a.note), indent=2))
        return
    r = basis.report()
    if a.command == "tier1":
        print(json.dumps({"tier1": r["tier1"], "controls": [c for c in r["controls"] if c["tier"] == 1]}, indent=2))
        return
    if a.command == "summary":
        print(json.dumps({"summary": r["summary"], "meaning": r["meaning"]}, indent=2))
    elif a.command == "report":
        print(json.dumps(r, indent=2))
    else:
        hit = [c for c in r["controls"] if c["framework"] == a.framework and c["control_id"] == a.control]
        if not hit:
            raise SystemExit(f"no control {a.framework} {a.control}")
        print(json.dumps(hit[0], indent=2))


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
