#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import events
from governance.autopilot import AutopilotScheduler, TriggerStore, load_policy
from governance.change_runtime import ChangeImpactStore
from governance.reassessment import ReassessmentCaseStore
from governance.result_contract import ResultStateLog
from governance.result_store import ResultStore

def main():
    print('='*72); print('G / WB-118 CONTINUOUS GOVERNANCE AUTOPILOT PROBE'); print('='*72)
    policy=load_policy(); sched=AutopilotScheduler(policy=policy)
    try: results=ResultStore().read(); result_ok=True
    except Exception as e: results=[]; result_ok=False; print('result_store_error:',type(e).__name__,e)
    try: states=ResultStateLog().read(); state_ok=True
    except Exception as e: states=[]; state_ok=False; print('state_log_error:',type(e).__name__,e)
    try: triggers=TriggerStore().read(); trigger_ok=True
    except Exception as e: triggers=[]; trigger_ok=False; print('trigger_store_error:',type(e).__name__,e)
    try: cases=ReassessmentCaseStore().read(); case_ok=True
    except Exception as e: cases=[]; case_ok=False; print('case_store_error:',type(e).__name__,e)
    try: changes=ChangeImpactStore().read(); change_ok=True
    except Exception as e: changes=[]; change_ok=False; print('change_store_error:',type(e).__name__,e)
    ev=events.verify(); st=sched.status()
    print('enabled:',policy.enabled)
    print('event_chain_intact:',ev['intact'],'events:',ev['events'],'breaks:',len(ev['breaks']))
    print('result_store_readable:',result_ok,'sealed_results:',len(results))
    print('state_log_readable:',state_ok,'state_events:',len(states))
    print('change_store_readable:',change_ok,'change_records:',len(changes))
    print('reassessment_store_readable:',case_ok,'cases:',len(cases))
    print('trigger_store_readable:',trigger_ok,'triggers:',len(triggers))
    print('queue_depth:',st['queue_depth'],'in_flight:',st['in_flight'],'max_concurrent:',st['max_concurrent'])
    print('job_counts:',json.dumps(st['counts'],sort_keys=True))
    waiting=[j for j in st['jobs'] if j.status.value=='WAITING_HUMAN']
    print('human_attention_jobs:',len(waiting))
    for j in sorted(st['jobs'],key=lambda x:x.updated_at,reverse=True)[:5]:
        print(f'job {j.job_id}: {j.status.value} control={j.framework}/{j.control_id} checkpoint={j.checkpoint or "-"} outcome={j.outcome or "-"}')
    ok=all([ev['intact'],result_ok,state_ok,trigger_ok,case_ok,change_ok])
    print('probe_integrity:', 'OK' if ok else 'FAILED')
    print('='*72)
    raise SystemExit(0 if ok else 2)
if __name__=='__main__': main()
