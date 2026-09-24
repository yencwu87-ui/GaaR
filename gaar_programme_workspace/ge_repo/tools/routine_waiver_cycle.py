#!/usr/bin/env python3
"""Read-only eligibility, or explicitly apply signed routine waiver to an existing cycle."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import events
from governance.routine_waiver import eligibility, approved_policy, applied_waiver, apply, WaiverDenied

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cycle',required=True)
    p.add_argument('--apply',action='store_true',help='Write one waiver event after all checks')
    a=p.parse_args()
    s=events.state(a.cycle)
    if not s:p.error('cycle not found')
    issues=eligibility(s)
    try:policy=approved_policy()
    except (WaiverDenied,RuntimeError) as exc:
        policy=None;issues=['policy:'+str(exc)]+issues
    out={'cycle_id':a.cycle,'control_id':s['control_id'],
         'policy_version':policy['schema'] if policy else None,
         'previously_applied':bool(applied_waiver(s)) if policy else False,
         'eligible':not issues,'blockers':issues,'write_requested':a.apply}
    if not issues and a.apply:
        event=apply(a.cycle)
        out['event_id']=event['event_id'];out['recorded']=True
    else:out['recorded']=False
    print(json.dumps(out,indent=2,default=str))
    return 0 if not issues else 2
if __name__=='__main__':raise SystemExit(main())
