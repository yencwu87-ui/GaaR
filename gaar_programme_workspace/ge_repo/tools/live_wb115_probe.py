#!/usr/bin/env python3
"""Safe live probe for WB-115 AI Auditor.

The probe never records a final governance decision. With --run it advances only machine-owned
nodes through ReviewConductor.run_to_checkpoint() and stops at evidence/human checkpoints.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import events
from governance.ai_auditor import ReviewConductor
from governance.ai_auditor.living_view import living_view
from governance.ai_auditor.registry import list_skills


def _latest_cycle(control_id: str, framework: str = "") -> str | None:
    rows = []
    for cid in events.cycles(control_id=control_id):
        s = events.state(cid)
        if not s:
            continue
        if framework and str(s.get("framework") or "") != framework:
            continue
        rows.append((str(s.get("updated") or ""), cid))
    rows.sort()
    return rows[-1][1] if rows else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", help="Control ID, e.g. 2.1 or M3.6")
    ap.add_argument("--framework", default="", help="Framework, e.g. SAFR, MAS, MGF Agentic")
    ap.add_argument("--cycle-id", default="")
    ap.add_argument("--run", action="store_true", help="Advance machine-owned nodes to next checkpoint")
    ap.add_argument("--reviewer", default="", help="Named reviewer for bounded Copilot presentation")
    ap.add_argument("--narrative", action="store_true", help="Generate grounded Control Narrative")
    ap.add_argument("--living", action="store_true", help="Print living result projection")
    args = ap.parse_args()

    print(json.dumps({
        "wb115": "AI Auditor runtime",
        "skills": [{"name": s.name, "may_mutate_state": s.may_mutate_state} for s in list_skills()],
        "event_chain": events.verify(),
    }, indent=2, default=str))

    if args.living and args.control:
        try:
            print(json.dumps({"living_view": living_view(args.control, args.framework or None)}, indent=2, default=str))
        except Exception as exc:
            print(json.dumps({"living_view_error": f"{type(exc).__name__}: {exc}"}, indent=2))

    cycle_id = args.cycle_id or (_latest_cycle(args.control, args.framework) if args.control else None)
    if not cycle_id:
        print("No matching live cycle. Start/bind evidence in Streamlit, then rerun this probe.", file=sys.stderr)
        return 2

    conductor = ReviewConductor()
    before = conductor.inspect(cycle_id)
    print(json.dumps({"cycle_id": cycle_id, "before": before.model_dump()}, indent=2, default=str))

    if args.run:
        after = conductor.run_to_checkpoint(cycle_id, reviewer_actor=args.reviewer or None)
        print(json.dumps({"after": after.model_dump()}, indent=2, default=str))

    if args.narrative:
        try:
            narrative = conductor.control_narrative(cycle_id)
            print(json.dumps({"control_narrative": narrative.model_dump()}, indent=2, default=str))
        except Exception as exc:
            print(json.dumps({"control_narrative_error": f"{type(exc).__name__}: {exc}"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
