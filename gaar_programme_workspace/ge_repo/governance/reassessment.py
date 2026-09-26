"""Governed reassessment workflow for GaaR.

This module does not run the assessor itself. It creates and advances a reassessment case around
an existing CURRENT -> REVIEW_REQUIRED trigger, then lets the existing assessment/challenge stack
produce a new GovernanceResult. Final state decisions remain human-governed.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from governance.change_intelligence import GovernanceChange, ImpactAssessment
from governance.result_contract import (
    ActorType,
    GovernanceResult,
    ResultStateLog,
    StateTransitionEvent,
    TransitionTrigger,
    ValidityState,
    begin_reassessment,
    reconfirm_current,
    supersede_reassessing_result,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_CASE_STORE = Path(os.environ.get("WB_REASSESSMENT_STORE") or ROOT / "reassessment_cases.jsonl")
GENESIS = "0" * 64


class ReassessmentStatus:
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_HUMAN = "AWAITING_HUMAN"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ReassessmentCase:
    case_id: str
    change_id: str
    impact_id: str
    result_id: str
    source_requirement_version_id: str
    target_requirement_version_id: str
    status: str
    opened_at: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReassessmentCaseStore:
    """Small append-only case register with a SHA-256 chain."""

    def __init__(self, path: str | Path = DEFAULT_CASE_STORE):
        self.path = Path(path)

    def last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        return (last or {}).get("record_hash", GENESIS)

    def append(self, case: ReassessmentCase) -> ReassessmentCase:
        with self._lock():
            prev = self.last_hash()
            body = {
                "store_schema_version": "gaar.reassessment-case.v1",
                "prev_hash": prev,
                "case": case.to_dict(),
            }
            body["record_hash"] = _sha(body)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(_canon(body) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return case

    def read(self) -> list[ReassessmentCase]:
        if not self.path.exists():
            return []
        out: list[ReassessmentCase] = []
        prev = GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("prev_hash") != prev:
                    raise ValueError("reassessment case chain is broken")
                if record.get("record_hash") != _sha({k: v for k, v in record.items() if k != "record_hash"}):
                    raise ValueError("reassessment case record hash is invalid")
                out.append(ReassessmentCase(**record["case"]))
                prev = record["record_hash"]
        return out

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def open_reassessment_case(
    *,
    review_event: StateTransitionEvent,
    change: GovernanceChange,
    impact: ImpactAssessment,
    result: GovernanceResult,
    store: ReassessmentCaseStore | None = None,
) -> ReassessmentCase:
    if review_event.to_state != ValidityState.REVIEW_REQUIRED:
        raise ValueError("reassessment case must originate from REVIEW_REQUIRED")
    if review_event.actor_type != ActorType.SYSTEM:
        raise ValueError("reassessment opening event must be SYSTEM-generated")
    if review_event.trigger_id != change.change_id:
        raise ValueError("review event is not triggered by the supplied GovernanceChange")
    if review_event.result_id != result.result_id:
        raise ValueError("review event/result mismatch")
    if result.requirement_version_id != result.provenance.requirement_version_id:
        raise ValueError("result provenance is internally inconsistent")

    identity = {
        "change_id": change.change_id,
        "impact_id": impact.impact_id,
        "result_id": result.result_id,
        "target_requirement_version_id": change.candidate_version,
    }
    case_id = f"RC-{_sha(identity)[:32]}"
    case = ReassessmentCase(
        case_id=case_id,
        change_id=change.change_id,
        impact_id=impact.impact_id,
        result_id=result.result_id,
        source_requirement_version_id=result.requirement_version_id,
        target_requirement_version_id=change.candidate_version,
        status=ReassessmentStatus.OPEN,
        opened_at=_now(),
        reason=review_event.reason,
    )
    (store or ReassessmentCaseStore()).append(case)
    return case


def begin_case_execution(
    case: ReassessmentCase,
    *,
    result: GovernanceResult,
    state_log: ResultStateLog,
    actor_id: str = "reassessment-engine",
    timestamp: str | None = None,
) -> StateTransitionEvent:
    if state_log.current_state(result.result_id) != ValidityState.REVIEW_REQUIRED:
        raise ValueError("result must currently be REVIEW_REQUIRED before reassessment starts")
    event = begin_reassessment(
        result,
        actor_id=actor_id,
        case_id=case.case_id,
        reason=f"Reassessment execution started for {case.case_id}",
        timestamp=timestamp,
        prev_hash=state_log.last_hash(),
    )
    return state_log.append(event)


def reconfirm_without_replacement(
    case: ReassessmentCase,
    *,
    result: GovernanceResult,
    state_log: ResultStateLog,
    actor_id: str,
    decision_id: str,
    reason: str = "Human reassessment confirmed existing governance result remains current",
    timestamp: str | None = None,
) -> StateTransitionEvent:
    if state_log.current_state(result.result_id) != ValidityState.REASSESSING:
        raise ValueError("result must be REASSESSING before human reconfirmation")
    event = reconfirm_current(
        result,
        actor_id=actor_id,
        decision_id=decision_id,
        reason=reason,
        timestamp=timestamp,
        prev_hash=state_log.last_hash(),
    )
    return state_log.append(event)


def complete_with_replacement(
    case: ReassessmentCase,
    *,
    old_result: GovernanceResult,
    new_result: GovernanceResult,
    state_log: ResultStateLog,
    actor_id: str,
    decision_id: str,
    reason: str = "Human reassessment approved replacement GovernanceResult",
    timestamp: str | None = None,
) -> tuple[StateTransitionEvent, StateTransitionEvent]:
    if state_log.current_state(old_result.result_id) != ValidityState.REASSESSING:
        raise ValueError("old result must be REASSESSING before supersession")
    if new_result.result_id == old_result.result_id:
        raise ValueError("replacement result must have a different result_id")
    if new_result.parent_result_id != old_result.result_id:
        raise ValueError("replacement result must reference old result as parent_result_id")

    old_event, new_event = supersede_reassessing_result(
        old_result,
        new_result,
        actor_id=actor_id,
        decision_id=decision_id,
        reason=reason,
        old_prev_hash=state_log.last_hash(),
        timestamp=timestamp,
    )
    state_log.append(old_event)
    state_log.append(new_event)
    return old_event, new_event


def enabled() -> bool:
    """Feature flag for live reassessment orchestration."""
    return os.environ.get("WB_GAAR_REASSESSMENT_WORKFLOW", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _candidate_control(candidate_requirements: dict[str, Any], control_id: str) -> dict[str, Any]:
    controls = (candidate_requirements or {}).get("controls") or {}
    raw = controls.get(control_id)
    if raw is None:
        raise ValueError(f"candidate requirement set has no control {control_id}")
    if isinstance(raw, str):
        return {"requirement": raw}
    if not isinstance(raw, dict):
        raise ValueError(f"candidate control {control_id} must be an object or string")
    return dict(raw)


def _requirement_text(control_spec: dict[str, Any]) -> str:
    for key in ("requirement", "text", "objective", "description"):
        value = str(control_spec.get(key) or "").strip()
        if value:
            return value
    raise ValueError("candidate control has no requirement text")


def _find_source_cycle_for_result(result_id: str) -> dict[str, Any]:
    """Resolve the assessment cycle that produced a sealed GovernanceResult.

    The cycle event ledger is the canonical evidence snapshot in this baseline.  The decided
    event carries governance_result_id, so D can recover the exact bound evidence without
    inventing or recollecting it.
    """
    import events as cycle_events

    for row in reversed(cycle_events.read_all()):
        if row.get("kind") != "decided":
            continue
        payload = row.get("payload") or {}
        if str(payload.get("governance_result_id") or "") == str(result_id):
            state = cycle_events.state(str(row.get("cycle_id")))
            if state:
                return state
    raise ValueError(f"no assessment cycle found for GovernanceResult {result_id}")


def requirement_version_id_for_candidate(
    *, framework: str, control_id: str, candidate_version: str, control_spec: dict[str, Any]
) -> str:
    identity = {
        "framework": framework,
        "control_id": control_id,
        "candidate_version": str(candidate_version),
        "control": control_spec,
    }
    return f"REQ-{_sha(identity)[:32]}"


def start_reassessment_cycle(
    *,
    review_event: StateTransitionEvent,
    change: GovernanceChange,
    impact: ImpactAssessment,
    candidate_requirements: dict[str, Any],
    result_store=None,
    state_log: ResultStateLog | None = None,
    case_store: ReassessmentCaseStore | None = None,
    actor_id: str = "reassessment-engine",
) -> dict[str, Any]:
    """Open D and enqueue the existing review cycle with governed reassessment context.

    This function deliberately does *not* call the assessor, challenger, Copilot or an LLM. It
    binds the old sealed result's current evidence to a normal cycle and supplies the target
    requirement snapshot. Existing review machinery owns every subsequent reasoning step.
    """
    if not enabled():
        return {"enabled": False, "review_event": review_event}

    from governance.result_store import ResultStore
    from core import cycle

    store = result_store or ResultStore()
    states = state_log or ResultStateLog()
    cases = case_store or ReassessmentCaseStore()

    old_result = next((x for x in store.read() if x.result_id == review_event.result_id), None)
    if old_result is None:
        raise ValueError(f"GovernanceResult not found: {review_event.result_id}")

    if impact.change_id != change.change_id:
        raise ValueError("impact/change mismatch")
    if old_result.result_id not in set(impact.affected_result_ids):
        raise ValueError("review event result is not in the impact assessment")

    source_state = _find_source_cycle_for_result(old_result.result_id)
    control_id = str(source_state.get("control_id") or "").strip()
    framework = str(source_state.get("framework") or "").strip()
    if not control_id:
        raise ValueError("source result cycle has no control_id")
    if control_id not in set(impact.affected_controls):
        raise ValueError("source control is not affected by the supplied impact assessment")

    evidence = source_state.get("evidence") or {}
    if not evidence:
        raise ValueError("source GovernanceResult has no recoverable bound evidence")

    control_spec = _candidate_control(candidate_requirements, control_id)
    req_text = _requirement_text(control_spec)
    target_req_id = requirement_version_id_for_candidate(
        framework=framework,
        control_id=control_id,
        candidate_version=change.candidate_version,
        control_spec=control_spec,
    )

    case = open_reassessment_case(
        review_event=review_event,
        change=change,
        impact=impact,
        result=old_result,
        store=cases,
    )
    started_event = begin_case_execution(
        case,
        result=old_result,
        state_log=states,
        actor_id=actor_id,
    )

    governance_context = {
        "is_reassessment": True,
        "reassessment_id": case.case_id,
        "trigger_change_id": change.change_id,
        "impact_id": impact.impact_id,
        "source_result_id": old_result.result_id,
        "parent_result_id": old_result.result_id,
        "supersedes_result_id": old_result.result_id,
        "result_version": int(old_result.result_version) + 1,
        "requirement_version_id": target_req_id,
        "source_requirement_version_id": old_result.requirement_version_id,
        "candidate_source_version": change.candidate_version,
        "evidence_set_id": old_result.evidence_set_id,
        "requirement_override": {
            "requirement": req_text,
            "elements": control_spec.get("elements") or [],
        },
    }
    new_cycle_id = cycle.start(
        control_id,
        framework=framework,
        actor=actor_id,
        governance_context=governance_context,
    )
    cycle.bind_evidence(new_cycle_id, evidence, actor=actor_id)

    return {
        "enabled": True,
        "case": case,
        "started_event": started_event,
        "cycle_id": new_cycle_id,
        "control_id": control_id,
        "framework": framework,
        "requirement_version_id": target_req_id,
        "evidence_set_id": old_result.evidence_set_id,
        "governance_context": governance_context,
    }
