from __future__ import annotations

from pathlib import Path
import pytest

from governance.autopilot import (
    AutopilotPolicy, ChangeMonitor, TriggerStore, TriggerType,
    AutopilotScheduler, JobStatus,
)


def test_policy_validates_concurrency(monkeypatch,tmp_path):
    p=tmp_path/'policy.yaml'; p.write_text('autopilot:\n  enabled: true\n  max_concurrent_reassessments: 2\n')
    from governance.autopilot.policy import load_policy
    out=load_policy(p); assert out.enabled and out.max_concurrent_reassessments==2


def test_trigger_store_deduplicates_identical_payload(tmp_path):
    store=TriggerStore(tmp_path/'triggers.jsonl'); mon=ChangeMonitor(store)
    a=mon.emit(trigger_type=TriggerType.MANUAL,control_id='2.1',framework='SAFR',reason='x',material=False,payload={'x':1})
    b=mon.emit(trigger_type=TriggerType.MANUAL,control_id='2.1',framework='SAFR',reason='x',material=False,payload={'x':1})
    assert a is not None and b is None
    assert len(store.read())==1


def test_trigger_store_hash_chain_detects_tamper(tmp_path):
    p=tmp_path/'triggers.jsonl'; store=TriggerStore(p); mon=ChangeMonitor(store)
    mon.emit(trigger_type=TriggerType.MANUAL,control_id='X',framework='MAS',reason='x',material=False,payload={'a':1})
    text=p.read_text(); p.write_text(text.replace('manual_review','manual_review_tampered') if 'manual_review' in text else text.replace('"reason":"x"','"reason":"y"'))
    with pytest.raises(ValueError): store.read()


def test_scheduler_respects_concurrency_limit(tmp_path):
    policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=2)
    trig_store=TriggerStore(tmp_path/'triggers.jsonl'); mon=ChangeMonitor(trig_store)
    sched=AutopilotScheduler(tmp_path/'jobs.jsonl',policy=policy)
    for i in range(5):
        t=mon.emit(trigger_type=TriggerType.MANUAL,control_id=f'C{i}',framework='SAFR',reason='manual',material=False,payload={'i':i})
        sched.enqueue(t)
    claimed=sched.claim(); assert len(claimed)==2
    st=sched.status(); assert st['in_flight']==2 and st['queue_depth']==3


def test_scheduler_idempotent_enqueue(tmp_path):
    policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=1)
    mon=ChangeMonitor(TriggerStore(tmp_path/'triggers.jsonl')); sched=AutopilotScheduler(tmp_path/'jobs.jsonl',policy=policy)
    t=mon.emit(trigger_type=TriggerType.MANUAL,control_id='X',framework='MAS',reason='manual',material=False,payload={'i':1})
    a=sched.enqueue(t); b=sched.enqueue(t); assert a.job_id==b.job_id and len(sched.latest_jobs())==1


def test_scheduler_status_is_projection_of_append_only_history(tmp_path):
    policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=1)
    mon=ChangeMonitor(TriggerStore(tmp_path/'triggers.jsonl')); sched=AutopilotScheduler(tmp_path/'jobs.jsonl',policy=policy)
    t=mon.emit(trigger_type=TriggerType.MANUAL,control_id='X',framework='MAS',reason='manual',material=False,payload={'i':1}); j=sched.enqueue(t)
    running=sched.claim()[0]; sched.update(running,status=JobStatus.WAITING_HUMAN,checkpoint='HUMAN_DECISION',outcome='WAITING_HUMAN')
    st=sched.status(); assert st['counts']['WAITING_HUMAN']==1 and st['in_flight']==0
    assert len(sched._records())==3


def test_non_governance_trigger_cannot_fabricate_review(tmp_path):
    from governance.autopilot.loop import ContinuousGovernanceLoop
    policy=AutopilotPolicy(enabled=True,max_concurrent_reassessments=1)
    mon=ChangeMonitor(TriggerStore(tmp_path/'triggers.jsonl')); sched=AutopilotScheduler(tmp_path/'jobs.jsonl',policy=policy)
    t=mon.emit(trigger_type=TriggerType.MANUAL,control_id='X',framework='MAS',reason='manual',material=False,payload={'i':1})
    j=sched.enqueue(t); r=sched.claim()[0]
    out=ContinuousGovernanceLoop(policy=policy,scheduler=sched).run_job(r,t)
    assert out.status=='SKIPPED' and out.state_events==0


def test_policy_human_checkpoint_reasons_are_declarative():
    p=AutopilotPolicy(human_checkpoint_triggers=('strong_unresolved_challenge','quality_gate_failure'))
    assert p.requires_human({'strong_unresolved_challenge'})
    assert not p.requires_human({'routine_change'})
