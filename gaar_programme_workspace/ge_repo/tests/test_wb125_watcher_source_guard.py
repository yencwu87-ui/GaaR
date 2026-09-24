from governance.watcher.models import WatcherConfig,SourceType,WatcherAuthority
from governance.watcher.connectors import HTTPJSONConnector
from governance.watcher.agent import RegulatoryWatcherAgent
from governance.watcher.store import CursorStore,EmissionStore,HealthStore
from governance.autopilot.monitor import ChangeMonitor,TriggerStore


def agent(tmp_path):
    return RegulatoryWatcherAgent(cursor_store=CursorStore(tmp_path/'c.jsonl'),
       emission_store=EmissionStore(tmp_path/'e.jsonl'),health_store=HealthStore(tmp_path/'h.jsonl'),
       change_monitor=ChangeMonitor(TriggerStore(tmp_path/'t.jsonl')))

def test_cisa_real_feed_fields_are_extracted(monkeypatch):
    class Resp:
        def raise_for_status(self):pass
        def json(self):return {'vulnerabilities':[{'cveID':'CVE-2026-12345',
            'vendorProject':'ACME','product':'Example','dateAdded':'2026-09-19',
            'shortDescription':'Known exploited vulnerability'}]}
    monkeypatch.setattr('governance.watcher.connectors.requests.get',lambda *a,**kw:Resp())
    cfg=WatcherConfig('cisa-kev-awareness',SourceType.THREAT,WatcherAuthority.THREAT,'GLOBAL',
      {'type':'http_json','url':'https://www.cisa.gov/example.json','items_field':'vulnerabilities',
       'content_field':'shortDescription','title_field':'cveID','publication_field':'dateAdded'})
    doc=HTTPJSONConnector().fetch(cfg,None)[0]
    assert doc.title=='CVE-2026-12345 — ACME Example'
    assert doc.published_at=='2026-09-19'
    assert doc.url=='https://www.cisa.gov/example.json'


def test_incomplete_live_source_is_degraded_and_never_triggers(tmp_path):
    a=agent(tmp_path)
    cfg=WatcherConfig('feed',SourceType.REGULATION,WatcherAuthority.BINDING,'SG',
       {'type':'static','items':[{'id':'1','title':'Untitled','content':'shall must governance',
        'last_modified':'1','materiality':1.,'classification_confidence':1.,
        'requirements':[{'control_id':'M3.6','requirement_text':'x'}]}]},
       filters={'framework':'MAS','require_source_validation':True,'keywords':['governance']})
    run=a.run_source(cfg)
    assert run.emitted==0 and run.skipped==1 and run.cursor_after is None
    assert a.health_store.latest('feed')['status']=='DEGRADED'
    assert a.emission_store.read()[0]['payload']['emission_status']=='INVALID_DOCUMENT'
    assert a.change_monitor.store.read()==[]


def test_demo_source_cannot_claim_binding_authority():
    from governance.watcher.policy import load_sources
    from pathlib import Path
    cfg=Path(__file__).resolve().parents[1]/'config'/'watcher_sources.yaml'
    text=cfg.read_text()
    assert 'source_id: demo-mas-regulatory-feed\n    source_type: background\n    authority: background' in text
