#!/usr/bin/env python3
"""WB-127 batch UX convenience. Each eligible cycle uses the same approve_one()->core.cycle.decide path."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.audit_package.decision_service import approve_batch
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--cycle',action='append',required=True,help='Repeat once per cycle')
p.add_argument('--reviewer',required=True)
p.add_argument('--note',default='')
a=p.parse_args()
try:
    print(json.dumps(approve_batch(a.cycle,reviewer_id=a.reviewer,note=a.note or None),indent=2,default=str))
except Exception as exc:
    print(json.dumps({'status':'ERROR','error':type(exc).__name__,'detail':str(exc)},indent=2));raise SystemExit(2)
