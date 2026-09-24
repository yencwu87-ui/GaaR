#!/usr/bin/env python3
"""WB-126 independent proposal challenge; read-only by default, explicit --run writes."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import events
from governance.independent_challenge import run, verify_for_decision
from governance.routine_waiver import eligibility,applied_waiver


def main() -> int:
    p=argparse.ArgumentParser(description='Inspect or execute an isolated assessor-proposal challenge on an admitted, signed-waiver cycle')
    p.add_argument('--cycle',required=True,help='Existing actual cycle ID')
    p.add_argument('--run',action='store_true',help='Call configured LLM and append challenge event; NEVER a governance decision')
    args=p.parse_args()
    s=events.state(args.cycle)
    if not s:
        p.error('cycle not found')
    if not args.run:
        result={'cycle_id':args.cycle,'read_only':True,
                'waiver_active':bool(applied_waiver(s)),
                'eligibility_before_challenge':eligibility(s),
                'independent_challenge':verify_for_decision(s),
                'has_human_decision':bool(s.get('decision')),
                'has_reviewer_read':bool(s.get('read'))}
        print(json.dumps(result,indent=2))
        return 0
    try:
        output=run(args.cycle)
    except Exception as exc:
        print(json.dumps({'status':'DENIED','reason':str(exc)},indent=2))
        return 2
    print(json.dumps({'cycle_id':args.cycle, 'status':output['validation_status'],
                      'challenges':len(output['challenges']),
                      'decision_checkpoint':verify_for_decision(events.state(args.cycle)),
                      'no_human_decision_written':not bool(events.state(args.cycle).get('decision'))},indent=2))
    return 0 if output['validation_status']=='admitted' else 2
if __name__=='__main__':raise SystemExit(main())
