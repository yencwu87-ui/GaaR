from governance.watcher.agent import RegulatoryWatcherAgent
from governance.watcher.models import SourceType, WatcherAuthority, WatcherConfig
from governance.watcher.store import CursorStore, EmissionStore, HealthStore
from governance.autopilot.monitor import ChangeMonitor, TriggerStore
from governance.autopilot.scheduler import AutopilotScheduler
from governance.autopilot.policy import AutopilotPolicy


def test_watcher_requires_document_approval_before_autopilot_queue(tmp_path):
    """WB-131 hardens the previous direct Watcher -> trigger integration."""
    monitor=ChangeMonitor(TriggerStore(tmp_path/'triggers.jsonl'))
    a=RegulatoryWatcherAgent(cursor_store=CursorStore(tmp_path/'c.jsonl'),emission_store=EmissionStore(tmp_path/'e.jsonl'),health_store=HealthStore(tmp_path/'h.jsonl'),change_monitor=monitor)
    cfg=WatcherConfig('mas-feed',SourceType.REGULATION,WatcherAuthority.BINDING,'Singapore',
      {'type':'static','items':[{'id':'1','title':'Model risk update','content':'governance model change','last_modified':'1',
      'materiality':.95,'classification_confidence':.99,
      'requirements':[{'control_id':'M3.6','requirement_text':'new governed model obligation'}]}]},
      filters={'framework':'MAS','keywords':['model','governance']})
    r=a.run_source(cfg)
    assert r.emitted==0
    assert a.emission_store.read()[0]['payload']['emission_status']=='REVIEW_CANDIDATE'
    assert len(monitor.store.read())==0
    policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=2)
    sched=AutopilotScheduler(policy=policy,path=tmp_path/'jobs.jsonl')
    assert sched.claim()==[]


def test_background_feed_cannot_self_feed_autopilot(tmp_path):
    monitor=ChangeMonitor(TriggerStore(tmp_path/'triggers.jsonl'))
    a=RegulatoryWatcherAgent(cursor_store=CursorStore(tmp_path/'c.jsonl'),emission_store=EmissionStore(tmp_path/'e.jsonl'),health_store=HealthStore(tmp_path/'h.jsonl'),change_monitor=monitor)
    cfg=WatcherConfig('blog',SourceType.BACKGROUND,WatcherAuthority.BACKGROUND,'GLOBAL',{'type':'static','items':[{'id':'1','title':'AI blog','content':'must shall mandatory','last_modified':'1','materiality':1.0,'classification_confidence':1.0,'requirements':[{'control_id':'M3.6','requirement_text':'blog idea'}]}]},filters={'framework':'MAS'})
    assert a.run_source(cfg).emitted==0
    assert monitor.store.read()==[]
