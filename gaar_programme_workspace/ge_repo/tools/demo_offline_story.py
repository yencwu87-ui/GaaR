#!/usr/bin/env python3
"""Deterministic offline product-story probe.

This demo exercises the self-feeding front of the GaaR pipeline without external services:
Watcher -> governed change trigger -> Autopilot queue -> status. It intentionally stops before
human-governed decision nodes; the live Streamlit/Ollama demo continues from there.
"""
from __future__ import annotations
import json,tempfile,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.watcher import RegulatoryWatcherAgent,CursorStore,EmissionStore,HealthStore
from governance.watcher.models import WatcherConfig,SourceType,WatcherAuthority
from governance.autopilot.monitor import ChangeMonitor,TriggerStore,AutopilotTrigger,TriggerType
from governance.autopilot.scheduler import AutopilotScheduler
from governance.autopilot.policy import AutopilotPolicy

def main():
    with tempfile.TemporaryDirectory(prefix='gaar-demo-') as td:
        p=Path(td); monitor=ChangeMonitor(TriggerStore(p/'triggers.jsonl'))
        watcher=RegulatoryWatcherAgent(cursor_store=CursorStore(p/'cursors.jsonl'),emission_store=EmissionStore(p/'emissions.jsonl'),health_store=HealthStore(p/'health.jsonl'),change_monitor=monitor)
        cfg=WatcherConfig('demo-authoritative-source',SourceType.REGULATION,WatcherAuthority.BINDING,'Singapore',{'type':'static','items':[{
            'id':'rule-v2','title':'Demonstration regulatory change','content':'Updated model governance approval must be reviewed before deployment','last_modified':'2026-09-19T12:00:00Z','materiality':.95,'classification_confidence':.99,
            'requirements':[{'control_id':'M3.6','requirement_text':'Approval and review before deployment','section':'4.2'}]}]},filters={'framework':'MAS','keywords':['model','governance','approval']})
        wr=watcher.run_source(cfg); row=monitor.store.read()[0]['trigger']
        trig=AutopilotTrigger(row['trigger_id'],TriggerType(row['trigger_type']),row['control_id'],row['framework'],row['detected_at'],row['reason'],row['material'],row['source_id'],row['change_id'],row['payload_hash'],row['metadata'])
        sched=AutopilotScheduler(p/'jobs.jsonl',policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=2)); job=sched.enqueue(trig); claimed=sched.claim()[0]
        print(json.dumps({
            'story':'SOURCE -> WATCHER -> GOVERNANCE CHANGE TRIGGER -> AUTOPILOT QUEUE',
            'watcher':wr.__dict__, 'trigger':row, 'job':claimed.to_dict() if hasattr(claimed,'to_dict') else claimed.__dict__,
            'status':sched.status(), 'authority_boundary':'No human read, decision, CURRENT or SUPERSEDED was fabricated.'
        },indent=2,default=str))
if __name__=='__main__': main()
