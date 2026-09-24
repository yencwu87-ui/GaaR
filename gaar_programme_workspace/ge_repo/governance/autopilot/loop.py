from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from governance.ai_auditor import ReviewConductor
from governance.change_runtime import apply_change
from governance.reassessment import start_reassessment_cycle
from governance.result_contract import ResultStateLog
from governance.result_store import ResultStore

from .monitor import AutopilotTrigger, TriggerType
from .policy import AutopilotPolicy, load_policy
from .scheduler import AutopilotJob, AutopilotScheduler, JobStatus

@dataclass(frozen=True)
class LoopOutcome:
    job_id: str
    trigger_id: str
    status: str
    cycle_ids: tuple[str,...]
    checkpoints: tuple[str,...]
    state_events: int
    human_attention_required: bool
    message: str

class ContinuousGovernanceLoop:
    """Governed orchestration for G.

    The loop may detect, queue, trigger reassessment and run machine-owned Review Conductor steps.
    It deliberately cannot create a human read, human decision, or force a GovernanceResult to CURRENT.
    """
    def __init__(self, *, policy:AutopilotPolicy|None=None, scheduler:AutopilotScheduler|None=None,
                 conductor:ReviewConductor|None=None, result_store:ResultStore|None=None,
                 state_log:ResultStateLog|None=None):
        self.policy=policy or load_policy(); self.scheduler=scheduler or AutopilotScheduler(policy=self.policy)
        self.conductor=conductor or ReviewConductor(); self.result_store=result_store or ResultStore(); self.state_log=state_log or ResultStateLog()

    def enqueue(self, trigger:AutopilotTrigger) -> AutopilotJob:
        return self.scheduler.enqueue(trigger)

    def run_job(self, job:AutopilotJob, trigger:AutopilotTrigger, *, change=None, impact=None,
                candidate_requirements:dict[str,Any]|None=None, actor_id='gaar-autopilot') -> LoopOutcome:
        if job.status != JobStatus.RUNNING:
            raise ValueError('job must be RUNNING before execution')
        if trigger.trigger_type != TriggerType.GOVERNANCE_CHANGE:
            self.scheduler.update(job,status=JobStatus.SKIPPED,outcome='TRIGGER_REQUIRES_ADAPTER')
            return LoopOutcome(job.job_id,trigger.trigger_id,'SKIPPED',(),(),0,False,'Trigger adapter not yet bound to a GovernanceChange.')
        if not (change and impact and candidate_requirements):
            self.scheduler.update(job,status=JobStatus.FAILED,error='governance change context missing')
            return LoopOutcome(job.job_id,trigger.trigger_id,'FAILED',(),(),0,True,'GovernanceChange, ImpactAssessment and candidate requirements are required.')

        applied=apply_change(change,impact,result_store=self.result_store,state_log=self.state_log,actor_id=actor_id)
        state_events=tuple(applied.get('state_events') or ())
        cycle_ids=[]; checkpoints=[]; human=False
        for ev in state_events:
            started=start_reassessment_cycle(review_event=ev,change=change,impact=impact,candidate_requirements=candidate_requirements,
                result_store=self.result_store,state_log=self.state_log,actor_id=actor_id)
            cid=started['cycle_id']; cycle_ids.append(cid)
            decision=self.conductor.run_to_checkpoint(cid,actor='ai-auditor')
            checkpoints.append(decision.checkpoint)
            human = human or decision.checkpoint.startswith('HUMAN') or decision.checkpoint in {'EVIDENCE_REQUIRED', 'INVESTIGATION_REQUIRED'}
        if not state_events:
            status=JobStatus.COMPLETE; outcome='NO_CURRENT_RESULT_IMPACT'; message='Change persisted; no CURRENT result required reassessment.'
        elif human:
            status=JobStatus.WAITING_HUMAN; outcome='WAITING_HUMAN'; message='Autopilot advanced machine-owned nodes and stopped at a governed checkpoint.'
        else:
            status=JobStatus.COMPLETE; outcome='MACHINE_STEPS_COMPLETE'; message='Machine-owned steps completed without a human checkpoint.'
        self.scheduler.update(job,status=status,cycle_id=cycle_ids[-1] if cycle_ids else None,
                              checkpoint=checkpoints[-1] if checkpoints else None,outcome=outcome)
        return LoopOutcome(job.job_id,trigger.trigger_id,status.value,tuple(cycle_ids),tuple(checkpoints),len(state_events),human,message)

    def status(self): return self.scheduler.status()
