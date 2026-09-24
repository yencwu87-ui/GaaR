from dataclasses import replace
import pytest
from governance.audit_package import (ReviewContext, route_policy, prepare_package,
    batch_eligibility, require_explicit_human_action)

BASE = ReviewContext(risk_tier='low',first_assessment=False,admitted_evidence=True,
                     freshness_verified=True,assessment_confidence=.95)

@pytest.mark.parametrize('change', [
    {'risk_tier':'high'}, {'risk_tier':'critical'}, {'first_assessment':True},
    {'governance_exception':True}, {'quality_blocked':True},
    {'unresolved_strong_challenge':True}, {'evidence_contradiction':True},
    {'independent_review_required':True},
])
def test_critical_is_never_batch(change):
    p=route_policy(replace(BASE,**change))
    assert p.name=='critical' and p.require_blind_read and not p.allow_batch_approval

@pytest.mark.parametrize('change', [
    {'risk_tier':'unknown'}, {'material_change':True},
    {'assessment_confidence':None}, {'assessment_confidence':.74},
    {'admitted_evidence':False}, {'freshness_verified':False},
])
def test_elevated_fail_closed(change):
    p=route_policy(replace(BASE,**change))
    assert p.name=='elevated' and not p.allow_batch_approval

def test_routine_requires_all_good():
    p=route_policy(BASE)
    assert p.name=='routine' and not p.require_blind_read and p.allow_batch_approval
    assert route_policy(replace(BASE,risk_tier='medium')).name=='routine'

def test_invalid_context_fails():
    with pytest.raises(ValueError): route_policy(replace(BASE,risk_tier='unrecognized'))
    with pytest.raises(ValueError): route_policy(replace(BASE,assessment_confidence=1.7))
    with pytest.raises(TypeError): route_policy({})

def test_proposed_dossier_never_ready_or_admitted():
    d={'dossier_id':'d1','content_hash':'a'*64,'binding_status':'PROPOSED_ONLY',
       'control_id':'2.1','framework':'SAFR'}
    p=prepare_package(dossier=d,context=BASE)
    assert p['status']=='CHECKPOINT_REQUIRED'
    assert 'proposed_scout_dossier_requires_governed_evidence_admission' in p['blockers']
    assert p['human_decision_id'] is None and p['governance_result_id'] is None
    assert p['requires_human_decision'] is True
    assert p['package_id']==prepare_package(dossier=d,context=BASE)['package_id']

def test_no_synthetic_dossier_claims():
    with pytest.raises(ValueError): prepare_package(dossier={'dossier_id':'x','content_hash':'x','binding_status':'ADMITTED'})
    with pytest.raises(ValueError): prepare_package(dossier={'binding_status':'PROPOSED_ONLY'})
    with pytest.raises(ValueError): prepare_package()

def test_batch_preview_is_readonly_and_guarded():
    p={'package_id':'one','cycle_id':'c1','status':'READY_FOR_HUMAN_REVIEW','blockers':[],
       'review_policy':{'name':'routine'},'quality_gate_bypassed':False}
    out=batch_eligibility([p])
    assert out['eligible'] and out['human_decisions_created']==0 and out['results_published']==0
    for bad in (
        {**p,'blockers':['quality_gate_blocked']},
        {**p,'review_policy':{'name':'elevated'}},
        {**p,'quality_gate_bypassed':True},
        {**p,'cycle_id':None},
        {**p,'human_decision_id':'fake'},
        {**p,'status':'CHECKPOINT_REQUIRED'},
    ):
        assert not batch_eligibility([bad])['eligible']
    with pytest.raises(ValueError): batch_eligibility([p,p])
    with pytest.raises(ValueError): batch_eligibility([])
    with pytest.raises(PermissionError): require_explicit_human_action([p],reviewer='ai-auditor')
