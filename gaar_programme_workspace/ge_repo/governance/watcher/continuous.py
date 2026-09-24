"""WB-134 opt-in periodic polling; persists truthful per-source outcomes.

Existing Watcher RSS/JSON/static connectors index publication summaries. This module
must not claim full authoritative PDF intake, regulator-wide coverage or MAC-live.
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from .agent import RegulatoryWatcherAgent
from .policy import load_sources
from .update_centre import ScanReceipts
from .store import _lock
from .models import utcnow
from datetime import datetime, timezone, timedelta

class MonitorDisabled(RuntimeError): pass

def scan_once(*,config=None,agent=None,receipts=None,force=False):
    if not force and os.environ.get('WB_GAAR_WATCHER_SCHEDULER_ENABLED')!='1':
        raise MonitorDisabled('Scheduler is opt-in: WB_GAAR_WATCHER_SCHEDULER_ENABLED=1')
    sources=load_sources(config)
    receipts=receipts or ScanReceipts()
    agent=agent or RegulatoryWatcherAgent()
    outcomes=[]
    for source in sources:
        interval=int(source.schedule.get('interval_minutes',360 if source.source_type.value!='threat' else 60))
        if interval < 60: raise ValueError('minimum polling interval is 60 minutes')
        last=receipts.latest(source.source_id)
        if last and not force:
            try:
                stamp=datetime.fromisoformat(last['checked_at'].replace('Z','+00:00'))
                if stamp.tzinfo and datetime.now(timezone.utc)-stamp < timedelta(minutes=interval):
                    outcomes.append(dict(last, skipped_not_due=True))
                    continue
            except (KeyError,ValueError,TypeError): pass
        result=agent.run_source(source)
        latest=agent.health_store.latest(source.source_id) or {}
        errors=list(result.errors)
        if latest.get('status')!='OK':
            error='; '.join(errors) or str(latest.get('error') or 'Source validation incomplete')
            status='UNABLE_TO_CHECK'
        else:
            # Snapshot count is new, successfully persisted discovered publications.
            emission_rows=[r['payload'] for r in agent.emission_store.read()
                           if r['payload'].get('run_id')==result.run_id and r['payload'].get('source_snapshot_id')
                           and r['payload'].get('emission_status') not in ('INVALID_DOCUMENT',)]
            status='UPDATES_AVAILABLE' if emission_rows else 'UP_TO_DATE'
            error=None
        row=receipts.record(source_id=source.source_id,status=status,run_id=result.run_id,
                            discovered=len(emission_rows) if status=='UPDATES_AVAILABLE' else 0,
                            error=error,interval_minutes=interval)
        outcomes.append(row['payload'])
    return outcomes

def run_daemon(*,config=None,receipts=None,once=False,force=False,sleep=time.sleep):
    """One poll at startup; background loop controlled by per-source intervals.
    launchd KeepAlive/StartInterval is the recommended Mac deployment, so --once
    is preferred: each launch polls only sources that are due and exits.
    """
    if not force and os.environ.get('WB_GAAR_WATCHER_SCHEDULER_ENABLED')!='1':
        raise MonitorDisabled('Scheduler disabled')
    return scan_once(config=config,receipts=receipts,force=force)
