from governance.operator_experience import audit_outcome, cycle_trace, portfolio_snapshot


def state(**kwargs):
    return {'cycle_id':'c1','control_id':'S2.2','framework':'SAFR', **kwargs}


def test_trace_is_cycle_scoped():
    assert [r['cycle_id'] for r in cycle_trace([{'cycle_id':'c2'},{'cycle_id':'c1'}], 'c1')] == ['c1']


def test_missing_evidence_no_false_success():
    assert audit_outcome(state(),[],checkpoint='HUMAN_DECISION')['status']=='EVIDENCE_NEEDED'


def test_current_cycle_evidence_free_proposal_is_an_incident():
    rows=[{'cycle_id':'c2','kind':'proposed'}, {'cycle_id':'c1','kind':'proposed'}]
    o=audit_outcome(state(), rows)
    assert o['status']=='PROBLEM_NEEDS_ATTENTION' and o['evidence_free_proposals']==1


def test_legacy_proposal_before_binding_is_visible():
    rows=[{'cycle_id':'c1','kind':'proposed'},{'cycle_id':'c1','kind':'evidence_bound'}]
    assert audit_outcome(state(evidence={'text':'x'}),rows)['evidence_free_proposals']==1


def test_clean_decision_requires_actual_current_and_gate():
    s=state(evidence={'text':'x'},decision={'decision':'PASS'})
    assert audit_outcome(s,[],living={'current_state':'CURRENT','quality_gate':'BLOCKED'})['status']=='PROBLEM_NEEDS_ATTENTION'
    assert audit_outcome(s,[],living={'current_state':'CURRENT','quality_gate':'FINALIZABLE'})['status']=='AUDIT_COMPLETE'


def test_blind_read_not_conflated_with_decision():
    assert audit_outcome(state(evidence={'text':'x'}),[],checkpoint='HUMAN_READ')['status']=='YOUR_REVIEW_NEEDED'


def test_clean_ready():
    assert audit_outcome(state(evidence={'text':'x'}),[],checkpoint='HUMAN_DECISION')['status']=='READY_FOR_DECISION'


def test_heatmap_missing_evidence_is_attention_not_risk_score():
    r=[{'library':'SAFR','control_id':'S2.2','title':'Access management','has_evidence':False,'next_action':{'kind':'input','label':'Add evidence'}}]
    p=portfolio_snapshot(r,[])
    assert p['by_theme']['Identity & access']['Evidence missing']==1
    assert 'risk_score' not in p


def test_heatmap_blocked_has_priority():
    r=[{'library':'SAFR','control_id':'S2.2','title':'Governance','has_evidence':False,'challenge':{'unresolved_strong':1},'next_action':{'kind':'input'}}]
    assert portfolio_snapshot(r,[])['hotspots'][0]['Attention']=='Exception / blocked'


def test_unmapped_is_visible():
    r=[{'library':'MAS','control_id':'M3','title':'xyz','has_evidence':True,'next_action':{'kind':'system'}}]
    assert 'Other / unmapped' in portfolio_snapshot(r,[])['by_theme']


def test_real_human_decision_findings_not_conflated_with_unassessed():
    rows=[{'library':'SAFR','control_id':'S2.2','title':'Model governance',
           'has_evidence':True,'next_action':{'kind':'complete','label':'Complete'}}]
    living=[{'framework':'SAFR','control_id':'S2.2','current_result':'res1',
             'current_state':'CURRENT','quality_gate':'FINALIZABLE','decision':'CONDITIONAL_PASS'}]
    snapshot=portfolio_snapshot(rows,living)
    assert snapshot['documented_findings']['AI model governance']['CONDITIONAL_PASS']==1
    assert snapshot['statuses']['Current / gate passed']==1


def test_async_proposal_writer_fails_closed_without_evidence(tmp_path, monkeypatch):
    import events
    from core.cycle import record_proposal, CycleError
    path=tmp_path/'events.jsonl'
    monkeypatch.setattr(events, 'LOG', path)
    events.append('cycle_started', cycle_id='isolated',actor='SYSTEM',control_id='S2.2',
                  framework='SAFR',payload={'title':'test'})
    before=path.read_bytes()
    import pytest
    with pytest.raises(CycleError, match='bind evidence'):
        record_proposal('isolated',{'status':'ok'},actor='assessor')
    assert path.read_bytes() == before
    assert not any(e['kind']=='proposed' for e in events.cycle('isolated'))
