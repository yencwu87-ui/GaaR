#!/usr/bin/env python3
"""Control impact and root cause: what a lapse flags downstream, and where its cause probably sits.

    python tools/gaar_impact.py --lapse MAS:M2.2 --weak MAS:M3.6 --effective MAS:M3.1     what-if
    python tools/gaar_impact.py --from-ledger                                              the workbench's decisions
    python tools/gaar_impact.py --pilot ~/gaar-recurring-demo/operations.json             the pilot series, with findings
    add --dot impact.dot to write a Graphviz picture (dot -Tpng impact.dot -o impact.png)

Flags are leads, never verdicts: nothing here changes a control's recorded status.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.impact import ImpactGraph, statuses_from_ledger, statuses_from_pilot  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lapse", action="append", default=[], help="FRAMEWORK:CONTROL that has lapsed")
    p.add_argument("--weak", action="append", default=[], help="FRAMEWORK:CONTROL that is partially effective")
    p.add_argument("--effective", action="append", default=[], help="FRAMEWORK:CONTROL known to be effective")
    p.add_argument("--from-ledger", action="store_true")
    p.add_argument("--pilot", help="a pilot series operations.json")
    p.add_argument("--dot", help="write Graphviz source here")
    args = p.parse_args()
    statuses, findings = {}, {}
    if args.from_ledger:
        statuses.update(statuses_from_ledger())
    if args.pilot:
        from governance.operations.runtime import load
        config, root = load(Path(args.pilot).expanduser())
        s, f = statuses_from_pilot(config, root)
        statuses.update(s)
        findings.update(f)
    statuses.update({c: "none" for c in args.lapse})
    statuses.update({c: "partial" for c in args.weak})
    statuses.update({c: "full" for c in args.effective})
    graph = ImpactGraph()
    result = graph.analyse(statuses, findings)
    if args.dot:
        Path(args.dot).write_text(graph.dot(statuses))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
