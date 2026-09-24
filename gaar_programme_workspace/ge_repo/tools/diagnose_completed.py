#!/usr/bin/env python3
"""Why is Completed 0? Distinguishes 'nothing decided' from 'decided but not counted'.

Run from the project root:  python3 tools/diagnose_completed.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import events

states = list(events.iter_states())
decided = events.decided()
import collections
stages = collections.Counter(s.get("stage") for s in states)

print(f"cycles in ledger        : {len(states)}")
print(f"stages                  : {dict(stages)}")
print(f"decided events          : {len(decided)}")
print()
if not decided:
    print("VERDICT: Completed 0 is CORRECT. No `decided` event exists in the ledger.")
    print("A control is Complete only when a decision is recorded — recording a reading,")
    print("running the assessor and reviewing the comparison all leave it at 'Record decision'.")
    print()
    print("If you believe you recorded a decision, the write failed. Check for an error at the")
    print("moment you clicked Record decision, and re-run with the decision step visible.")
else:
    print("VERDICT: decisions EXIST in the ledger, so Completed 0 is a display defect.")
    for d in decided[:5]:
        print(f"   {d.get('control_id')} · cycle {d.get('cycle_id')} · {d.get('stage')}")
    print()
    print("Next: confirm those control ids are in the current scope filter — a decided control")
    print("outside the filtered 85 would not raise the counter.")
