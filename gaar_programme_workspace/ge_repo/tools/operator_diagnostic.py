#!/usr/bin/env python3
"""Read-only Gate-0 diagnostic for WB-129. Never creates or edits cycle records."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
from collections import Counter
import events
from governance.operator_experience.audit import audit_outcome, cycle_trace


def main():
    p=argparse.ArgumentParser(description='Read-only audit event grounding diagnosis; no writes')
    p.add_argument('--cycle',help='Exact cycle ID shown in the AI Auditor UI')
    a=p.parse_args()
    all_rows=events.read_all()
    chosen=a.cycle or (all_rows[-1].get('cycle_id') if all_rows else '')
    rows=cycle_trace(all_rows,chosen)
    state=events.state(chosen) if chosen else {}
    projection=audit_outcome(state,rows) if state else None
    result={'cycle_id':chosen or None,'event_count_this_cycle':len(rows),
            'all_ledger_events':len(all_rows),'kinds_this_cycle':dict(Counter(e.get('kind') for e in rows)),
            'control_ids_in_this_cycle':sorted({str(e.get('control_id')) for e in rows}),
            'evidence_bound':bool(state.get('evidence')),
            'proposals_without_preceding_bound_evidence':projection['evidence_free_proposals'] if projection else 0,
            'operator_status':projection['status'] if projection else 'CYCLE_NOT_FOUND',
            'event_chain':events.verify()}
    print(json.dumps(result,indent=2,default=str))
    if not state: return 2
    if result['proposals_without_preceding_bound_evidence']:return 3
    return 0

if __name__=='__main__':
    raise SystemExit(main())
