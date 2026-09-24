from pathlib import Path
from governance.watcher.agent import RegulatoryWatcherAgent
from governance.watcher.models import SourceType, WatcherAuthority, WatcherConfig
from governance.watcher.store import CursorStore, EmissionStore, HealthStore
from governance.autopilot.monitor import ChangeMonitor, TriggerStore


def stores(tmp_path):
    return (
        CursorStore(tmp_path/'cursor.jsonl'),
        EmissionStore(tmp_path/'emission.jsonl'),
        HealthStore(tmp_path/'health.jsonl'),
        ChangeMonitor(TriggerStore(tmp_path/'triggers.jsonl')),
    )

def cfg(authority=WatcherAuthority.BINDING, *, items=None, materiality=0.9, source_id='src'):
    items = items or [{
        'id':'d1','title':'MAS model governance update','content':'New model governance obligation','last_modified':'2026-09-19T01:00:00Z',
        'materiality':materiality,'classification_confidence':0.99,
        'requirements':[{'control_id':'M3.6','requirement_text':'Govern models before deployment','section':'4.2'}],
    }]
    return WatcherConfig(source_id,SourceType.REGULATION,authority,'Singapore',{'type':'static','items':items},filters={'framework':'MAS','keywords':['model','governance']})

def agent(tmp_path):
    c,e,h,m=stores(tmp_path); return RegulatoryWatcherAgent(cursor_store=c,emission_store=e,health_store=h,change_monitor=m),c,e,h,m

def test_authoritative_source_requires_human_review_before_trigger(tmp_path):
    a,c,e,h,m=agent(tmp_path); r=a.run_source(cfg())
    assert r.emitted==0 and r.background==0 and not r.errors
    assert len(e.read())==1
    assert len(m.store.read())==0
    assert e.read()[0]['payload']['emission_status']=='REVIEW_CANDIDATE'

def test_background_never_triggers_governance_change(tmp_path):
    a,c,e,h,m=agent(tmp_path); r=a.run_source(cfg(WatcherAuthority.BACKGROUND))
    assert r.background==1 and r.emitted==0
    assert len(m.store.read())==0
    assert e.read()[0]['payload']['emission_status']=='BACKGROUND_ONLY'

def test_below_materiality_is_recorded_but_not_triggered(tmp_path):
    a,c,e,h,m=agent(tmp_path); r=a.run_source(cfg(materiality=0.1))
    assert r.skipped==1 and r.emitted==0
    assert len(m.store.read())==0
    assert e.read()[0]['payload']['emission_status']=='BELOW_POLICY_THRESHOLD'

def test_cursor_advances_only_after_successful_run(tmp_path):
    a,c,e,h,m=agent(tmp_path); r=a.run_source(cfg())
    assert r.cursor_before is None
    assert c.get('src')=='2026-09-19T01:00:00Z'

def test_restart_uses_persisted_cursor_and_does_not_duplicate(tmp_path):
    a,c,e,h,m=agent(tmp_path); assert a.run_source(cfg()).emitted==0
    a2=RegulatoryWatcherAgent(cursor_store=c,emission_store=e,health_store=h,change_monitor=m)
    r=a2.run_source(cfg()); assert r.fetched==0 and r.emitted==0
    assert len(e.read())==1 and len(m.store.read())==0

def test_emission_store_detects_duplicate_content(tmp_path):
    a,c,e,h,m=agent(tmp_path); a.run_source(cfg())
    assert e.has_content('src',e.read()[0]['payload']['content_hash'])

def test_classification_authority_comes_from_config_not_prose(tmp_path):
    items=[{'id':'x','title':'Blog says mandatory binding regulation','content':'shall must enforcement','last_modified':'1','materiality':1.0,'classification_confidence':1.0,'requirements':[{'control_id':'M3.6','requirement_text':'x'}]}]
    a,c,e,h,m=agent(tmp_path); r=a.run_source(cfg(WatcherAuthority.BACKGROUND,items=items))
    assert r.emitted==0 and e.read()[0]['payload']['authority']=='background'

def test_no_control_mapping_means_no_emission(tmp_path):
    items=[{'id':'x','title':'Update','content':'unrelated','last_modified':'1','materiality':1.0,'classification_confidence':1.0}]
    a,c,e,h,m=agent(tmp_path); r=a.run_source(cfg(items=items))
    assert r.emitted==0 and r.skipped==1 and len(m.store.read())==0

def test_hash_chains_validate(tmp_path):
    a,c,e,h,m=agent(tmp_path); a.run_source(cfg())
    assert c.store.read() and e.store.read() and h.store.read() and not m.store.read()

def test_content_hash_change_emits_new_change(tmp_path):
    a,c,e,h,m=agent(tmp_path); a.run_source(cfg())
    items=[{'id':'d2','title':'MAS model governance update v2','content':'Revised stronger model governance obligation','last_modified':'2026-09-19T02:00:00Z','materiality':.9,'classification_confidence':.99,'requirements':[{'control_id':'M3.6','requirement_text':'Revised requirement'}]}]
    r=a.run_source(cfg(items=items)); assert r.emitted==0
    assert len(e.read())==2 and len(m.store.read())==0

def test_circuit_breaker_opens_after_failures(tmp_path):
    a,c,e,h,m=agent(tmp_path)
    bad=WatcherConfig('bad',SourceType.REGULATION,WatcherAuthority.BINDING,'SG',{'type':'unsupported'},max_consecutive_failures=2)
    assert a.run_source(bad).circuit_open is False
    assert a.run_source(bad).circuit_open is True
    third=a.run_source(bad); assert third.circuit_open is True and third.errors==('circuit breaker open',)

def test_invalid_threshold_rejected():
    c=cfg(); object.__setattr__(c,'min_confidence',1.5)
    try: c.validate(); assert False
    except ValueError: pass
