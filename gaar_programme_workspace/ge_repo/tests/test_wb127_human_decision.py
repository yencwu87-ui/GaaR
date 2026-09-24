import json
from types import SimpleNamespace

import events
import pytest

from governance.audit_package import decision_service as ds


def ready_preflight(cycle_id='c1', *, batch=False):
    return {
        'cycle_id':cycle_id,'control_id':'S2.2','framework':'SAFR','review_tier':'routine',
        'batch_eligible':True,'single_eligible':True,'checkpoint':'HUMAN_DECISION',
        'proposal':{'sufficiency':'partial','maturity':2},'package_fingerprint':'fp123',
        'signer_key_id':'k1','blockers':[],
        'identity_assurance':'LOCAL_ATTRIBUTION_ONLY_NOT_AUTHENTICATED'
    }


def test_single_approval_uses_existing_cycle_decide(monkeypatch):
    state={'cycle_id':'c1','control_id':'S2.2','framework':'SAFR',
           'proposal':{'sufficiency':'partial','maturity':2},'evidence':{'evidence_set_id':'E1'}}
    monkeypatch.setattr(ds,'preflight',lambda cid,batch=False:ready_preflight(cid,batch=batch))
    monkeypatch.setattr(events,'state',lambda cid:state)
    monkeypatch.setattr(ds,'_package_fingerprint',lambda s:'fp123')
    calls=[]
    monkeypatch.setattr(ds.governance_cycle,'decide',lambda cid,**kw:(calls.append((cid,kw)) or {
        'human_decision_id':'hum1','governance_result_id':'res1',
        'governance_result':{'result_id':'res1'},'quality_gate':{'status':'FINALIZABLE'}}))
    out=ds.approve_one('c1',reviewer_id='Alice Reviewer')
    assert out['decision_path']=='core.cycle.decide' and out['status']=='CURRENT'
    assert calls[0][0]=='c1'
    assert calls[0][1]['sufficiency']=='partial' and calls[0][1]['maturity']==2
    assert calls[0][1]['reviewer']=='Alice Reviewer' and calls[0][1]['action']=='accept'
    assert 'complete governed audit package' in calls[0][1]['reason']


def test_system_cannot_be_human_decider():
    with pytest.raises(ds.DecisionServiceError,match='SYSTEM'):
        ds.approve_one('c1',reviewer_id='SYSTEM')


def test_package_drift_blocks_before_decide(monkeypatch):
    monkeypatch.setattr(ds,'preflight',lambda cid,batch=False:ready_preflight(cid,batch=batch))
    monkeypatch.setattr(events,'state',lambda cid:{'cycle_id':'c1','proposal':{'sufficiency':'partial','maturity':2},'evidence':{}})
    monkeypatch.setattr(ds,'_package_fingerprint',lambda s:'changed')
    called=[]
    monkeypatch.setattr(ds.governance_cycle,'decide',lambda *a,**k:called.append(1))
    with pytest.raises(ds.DecisionServiceError,match='changed after decision preflight'):
        ds.approve_one('c1',reviewer_id='Alice')
    assert called==[]


def test_final_gate_block_does_not_claim_current(monkeypatch):
    state={'cycle_id':'c1','control_id':'S2.2','proposal':{'sufficiency':'partial','maturity':2},'evidence':{}}
    monkeypatch.setattr(ds,'preflight',lambda cid,batch=False:ready_preflight(cid,batch=batch))
    monkeypatch.setattr(events,'state',lambda cid:state)
    monkeypatch.setattr(ds,'_package_fingerprint',lambda s:'fp123')
    monkeypatch.setattr(ds.governance_cycle,'decide',lambda *a,**k:{
        'human_decision_id':'hum1','governance_result_id':'res1','governance_result':{'result_id':'res1'},
        'quality_gate':{'status':'BLOCKED','blockers':['evidence:gap']}})
    out=ds.approve_one('c1',reviewer_id='Alice')
    assert out['status']=='BLOCKED_FINALIZED'
    assert out['published_current'] is False


def test_batch_is_only_loop_over_same_single_path(tmp_path,monkeypatch):
    monkeypatch.setenv('WB_GAAR_BATCH_DECISION_STORE',str(tmp_path/'batch.jsonl'))
    checks={
      'a':dict(ready_preflight('a'),batch_eligible=True),
      'b':dict(ready_preflight('b'),batch_eligible=True),
      'elevated':dict(ready_preflight('elevated'),batch_eligible=False,blockers=['nonroutine_individual_review']),
    }
    monkeypatch.setattr(ds,'preflight',lambda cid,batch=False:checks[cid])
    calls=[]
    def approve(cid,*,reviewer_id,note=None):
        calls.append(cid)
        return {'cycle_id':cid,'status':'CURRENT','decision_path':'core.cycle.decide',
                'human_decision_id':'hum-'+cid,'governance_result_id':'res-'+cid}
    monkeypatch.setattr(ds,'approve_one',approve)
    out=ds.approve_batch(['a','elevated','b'],reviewer_id='Alice')
    assert calls==['a','b']
    assert out['current']==2 and out['skipped']==1
    assert all(x.get('human_decision_id') for x in out['items'] if x['status']=='CURRENT')
    assert out['path_identity'].startswith('EVERY_APPROVED_ITEM_CALLS_APPROVE_ONE')
    rows=ds.HashChainStore(tmp_path/'batch.jsonl',ds.SCHEMA).read()
    assert len(rows)==1 and rows[0]['record_type']=='HumanBatchDecisionReceipt'


def test_batch_last_moment_failure_is_per_control_not_bulk(tmp_path,monkeypatch):
    monkeypatch.setenv('WB_GAAR_BATCH_DECISION_STORE',str(tmp_path/'batch.jsonl'))
    monkeypatch.setattr(ds,'preflight',lambda cid,batch=False:ready_preflight(cid,batch=batch))
    def approve(cid,*,reviewer_id,note=None):
        if cid=='b': raise ds.DecisionServiceError('waiver revoked after render')
        return {'cycle_id':cid,'status':'CURRENT','decision_path':'core.cycle.decide','human_decision_id':'h','governance_result_id':'r'}
    monkeypatch.setattr(ds,'approve_one',approve)
    out=ds.approve_batch(['a','b','c'],reviewer_id='Alice')
    assert out['current']==2 and out['blocked']==1
    assert next(x for x in out['items'] if x['cycle_id']=='b')['status']=='BLOCKED'


def test_investigate_and_reject_do_not_decide(monkeypatch):
    monkeypatch.setattr(events,'state',lambda cid:{'cycle_id':cid,'decision':None})
    rows=[]
    monkeypatch.setattr(ds.governance_cycle,'record_note',lambda cid,payload,actor:(rows.append(payload) or {'event_id':'note1'}))
    a=ds.request_investigation('c1',reviewer_id='Alice',note='Investigate whether the deployment timestamp predates the approval record.')
    b=ds.reject_proposal('c1',reviewer_id='Alice',note='The admitted evidence does not demonstrate the proposed operating maturity level.')
    assert a['governance_result_created'] is False and b['governance_result_created'] is False
    assert [r['audit_package_human_action'] for r in rows]==['REQUEST_INVESTIGATION','REJECT_PROPOSAL']


def test_preflight_rejects_nonroutine_batch(monkeypatch):
    state={'cycle_id':'c1','control_id':'S2.2','framework':'SAFR','proposal':{'sufficiency':'partial','maturity':2},
           'evidence':{'evidence_set_id':'E1'},'blind_read_waiver':None}
    monkeypatch.setattr(events,'state',lambda cid:state)
    fake=SimpleNamespace(checkpoint='HUMAN_DECISION',quality_audit=None)
    monkeypatch.setattr('governance.ai_auditor.conductor.ReviewConductor.inspect',lambda self,cid:fake)
    monkeypatch.setenv('WB_GAAR_RESULT_ENABLE','1');monkeypatch.setenv('WB_GAAR_QUALITY_GATE','1')
    monkeypatch.setattr('governance.result_integration.signer_from_env',lambda:SimpleNamespace(key_id='k'))
    monkeypatch.setattr(ds,'_package_fingerprint',lambda s:'fp')
    out=ds.preflight('c1',batch=True)
    assert not out['batch_eligible'] and 'nonroutine_individual_review' in out['blockers']


def test_result_provenance_includes_independent_challenge_event(monkeypatch):
    import governance.result_integration as ri
    monkeypatch.setattr('core.cycle._control',lambda cid,fw:SimpleNamespace(req='Requirement',maps=[]))
    state={
      'cycle_id':'c1','control_id':'S2.2','framework':'SAFR','evidence':{'text':'x'},
      'proposal':{'sufficiency':'partial','maturity':2},'proposal_model':'assess-model',
      'assessment_identity':{},'decided_by':'Alice','decision':{'sufficiency':'partial','reason':'A sufficiently detailed human reason for result.'},
      '_events':[{'kind':'proposed','event_id':'p1','ts':'2026-01-01T00:00:00Z'},
                 {'kind':'independent_challenged','event_id':'ic1','ts':'2026-01-01T00:01:00Z'}]
    }
    out=ri.build_result_inputs(cycle_id='c1',state=state,human_decision_id='h1',decision_timestamp='2026-01-01T00:02:00Z')
    assert out['provenance'].workflow_step_timestamps.get('independent_challenged')
    # challenge set must change if independent challenge event ID changes
    state2=dict(state);state2['_events']=[dict(x) for x in state['_events']];state2['_events'][1]['event_id']='ic2'
    out2=ri.build_result_inputs(cycle_id='c1',state=state2,human_decision_id='h1',decision_timestamp='2026-01-01T00:02:00Z')
    assert out['challenge_set_id'] != out2['challenge_set_id']
