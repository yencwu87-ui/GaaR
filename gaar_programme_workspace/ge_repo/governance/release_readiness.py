from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
from typing import Callable
import os

from governance.result_store import ResultStore
from governance.result_contract import ResultStateLog
from governance.quality_gate import QualityGateLog
from governance.autopilot import TriggerStore, AutopilotScheduler, load_policy as load_autopilot_policy
from governance.watcher import CursorStore,EmissionStore,HealthStore,load_sources
from governance.evidence_scout import ScoutStore

@dataclass(frozen=True)
class ReadinessCheck:
    name:str; passed:bool; detail:str; severity:str="ERROR"

@dataclass(frozen=True)
class ReleaseReadiness:
    ready:bool; checks:tuple[ReadinessCheck,...]
    def to_dict(self): return {"ready":self.ready,"checks":[asdict(x) for x in self.checks]}

def _safe(name,fn:Callable[[],str],severity='ERROR'):
    try: return ReadinessCheck(name,True,fn() or 'OK',severity)
    except Exception as e: return ReadinessCheck(name,False,f'{type(e).__name__}: {e}',severity)

def evaluate_release_readiness()->ReleaseReadiness:
    checks=[]
    checks.append(_safe('result_store_chain',lambda:f'{len(ResultStore().read())} result(s)'))
    checks.append(_safe('state_event_chain',lambda:f'{len(ResultStateLog().read())} event(s)'))
    checks.append(_safe('quality_gate_chain',lambda:f'{len(QualityGateLog().read())} gate record(s)'))
    checks.append(_safe('autopilot_trigger_chain',lambda:f'{len(TriggerStore().read())} trigger(s)'))
    checks.append(_safe('autopilot_job_projection',lambda:f"queue={AutopilotScheduler(policy=load_autopilot_policy()).status()['queue_depth']}"))
    checks.append(_safe('watcher_emission_chain',lambda:f'{len(EmissionStore().read())} emission(s)'))
    checks.append(_safe('watcher_cursor_chain',lambda:f'{len(CursorStore().store.read())} cursor record(s)'))
    checks.append(_safe('watcher_health_chain',lambda:f'{len(HealthStore().store.read())} health record(s)'))
    checks.append(_safe('evidence_scout_chain',lambda:f'{len(ScoutStore().read())} scout run(s)'))
    checks.append(_safe('watcher_config',lambda:f'{len(load_sources())} enabled source(s)',severity='WARN'))
    # Production safety checks: binding on localhost by default and authentication when exposed externally.
    host=os.environ.get('WB_GAAR_API_HOST','127.0.0.1')
    api_key=bool(os.environ.get('WB_GAAR_API_KEY','').strip())
    public=host not in {'127.0.0.1','localhost','::1'}
    checks.append(ReadinessCheck('api_safe_bind',not public or api_key,
        'localhost-only' if not public else ('public bind protected by API key' if api_key else 'public bind requires WB_GAAR_API_KEY')))
    failed=[x for x in checks if not x.passed and x.severity=='ERROR']
    return ReleaseReadiness(not failed,tuple(checks))
