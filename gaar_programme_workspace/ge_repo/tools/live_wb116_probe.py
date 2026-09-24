#!/usr/bin/env python3
"""Read-only/safe WB-116 quality-gate probe.

It never creates a human decision or changes result validity. With --evaluate it evaluates a
sealed result against its already-recorded cycle and prints FINALIZABLE/BLOCKED; it does not
append the gate or transition CURRENT.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

import events
from governance.result_store import ResultStore
from governance.result_contract import ResultStateLog
from governance.quality_gate import QualityGateLog, evaluate


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--result-id", default="")
    ap.add_argument("--cycle-id", default="")
    ap.add_argument("--evaluate", action="store_true")
    args=ap.parse_args()
    store=ResultStore(); states=ResultStateLog(); gates=QualityGateLog()
    results=store.read()
    result=store.get(args.result_id) if args.result_id else (results[-1] if results else None)
    print(json.dumps({"event_chain":events.verify(),"results":len(results),"quality_gate_records":len(gates.read())}, indent=2, default=str))
    if not result:
        print("No sealed GovernanceResult found.", file=sys.stderr); return 2
    cycle_id=args.cycle_id
    if not cycle_id:
        for row in reversed(events.decided()):
            if str(row.get("governance_result_id") or "") == result.result_id:
                cycle_id=str(row.get("cycle_id") or ""); break
    latest=gates.latest_for_result(result.result_id)
    print(json.dumps({"result_id":result.result_id,"current_state":getattr(states.current_state(result.result_id),"value",None),
                      "latest_gate":latest.model_dump(mode="json") if latest else None,"cycle_id":cycle_id}, indent=2, default=str))
    if args.evaluate:
        if not cycle_id:
            print("No source cycle found for result.", file=sys.stderr); return 3
        out=evaluate(cycle_id=cycle_id,result=result)
        print(json.dumps({"dry_run_gate":out.model_dump(mode="json")}, indent=2, default=str))
    return 0

if __name__ == "__main__": raise SystemExit(main())
