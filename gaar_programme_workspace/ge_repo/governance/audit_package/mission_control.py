"""Read-only WB-123 operational status and provenance timeline.

Health is reported as activity observed, never invented 'MONITORING' or 'ACTIVE'.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import os


def snapshot() -> dict:
    import events
    from governance.autopilot import AutopilotScheduler
    from governance.watcher.store import EmissionStore, HealthStore
    from governance.evidence_scout.refresh import AcquisitionStore
    from governance.evidence_scout.dossier import DossierStore
    root=Path(__file__).resolve().parents[1]
    paths={
        'watcher_health':Path(os.environ.get('WB_GAAR_WATCHER_HEALTH_STORE') or root/'watcher_health.jsonl'),
        'watcher_emissions':Path(os.environ.get('WB_GAAR_WATCHER_EMISSION_STORE') or root/'watcher_emissions.jsonl'),
    }
    health=HealthStore(paths['watcher_health']).store.read()
    emissions=EmissionStore(paths['watcher_emissions']).read()
    acqu=AcquisitionStore().read()
    dossiers=DossierStore().read()
    scheduler=AutopilotScheduler().status()
    cycles=list(events.iter_states())
    return {
        'ai_auditor':{'cycles':len(cycles),'awaiting_human_read':sum(bool(c.get('evidence')) and not c.get('read') for c in cycles),
                      'awaiting_human_decision':sum(bool(c.get('proposal')) and not c.get('decision') for c in cycles)},
        'autopilot':{'configured_enabled':scheduler['enabled'],'jobs':len(scheduler['jobs']),
                     'queued':scheduler['queue_depth'],'running':scheduler['in_flight']},
        'watcher':{'poll_receipts':len(health),'emissions':len(emissions),
                    'last_poll':(health[-1].get('payload') or {}).get('checked_at') if health else None,
                    'note':'Poll receipt does not prove a daemon is running'},
        'scout':{'acquisition_receipts':len(acqu),'proposed_dossiers':len(dossiers),
                 'note':'Proposals are not governed admissions'},
    }


def timeline(limit:int=30)->list[dict]:
    """Merge actual identifiable ledger events; never manufacture cross-system job IDs."""
    if limit < 1 or limit > 500: raise ValueError('limit 1..500')
    import events
    from governance.autopilot import AutopilotScheduler
    from governance.watcher.store import EmissionStore,HealthStore
    from governance.evidence_scout.refresh import AcquisitionStore
    from governance.evidence_scout.dossier import DossierStore
    out=[]
    for row in events.read_all():
        out.append({'when':row.get('ts'),'component':'AI Auditor','action':row.get('kind'),
            'reference':row.get('cycle_id'),'event_id':row.get('event_id')})
    for job in AutopilotScheduler().latest_jobs():
        out.append({'when':job.updated_at,'component':'Autopilot','action':job.status.value,
            'reference':job.job_id,'cycle_id':job.cycle_id,'trigger_id':job.trigger_id})
    for cls,name,field in ((HealthStore,'Watcher poll','run_id'),(EmissionStore,'Watcher emission','emission_id'),
                           (AcquisitionStore,'Evidence Scout','acquisition_id'),(DossierStore,'Evidence Dossier','dossier_id')):
        store=cls()
        rows=store.store.read() if isinstance(store,HealthStore) else store.read()
        for row in rows:
            p=row.get('payload') or {}
            when=p.get('checked_at') or p.get('emitted_at') or p.get('assembled_at') or p.get('timestamp')
            out.append({'when':when,'component':name,'action':row.get('record_type'),
                'reference':p.get(field) or row.get('record_hash'),'record_hash':row.get('record_hash')})
    # Missing timestamps remain visible last; never invent a time.
    return sorted(out,key=lambda x: str(x.get('when') or ''),reverse=True)[:limit]
