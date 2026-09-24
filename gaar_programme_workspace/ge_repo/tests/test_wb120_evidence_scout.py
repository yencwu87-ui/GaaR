from governance.evidence_scout import EvidenceScoutAgent,EvidenceSource,ScoutRequest,ScoutStore

def test_scout_finds_ranked_candidates_without_deciding(tmp_path):
    (tmp_path/'a.md').write_text('Model inventory approval before deployment and governance review evidence',encoding='utf-8')
    (tmp_path/'b.md').write_text('Unrelated cafeteria menu',encoding='utf-8')
    store=ScoutStore(tmp_path/'scout.jsonl')
    res=EvidenceScoutAgent([EvidenceSource('repo',str(tmp_path))],store=store).run(ScoutRequest('M3.6','MAS','model governance approval before deployment',('approval before deployment',)))
    assert res.candidates and res.candidates[0].path=='a.md'
    assert res.recommended_action=='REVIEW_CANDIDATES'
    payload=store.read()[0]['payload']
    text=str(payload).lower()
    assert 'maturity' not in text and 'sufficiency' not in text and 'decision' not in text

def test_scout_deduplicates_same_content(tmp_path):
    (tmp_path/'a.md').write_text('model governance approval',encoding='utf-8')
    (tmp_path/'b.md').write_text('model governance approval',encoding='utf-8')
    res=EvidenceScoutAgent([EvidenceSource('repo',str(tmp_path))],store=ScoutStore(tmp_path/'s.jsonl')).run(ScoutRequest('x','MAS','model governance approval',()))
    assert len(res.candidates)==1

def test_scout_respects_approved_root_and_extensions(tmp_path):
    (tmp_path/'a.bin').write_bytes(b'model governance approval')
    res=EvidenceScoutAgent([EvidenceSource('repo',str(tmp_path))],store=ScoutStore(tmp_path/'s.jsonl')).run(ScoutRequest('x','MAS','model governance approval',()))
    assert not res.candidates

def test_scout_reports_collect_more_when_empty(tmp_path):
    (tmp_path/'a.md').write_text('cafeteria menu',encoding='utf-8')
    res=EvidenceScoutAgent([EvidenceSource('repo',str(tmp_path))],store=ScoutStore(tmp_path/'s.jsonl')).run(ScoutRequest('x','MAS','model governance approval',('approval evidence',)))
    assert res.recommended_action=='COLLECT_MORE' and res.gaps

def test_scout_hash_chain_survives_multiple_runs(tmp_path):
    (tmp_path/'a.md').write_text('model governance approval',encoding='utf-8')
    store=ScoutStore(tmp_path/'s.jsonl'); agent=EvidenceScoutAgent([EvidenceSource('repo',str(tmp_path))],store=store); req=ScoutRequest('x','MAS','model governance approval',())
    agent.run(req); agent.run(req); assert len(store.read())==2
