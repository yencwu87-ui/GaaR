from governance.release_readiness import evaluate_release_readiness

def test_release_readiness_returns_named_checks(monkeypatch,tmp_path):
    monkeypatch.setenv('WB_GAAR_RESULT_STORE',str(tmp_path/'results.jsonl'))
    monkeypatch.setenv('WB_GAAR_RESULT_STATE_STORE',str(tmp_path/'states.jsonl'))
    monkeypatch.setenv('WB_GAAR_QUALITY_GATE_STORE',str(tmp_path/'gates.jsonl'))
    monkeypatch.setenv('WB_GAAR_AUTOPILOT_TRIGGER_STORE',str(tmp_path/'triggers.jsonl'))
    monkeypatch.setenv('WB_GAAR_AUTOPILOT_JOB_STORE',str(tmp_path/'jobs.jsonl'))
    monkeypatch.setenv('WB_GAAR_WATCHER_EMISSION_STORE',str(tmp_path/'we.jsonl'))
    monkeypatch.setenv('WB_GAAR_WATCHER_CURSOR_STORE',str(tmp_path/'wc.jsonl'))
    monkeypatch.setenv('WB_GAAR_WATCHER_HEALTH_STORE',str(tmp_path/'wh.jsonl'))
    monkeypatch.setenv('WB_GAAR_SCOUT_STORE',str(tmp_path/'scout.jsonl'))
    out=evaluate_release_readiness(); assert out.ready
    names={x.name for x in out.checks}; assert {'result_store_chain','watcher_emission_chain','api_safe_bind'} <= names

def test_public_api_bind_requires_key(monkeypatch,tmp_path):
    monkeypatch.setenv('WB_GAAR_API_HOST','0.0.0.0'); monkeypatch.delenv('WB_GAAR_API_KEY',raising=False)
    out=evaluate_release_readiness(); c=next(x for x in out.checks if x.name=='api_safe_bind'); assert not c.passed and not out.ready
