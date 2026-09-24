"""WB-125 negative-first tests. Nothing here generates a fake GovernanceResult."""
from __future__ import annotations
import base64
import json
import os
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
import events
from core import cycle
from governance.result_integration import signer_from_env
from governance.routine_waiver import (policy_approval,verify_policy,approved_policy,
    eligibility,apply,applied_waiver,WaiverDenied,VERSION)

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(events,'LOG',tmp_path/'events.jsonl')
    monkeypatch.setenv('WB_GAAR_RESULT_SIGNING_KEY_B64',base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv('WB_GAAR_RESULT_KEY_ID','wb125-test')
    monkeypatch.setenv('WB_GAAR_ADMISSION_STORE',str(tmp_path/'admissions.jsonl'))
    signer=signer_from_env()
    approval=policy_approval(approved_by='human-governance-lead',reason='Approved change for controlled routine reassessment',signer=signer)
    loc=tmp_path/'approved-policy.json'
    loc.write_text(json.dumps(approval))
    monkeypatch.setenv('WB_GAAR_ROUTINE_POLICY_FILE',str(loc))
    monkeypatch.setenv('WB_GAAR_ROUTINE_WAIVER_ENABLED','1')
    return tmp_path,loc,approval

def test_signature_tamper_and_policy_must_be_explicit(isolated,monkeypatch):
    tmp,path,p=isolated
    assert verify_policy(p) and approved_policy()['schema']==VERSION
    monkeypatch.setenv('WB_GAAR_ROUTINE_WAIVER_ENABLED','0')
    with pytest.raises(WaiverDenied,match='disabled'):approved_policy()
    monkeypatch.setenv('WB_GAAR_ROUTINE_WAIVER_ENABLED','1')
    for changed in ({**p,'reason':'inadequate'},
                    {**p,'tier':'critical'},
                    {**p,'human_final_decision_required':False},
                    {**p,'waive':['human_final_decision']}):
        assert not verify_policy(changed)
        path.write_text(json.dumps(changed))
        with pytest.raises(WaiverDenied,match='signature or terms'):approved_policy()
    path.write_text(json.dumps(p))
    bad=tmp/'link.json';bad.symlink_to(path)
    monkeypatch.setenv('WB_GAAR_ROUTINE_POLICY_FILE',str(bad))
    with pytest.raises(WaiverDenied,match='symlinked'):approved_policy()

def test_approver_restrictions(isolated):
    signer=signer_from_env()
    with pytest.raises(WaiverDenied,match='named human'):
        policy_approval(approved_by='system',reason='this is a sufficiently long reason',signer=signer)
    with pytest.raises(WaiverDenied,match='substantial'):
        policy_approval(approved_by='human',reason='OK',signer=signer)

CTX={'risk_tier':'low','material_change':False,'evidence_contradiction':False,
     'unresolved_strong_challenge':False,'quality_blocked':False,
     'governance_exception':False,'independent_review_required':False,
     'assessment_confidence':.95,'requirement_version_id':'req-v1'}

def _eligible(isolated,monkeypatch,ctx=None):
    from governance.admission import AdmissionStore
    tmp,_,_=isolated
    prior=cycle.start('S2.2',framework='SAFR',actor='human')
    # This fixture stubs prior REAL result and signed admission verification below.
    events.append('decided',cycle_id=prior,actor='human',control_id='S2.2',framework='SAFR',
                  payload={'sufficiency':'partial','maturity':2,'reason':'previous human review decision'})
    cid=cycle.start('S2.2',framework='SAFR',governance_context=ctx if ctx is not None else CTX)
    expiry=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
    ev={'text':'threshold policy approved before deployment',
        'evidence_set_id':'EVID-1','admission_dossier_id':'dos-1','fresh_until':expiry}
    cycle.bind_evidence(cid,ev)
    store=AdmissionStore()
    store.append('EvidenceCycleBound',{'dossier_id':'dos-1','cycle_id':cid,'evidence_set_id':'EVID-1',
                                      'cycle_evidence_bound':True})
    cycle.record_proposal(cid,{'sufficiency':'partial','maturity':2,'rationale':'supported by approved record'},actor='assessor')
    monkeypatch.setattr('governance.routine_waiver._prior_decision',lambda *_:True)
    monkeypatch.setattr('governance.routine_waiver._verified_admission',lambda *_:True)
    return cid

def test_unknown_or_first_assessment_never_routine(isolated):
    cid=cycle.start('S2.2',framework='SAFR',governance_context=CTX)
    with pytest.raises(WaiverDenied,match='first_assessment'):
        apply(cid)
    assert not [x for x in events.cycle(cid) if x['kind']=='blind_read_waived']

def test_eligible_waiver_is_event_not_read_or_decision(isolated,monkeypatch):
    # No LLM needed: this verifies policy boundary with an already-recorded proposal.
    monkeypatch.setattr(cycle,'assert_contract_executable',lambda *_:None)
    monkeypatch.setattr(cycle,'check_bundle_unchanged',lambda *_:None)
    cid=_eligible(isolated,monkeypatch)
    assert eligibility(events.state(cid)) == []
    before=len(events.cycle(cid))
    ev=apply(cid)
    state=events.state(cid)
    assert ev['kind']=='blind_read_waived' and len(events.cycle(cid))==before+1
    assert state['blind_read_waiver']['policy_version']==VERSION
    assert not state.get('read') and not state.get('diff') and not state.get('decision')
    assert applied_waiver(state)
    with pytest.raises(WaiverDenied,match='already recorded'):apply(cid)
    assert 'independent_challenge_not_recorded' in eligibility(state,require_challenge=True)
    monkeypatch.setenv('WB_GAAR_ROUTINE_WAIVER_ENABLED','0')
    assert applied_waiver(events.state(cid)) is None
    with pytest.raises(cycle.CycleError,match='withdrawn'):
        cycle.decide(cid,sufficiency='partial',maturity=2,reason='Reviewed source evidence and evidence limitations',reviewer='human')

def test_risk_change_exception_or_stale_blocks(isolated,monkeypatch):
    monkeypatch.setattr(cycle,'assert_contract_executable',lambda *_:None)
    monkeypatch.setattr(cycle,'check_bundle_unchanged',lambda *_:None)
    for field,value in [('risk_tier','high'),('risk_tier','unknown'),('material_change',True),
                        ('evidence_contradiction',True),('unresolved_strong_challenge',True),
                        ('assessment_confidence',None),('independent_review_required',True)]:
        cid=_eligible(isolated,monkeypatch,ctx={**CTX,field:value})
        assert eligibility(events.state(cid)),(field,value)
        with pytest.raises(WaiverDenied):apply(cid)

def test_waiver_does_not_fabricate_challenge_and_conductor_stops(isolated,monkeypatch):
    # Legacy contract fixture; mandatory investigation defaults are tested separately.
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
    monkeypatch.setattr(cycle,'assert_contract_executable',lambda *_:None)
    monkeypatch.setattr(cycle,'check_bundle_unchanged',lambda *_:None)
    cid=_eligible(isolated,monkeypatch)
    apply(cid)
    from governance.ai_auditor.conductor import ReviewConductor
    from governance.ai_auditor.schemas import EvidenceExaminerOutput
    from governance.ai_auditor.skills import evidence_examiner
    monkeypatch.setattr(evidence_examiner,'run',lambda *a,**k:EvidenceExaminerOutput(
       sufficiency_score=1.,evidence_freshness='100%',open_evidence_gaps=[],
       covered_elements=[],recommended_action='NONE',rationale='fixture preflight'))
    decision=ReviewConductor().inspect(cid)
    assert decision.checkpoint=='CHALLENGE_REQUIRED'
    assert not events.state(cid).get('read') and not events.state(cid).get('decision')


def test_signed_policy_hash_follows_cycle_event(isolated,monkeypatch):
    monkeypatch.setattr(cycle,'assert_contract_executable',lambda *_:None)
    monkeypatch.setattr(cycle,'check_bundle_unchanged',lambda *_:None)
    cid=_eligible(isolated,monkeypatch)
    apply(cid)
    assert events.verify()['intact']
    assert events.state(cid)['blind_read_waiver']['policy_sha256']

def test_forged_admission_bound_record_rejected(isolated,monkeypatch):
    from governance.routine_waiver import _verified_admission
    tmp,_,_=isolated
    cid=cycle.start('S2.2',framework='SAFR',governance_context=CTX)
    cycle.bind_evidence(cid,{'text':'content','evidence_set_id':'EVID-fake',
                             'admission_dossier_id':'dos-fake','fresh_until':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
    from governance.admission import AdmissionStore
    AdmissionStore().append('EvidenceCycleBound',{
        'dossier_id':'dos-fake','cycle_id':cid,'evidence_set_id':'EVID-fake',
        'cycle_evidence_bound':True,'admission_signature':'fake'})
    assert not _verified_admission(events.state(cid))


def test_fake_prior_decision_does_not_qualify(isolated):
    from governance.routine_waiver import _prior_decision
    prior=cycle.start('S2.2',framework='SAFR')
    events.append('decided',cycle_id=prior,actor='human',control_id='S2.2',framework='SAFR',
                  payload={'human_decision_id':'fake','governance_result_id':'fake'})
    cid=cycle.start('S2.2',framework='SAFR',governance_context=CTX)
    assert _prior_decision(events.state(cid)) is False


def test_waived_decide_missing_challenge_rejected_before_any_write(isolated,monkeypatch):
    monkeypatch.setattr(cycle,'assert_contract_executable',lambda *_:None)
    monkeypatch.setattr(cycle,'check_bundle_unchanged',lambda *_:None)
    cid=_eligible(isolated,monkeypatch)
    apply(cid)
    monkeypatch.setenv('WB_GAAR_RESULT_ENABLE','1')
    monkeypatch.setenv('WB_GAAR_QUALITY_GATE','1')
    before=events.read_all()
    with pytest.raises(cycle.CycleError,match='independent_challenge_not_recorded'):
        cycle.decide(cid,sufficiency='partial',maturity=2,
                     reason='Reviewed the evidence and its documented limitations',reviewer='human')
    assert events.read_all()==before
