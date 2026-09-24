#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.autopilot import ChangeMonitor, TriggerType, AutopilotScheduler, load_policy

def main():
    ap=argparse.ArgumentParser(description='Create a governed autopilot trigger without making a governance decision.')
    ap.add_argument('--control',required=True); ap.add_argument('--framework',required=True)
    ap.add_argument('--reason',default='manual_review'); ap.add_argument('--material',action='store_true')
    args=ap.parse_args(); mon=ChangeMonitor(); trig=mon.emit(trigger_type=TriggerType.MANUAL,control_id=args.control,
        framework=args.framework,reason=args.reason,material=args.material,payload={'reason':args.reason})
    if trig is None:
        print('deduplicated: identical trigger already recorded'); return
    job=AutopilotScheduler(policy=load_policy()).enqueue(trig)
    print(json.dumps({'trigger':trig.to_dict(),'job':job.to_dict()},indent=2,default=str))
if __name__=='__main__': main()
