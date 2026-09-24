from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

import events
from governance.autopilot import AutopilotPolicy, ChangeMonitor, TriggerStore, TriggerType, AutopilotScheduler, JobStatus
from governance.autopilot.loop import ContinuousGovernanceLoop
from governance.change_intelligence import AuthorityEvidence, assess_impact, assess_source_authority, detect_governance_change
from governance.result_contract import CanonicalSigner, Decision, ProvenanceTrail, ResultStateLog, ValidityState, approve_result
from governance.result_store import ResultStore
from governance.result_contract import create_governance_result
from governance.triangulation import SourceRegistry

ROOT=Path(__file__).resolve().parents[1]

def _signer():
    key=Ed25519PrivateKey.generate(); raw=key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption())
    return CanonicalSigner.from_base64('g-test',base64.b64encode(raw).decode())

def _result():
    p=ProvenanceTrail(requirement_version_id='REQ-OLD',evidence_set_id='EVID-OLD',assessment_id='ASS-OLD',challenge_set_id='CH-OLD',
        human_decision_id='HD-OLD',assessor_prompt_version='v1',model_version='ollama:test',model_invocation_id='run-old',
        human_decider_id='human-old',human_decision_timestamp='2026-09-19T00:00:00+00:00')
    return create_governance_result(requirement_version_id='REQ-OLD',evidence_set_id='EVID-OLD',assessment_id='ASS-OLD',challenge_set_id='CH-OLD',
        human_decision_id='HD-OLD',decision=Decision.PASS,rationale='Existing current result.',provenance=p,signer=_signer())

def _change(old):
    reg=SourceRegistry.from_yaml(ROOT/'requirements/triangulation/sources.yaml'); src=reg.sources['MAS-TRM-NOTICES-BASELINE-2024']
    auth=assess_source_authority(src,metadata=AuthorityEvidence(issuer='MAS',jurisdiction='Singapore',legal_basis='MAS Notice',
        enforcement_status='binding',applicability='governed MAS scope',applicable=True),as_of='2026-09-19')
    current={'version':'1','controls':{'M3.6':{'requirement':'Old material requirement'}}}
    candidate={'version':'2','controls':{'M3.6':{'requirement':'Updated material requirement with independent validation.',
        'elements':[{'id':'e1','text':'Independent validation evidence is maintained.'}]}}}
    ch=detect_governance_change(current,candidate,source=src,authority=auth,detected_on='2026-09-19',applicability='governed MAS scope')
    imp=assess_impact(ch,results=[old],current_requirement_version_ids={'M3.6':old.requirement_version_id},control_materiality={'M3.6':'HIGH'})
    return ch,imp,candidate

def _seed_source_cycle(tmp_path,old):
    events.LOG=tmp_path/'events.jsonl'; cid='M3-6-source'
    events.append('cycle_started',cycle_id=cid,actor='human-old',control_id='M3.6',framework='MAS',payload={'title':'old'})
    events.append('evidence_bound',cycle_id=cid,actor='human-old',control_id='M3.6',framework='MAS',payload={'text':'Independent validation evidence is maintained and reviewed.','source_id':'evidence.md'})
    events.append('decided',cycle_id=cid,actor='human-old',control_id='M3.6',framework='MAS',payload={'governance_result_id':old.result_id,'human_decision_id':'HD-OLD'})

def test_full_change_to_reassessment_to_conductor_checkpoint(tmp_path,monkeypatch):
    monkeypatch.setenv('WB_GAAR_CHANGE_INTELLIGENCE','1'); monkeypatch.setenv('WB_GAAR_REASSESSMENT_WORKFLOW','1')
    old=_result(); rs=ResultStore(tmp_path/'results.jsonl'); sl=ResultStateLog(tmp_path/'states.jsonl'); rs.append(old)
    sl.append(approve_result(old,actor_id='human-old',decision_id='HD-OLD',reason='approved'))
    _seed_source_cycle(tmp_path,old); ch,imp,candidate=_change(old)
    trig_store=TriggerStore(tmp_path/'triggers.jsonl'); mon=ChangeMonitor(trig_store)
    trig=mon.emit(trigger_type=TriggerType.GOVERNANCE_CHANGE,control_id='M3.6',framework='MAS',reason='material regulation change',material=True,
        source_id=ch.source_id,change_id=ch.change_id,payload=ch.to_dict())
    policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=2,evidence_sufficiency_threshold=0.5)
    sched=AutopilotScheduler(tmp_path/'jobs.jsonl',policy=policy); queued=sched.enqueue(trig); running=sched.claim()[0]
    loop=ContinuousGovernanceLoop(policy=policy,scheduler=sched,result_store=rs,state_log=sl)
    out=loop.run_job(running,trig,change=ch,impact=imp,candidate_requirements=candidate)
    assert out.state_events==1 and len(out.cycle_ids)==1
    assert sl.current_state(old.result_id)==ValidityState.REASSESSING
    assert out.human_attention_required is True
    assert out.checkpoints[-1] == 'INVESTIGATION_REQUIRED'
    assert out.status == 'WAITING_HUMAN'
    latest={j.job_id:j for j in sched.latest_jobs()}[running.job_id]
    assert latest.status==JobStatus.WAITING_HUMAN
    s=events.state(out.cycle_ids[0]); assert s['governance_context']['trigger_change_id']==ch.change_id
    assert s['evidence']['text'].startswith('Independent validation')

def test_duplicate_change_is_deduplicated_before_queue(tmp_path):
    mon=ChangeMonitor(TriggerStore(tmp_path/'t.jsonl'))
    one=mon.emit(trigger_type=TriggerType.GOVERNANCE_CHANGE,control_id='2.1',framework='SAFR',reason='x',material=True,change_id='GC1',payload={'change_id':'GC1'})
    two=mon.emit(trigger_type=TriggerType.GOVERNANCE_CHANGE,control_id='2.1',framework='SAFR',reason='x',material=True,change_id='GC1',payload={'change_id':'GC1'})
    assert one is not None and two is None
