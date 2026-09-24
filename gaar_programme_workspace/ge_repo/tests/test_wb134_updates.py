import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from governance.watcher.update_centre import ScanReceipts, domain_suggestions
from governance.watcher.continuous import scan_once, MonitorDisabled
from governance.watcher.models import WatcherConfig,SourceType,WatcherAuthority
from governance.watcher.store import HealthStore,EmissionStore,CursorStore
import pytest

def test_domains_are_independent_and_never_obligations():
    assert 'AI and model governance' in domain_suggestions('MAS AI model governance')
    assert 'Cybersecurity and resilience' in domain_suggestions('Cyber operational risk')
    assert domain_suggestions('Completely unrelated material') == ['Unclassified — review required']

def test_status_distinctions(tmp_path):
    r=ScanReceipts(tmp_path/'scan.jsonl')
    assert r.status('s',enabled=False)['status']=='NOT_CONFIGURED'
    assert r.status('s',enabled=True)['status']=='NEVER_CHECKED'
    r.record(source_id='s',status='UP_TO_DATE',run_id='1',checked_at='2025-01-01T00:00:00+00:00')
    assert r.status('s',enabled=True,now=datetime(2026,1,1,tzinfo=timezone.utc))['status']=='CHECK_OVERDUE'
    r.record(source_id='s',status='UNABLE_TO_CHECK',run_id='2',error='DNS')
    assert r.status('s',enabled=True)['status']=='UNABLE_TO_CHECK'
    assert r.latest('s')['error']=='DNS'

def test_opt_in(monkeypatch):
    monkeypatch.delenv('WB_GAAR_WATCHER_SCHEDULER_ENABLED',raising=False)
    with pytest.raises(MonitorDisabled): scan_once()

def test_scan_records_clean_and_failed(tmp_path,monkeypatch):
    monkeypatch.setenv('WB_GAAR_WATCHER_SCHEDULER_ENABLED','1')
    from governance.watcher import continuous
    sources=(WatcherConfig('first',SourceType.BACKGROUND,WatcherAuthority.BACKGROUND,'SG',{'type':'static'},enabled=True),WatcherConfig('second',SourceType.BACKGROUND,WatcherAuthority.BACKGROUND,'SG',{'type':'static'},enabled=True))
    monkeypatch.setattr(continuous,'load_sources',lambda _ : sources)
    r=ScanReceipts(tmp_path/'scan.jsonl')
    class FakeAgent:
        def __init__(self):
            self.emission_store=SimpleNamespace(read=lambda:[])
            self.health_store=SimpleNamespace(latest=lambda key: {'status':'OK'} if key=='first' else {'status':'ERROR','error':'DNS failed'})
        def run_source(self,source):
            return SimpleNamespace(run_id=source.source_id,errors=() if source.source_id=='first' else ('DNS failed',))
    result=scan_once(agent=FakeAgent(),receipts=r)
    assert [v['status'] for v in result]==['UP_TO_DATE','UNABLE_TO_CHECK']
    assert r.latest('second')['error']=='DNS failed'

def test_change_recognized_only_with_recorded_snapshot(tmp_path,monkeypatch):
    monkeypatch.setenv('WB_GAAR_WATCHER_SCHEDULER_ENABLED','1')
    from governance.watcher import continuous
    monkeypatch.setattr(continuous,'load_sources',lambda _:(WatcherConfig('feed',SourceType.GUIDANCE,WatcherAuthority.EXPECTATION,'SG',{'type':'static'},enabled=True),))
    class FakeAgent:
        health_store=SimpleNamespace(latest=lambda _: {'status':'OK'})
        emission_store=SimpleNamespace(read=lambda:[{'payload':{'run_id':'r','source_snapshot_id':'snapshot','emission_status':'REVIEW_CANDIDATE'}}])
        def run_source(self,_):return SimpleNamespace(run_id='r',errors=())
    r=ScanReceipts(tmp_path/'receipts.jsonl')
    assert scan_once(agent=FakeAgent(),receipts=r)[0]['status']=='UPDATES_AVAILABLE'
    assert scan_once(agent=FakeAgent(),receipts=r)[0]['discovered']==1
