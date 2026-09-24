"""WB-126 isolated, no live CAS or real provider. All governance writes temp-scoped."""
import base64
import hashlib
import json
import os
from datetime import datetime,timedelta,timezone

import events
import pytest
from core import cycle
from governance.result_integration import signer_from_env
from governance.routine_waiver import policy_approval,apply,eligibility
from governance.independent_challenge import (
    IndependentChallengeError, proposal_view, run, verify_for_decision)

@pytest.fixture
def configured(tmp_path,monkeypatch):
    monkeypatch.setattr(events,'LOG',tmp_path/'events.jsonl')
    monkeypatch.setenv('WB_GAAR_RESULT_SIGNING_KEY_B64',base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv('WB_GAAR_RESULT_KEY_ID','wb126-lab')
    monkeypatch.setenv('WB_GAAR_ADMISSION_STORE',str(tmp_path/'admissions.jsonl'))
    signed=policy_approval(approved_by='approved-human',reason='Approved routine test policy in isolated fixture',signer=signer_from_env())
    loc=tmp_path/'policy.json';loc.write_text(json.dumps(signed))
    monkeypatch.setenv('WB_GAAR_ROUTINE_POLICY_FILE',str(loc))
    monkeypatch.setenv('WB_GAAR_ROUTINE_WAIVER_ENABLED','1')
    monkeypatch.setattr('governance.routine_waiver._prior_decision',lambda *_: True)
    monkeypatch.setattr('governance.routine_waiver._verified_admission',lambda *_: True)
    from governance.audit_package import policy_engine
    ctx={'risk_tier':'low','material_change':False,'evidence_contradiction':False,
        'unresolved_strong_challenge':False,'quality_blocked':False,
        'governance_exception':False,'independent_review_required':False,
        'assessment_confidence':.9,'requirement_version_id':'req-v1'}
    cid=cycle.start('S2.2',framework='SAFR',governance_context=ctx)
    text='Threshold policy approved before production deployment on 2026-09-10.'
    from governance.evidence_scout.dossier import ImmutableBlobStore
    monkeypatch.setenv('WB_GAAR_EVIDENCE_BLOB_ROOT',str(tmp_path/'blobs'))
    blob=ImmutableBlobStore(tmp_path/'blobs').put(text.encode())['sha256']
    cycle.bind_evidence(cid,{'text':text,'evidence_set_id':'EVID-real-fixture',
        'admission_dossier_id':'dos-fixture','fresh_until':(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),
        'chunks':[{'path':'root1/approval.txt','text':text}],
        'admitted_anchors':[{'anchor_id':'E01','sha256':blob,'blob_ref':f'sha256:{blob}','locator':'root1/approval.txt'}]})
    cycle.record_proposal(cid,{'sufficiency':'partial','maturity':2,
        'rationale':'THIS SENSITIVE ASSESSOR REASON MUST NEVER REACH CHALLENGER'},model='assess-test')
    apply(cid)
    return cid,loc

def responder(challenges=None):
    return json.dumps({'completed':True,'challenges':challenges or [],
                       'limitations':['Observed source does not prove longitudinal effectiveness.']})

def test_clean_run_does_not_create_decision_or_read(configured):
    cid,_=configured
    captured=[]
    out=run(cid,invoke=lambda sys,usr:(captured.append(usr),responder())[1])
    assert out['validation_status']=='admitted' and out['mode']=='independent_assessor_proposal'
    assert 'SENSITIVE ASSESSOR REASON' not in captured[0]
    assert 'rationale' not in json.loads(captured[0])['proposal_verdicts']
    assert verify_for_decision(events.state(cid))==[]
    s=events.state(cid)
    assert not s.get('read') and not s.get('diff') and not s.get('decision')
    assert len([x for x in events.cycle(cid) if x['kind']=='independent_challenged'])==1
    assert events.verify()['intact']

def test_rationale_mutation_does_not_change_challenge_input(configured,monkeypatch):
    from governance.independent_challenge import _input
    cid,_=configured
    a=_input(events.state(cid))
    monkeypatch.setattr('governance.routine_waiver._verified_admission',lambda *_:True)
    cycle.record_proposal(cid,{'sufficiency':'partial','maturity':2,'rationale':'A TOTALLY OPPOSITE STORY'},model='assess-test')
    b=_input(events.state(cid))
    assert a==b
    assert 'OPPOSITE STORY' not in json.dumps(b)

def test_fabricated_quote_blocks_and_cannot_retry_as_clean(configured):
    cid,_=configured
    row={'category':'factual_pointer','anchor_id':'E01','quote':'FABRICATED QUOTE!',
         'element_id':'','observation':'An invented fact that conflicts',
         'challenge':'Does the source truly say this?','strength':'strong','status':'open'}
    out=run(cid,invoke=lambda *_:responder([row]))
    assert out['validation_status']=='blocked' and not out['challenges']
    assert 'independent_challenge_not_admitted' in verify_for_decision(events.state(cid))
    with pytest.raises(IndependentChallengeError,match='already contains'):run(cid,invoke=lambda *_:responder())

def test_strong_challenge_restores_full_review_and_is_not_resolved_by_model(configured):
    cid,_=configured
    row={'category':'factual_pointer','anchor_id':'E01',
         'quote':'Threshold policy approved before production deployment',
         'element_id':'','observation':'The source records policy approval, not observed operating effectiveness.',
         'challenge':'Does the approval establish operating effectiveness across the review period?',
         'strength':'strong','status':'open'}
    out=run(cid,invoke=lambda *_:responder([row]))
    assert out['validation_status']=='admitted'
    assert 'unresolved_strong_independent_challenge_restore_full_review' in verify_for_decision(events.state(cid))
    assert 'unresolved_strong_challenge' in eligibility(events.state(cid),require_challenge=True)

def test_interpretation_cannot_be_strong(configured):
    cid,_=configured
    row={'category':'interpretation_pointer','anchor_id':'E01',
         'quote':'Threshold policy approved before production deployment',
         'element_id':'','observation':'A documented approval does not establish all operating periods.',
         'challenge':'What records demonstrate continuing effectiveness?',
         'strength':'strong','status':'open'}
    assert run(cid,invoke=lambda *_:responder([row]))['validation_status']=='blocked'

def test_provider_failure_is_blocked_not_clean(configured):
    cid,_=configured
    def fail(*_): raise TimeoutError('provider unavailable')
    assert run(cid,invoke=fail)['validation_status']=='blocked'
    assert verify_for_decision(events.state(cid))

def test_revoked_policy_prevents_challenge(configured,monkeypatch):
    cid,_=configured
    monkeypatch.setenv('WB_GAAR_ROUTINE_WAIVER_ENABLED','0')
    with pytest.raises(IndependentChallengeError,match='active routine waiver'):run(cid,invoke=lambda *_:responder())
    assert not events.state(cid).get('challenges')

def test_verdict_change_after_challenge_is_detected(configured):
    cid,_=configured
    run(cid,invoke=lambda *_:responder())
    cycle.record_proposal(cid,{'sufficiency':'full','maturity':4,'rationale':'revised'},model='assess-test')
    assert 'assessor_verdict_changed_after_challenge' in verify_for_decision(events.state(cid))

def test_missing_proposal_verdict_fails_closed():
    with pytest.raises(IndependentChallengeError):proposal_view({'sufficiency':'full','maturity':None})

def test_conductor_auto_runs_clean_challenge_without_deciding(configured,monkeypatch):
    # Legacy contract fixture; mandatory investigation defaults are tested separately.
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
    cid,_=configured
    from governance.ai_auditor.conductor import ReviewConductor
    from governance.ai_auditor.schemas import EvidenceExaminerOutput
    from governance.ai_auditor.skills import evidence_examiner
    monkeypatch.setenv('WB_GAAR_INDEPENDENT_CHALLENGE_ENABLED','1')
    monkeypatch.setattr(evidence_examiner,'run',lambda *args,**kwargs:EvidenceExaminerOutput(
        sufficiency_score=1.,evidence_freshness='100%',open_evidence_gaps=[],
        covered_elements=[],recommended_action='NONE',rationale='lab fixture'))
    from governance import independent_challenge
    genuine_run=independent_challenge.run
    monkeypatch.setattr(independent_challenge,'run',lambda cid:genuine_run(cid,invoke=lambda *_:responder()))
    result=ReviewConductor().run_to_checkpoint(cid)
    assert result.checkpoint=='HUMAN_DECISION'
    assert not events.state(cid).get('decision')
    assert len([e for e in events.cycle(cid) if e['kind']=='independent_challenged'])==1

def test_cas_corruption_fails_before_provider_call(configured):
    cid,_=configured
    state=events.state(cid)
    a=state['evidence']['admitted_anchors'][0]
    from pathlib import Path
    root=Path(os.environ['WB_GAAR_EVIDENCE_BLOB_ROOT'])
    blob=root/a['sha256'][:2]/a['sha256'][2:]
    blob.write_bytes(b'TEST-FIXTURE-ONLY CORRUPTED BLOB')
    called=[]
    with pytest.raises(IndependentChallengeError,match='CAS source re-verification'):
        run(cid,invoke=lambda *_:called.append(1))
    assert called==[] and not state.get('challenges')
