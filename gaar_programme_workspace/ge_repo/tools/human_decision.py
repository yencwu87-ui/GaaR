#!/usr/bin/env python3
"""WB-127 local human decision surface. Reviewer ID is attribution, not authenticated IAM/RBAC."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.audit_package.decision_service import preflight,approve_one,request_investigation,reject_proposal
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cycle',required=True)
p.add_argument('--reviewer',required=True)
p.add_argument('--action',choices=['preflight','approve','investigate','reject'],default='preflight')
p.add_argument('--note',default='')
a=p.parse_args()
try:
    if a.action=='preflight': out=preflight(a.cycle)
    elif a.action=='approve': out=approve_one(a.cycle,reviewer_id=a.reviewer,note=a.note or None)
    elif a.action=='investigate': out=request_investigation(a.cycle,reviewer_id=a.reviewer,note=a.note)
    else: out=reject_proposal(a.cycle,reviewer_id=a.reviewer,note=a.note)
    print(json.dumps(out,indent=2,default=str))
except Exception as exc:
    print(json.dumps({'status':'ERROR','error':type(exc).__name__,'detail':str(exc)},indent=2))
    raise SystemExit(2)
