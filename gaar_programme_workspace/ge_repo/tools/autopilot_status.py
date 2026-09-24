#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.autopilot import AutopilotScheduler, TriggerStore, load_policy

def main():
    p=load_policy(); sched=AutopilotScheduler(policy=p); triggers=TriggerStore().read(); status=sched.status()
    print('GAAR CONTINUOUS GOVERNANCE AUTOPILOT')
    print(f'enabled: {status["enabled"]}')
    print(f'max_concurrent: {status["max_concurrent"]}')
    print(f'trigger_records: {len(triggers)}')
    print(f'queue_depth: {status["queue_depth"]}')
    print(f'in_flight: {status["in_flight"]}')
    print('counts: '+json.dumps(status['counts'],sort_keys=True))
    for j in sorted(status['jobs'],key=lambda x:x.updated_at,reverse=True)[:10]:
        print(f'- {j.job_id} {j.framework} {j.control_id} {j.status.value} checkpoint={j.checkpoint or "-"} outcome={j.outcome or "-"}')
if __name__=='__main__': main()
