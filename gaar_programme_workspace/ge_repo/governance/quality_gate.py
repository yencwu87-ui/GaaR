"""WB-116 Governance Result Quality Gate.

The gate answers one question only: is a sealed, human-decided GovernanceResult
complete and trustworthy enough to become CURRENT?  It does not re-rate a control.
Gate outcomes are append-only and separate from immutable GovernanceResult content.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

import events
from governance.ai_auditor.conductor import ReviewConductor
from governance.ai_auditor.skills import evidence_examiner
from governance.ai_auditor.schemas import EvidenceExaminerInput
from governance.result_contract import GovernanceResult

DEFAULT_LOG = Path(__file__).resolve().parent / "quality_gate_events.jsonl"
GENESIS = "0" * 64


class GateStatus(str, Enum):
    FINALIZABLE = "FINALIZABLE"
    BLOCKED = "BLOCKED"


class GateDimension(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    passed: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class QualityGateOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: str = "gaar.quality-gate.v1"
    gate_id: str
    cycle_id: str
    result_id: str
    status: GateStatus
    evidence: GateDimension
    reasoning: GateDimension
    governance: GateDimension
    provenance: GateDimension
    blockers: list[str] = Field(default_factory=list)
    evaluated_at: str
    prev_hash: str
    record_hash: str
    investigation: dict[str, Any] = Field(default_factory=dict)
    deployment_authorized: bool = False


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _sources(ev: dict) -> set[str]:
    out: set[str] = set()
    for item in ev.get("chunks") or []:
        if not isinstance(item, dict):
            continue
        for key in ("source_id", "source", "document_id", "file", "path"):
            val = str(item.get(key) or "").strip()
            if val:
                out.add(val)
                break
    top = str(ev.get("source_id") or ev.get("source") or "").strip()
    if top:
        out.add(top)
    # Plain-text evidence is still a valid single evidence source.
    if not out and str(ev.get("text") or "").strip():
        out.add("bound-evidence")
    return out


def _dimension(passed: bool, checks: dict[str, bool], reasons: list[str], **metrics: Any) -> GateDimension:
    return GateDimension(passed=passed, checks=checks, reasons=reasons, metrics=metrics)


def evaluate(*, cycle_id: str, result: GovernanceResult, evidence_threshold: float = 0.70,
             min_sources: int = 1) -> QualityGateOutcome:
    state = events.state(cycle_id)
    if not state:
        raise ValueError(f"cycle not found: {cycle_id}")

    conductor = ReviewConductor()
    control = conductor._control(state)
    ev = state.get("evidence") or {}
    elems = conductor._req_elements(control, state)
    req_vid = str((state.get("governance_context") or {}).get("requirement_version_id") or result.requirement_version_id)
    evid = str((state.get("governance_context") or {}).get("evidence_set_id") or result.evidence_set_id)
    evidence_report = evidence_examiner.run(EvidenceExaminerInput(
        control_id=state.get("control_id", ""), framework=state.get("framework", ""),
        requirement_version_id=req_vid, evidence_set_id=evid,
        requirement_context=elems, evidence_text=str(ev.get("text") or ""), evidence_age_days=ev.get("age_days"),
    ), threshold=evidence_threshold, max_age_days=conductor.policy.freshness_max_age_days)
    sources = _sources(ev)
    examiner_evaluated = evidence_report.evaluation_status == "EVALUATED"
    threshold_passed = bool(
        examiner_evaluated
        and evidence_report.sufficiency_score is not None
        and evidence_report.sufficiency_score >= evidence_threshold
    )
    evidence_checks = {
        "evidence_bound": bool(str(ev.get("text") or "").strip() or ev.get("chunks")),
        "governed_elements_evaluated": examiner_evaluated,
        "sufficiency_threshold": threshold_passed,
        "source_floor": len(sources) >= max(1, int(min_sources)),
    }
    evidence_reasons = list(evidence_report.open_evidence_gaps)
    if not evidence_checks["source_floor"]:
        evidence_reasons.append(f"evidence_source_count={len(sources)} below policy floor={min_sources}")
    evidence_dim = _dimension(all(evidence_checks.values()), evidence_checks, evidence_reasons,
                              sufficiency_score=evidence_report.sufficiency_score,
                              threshold=evidence_threshold, source_count=len(sources), freshness=evidence_report.evidence_freshness)

    from governance.investigation.bridge import required as investigation_required, cycle_gate
    investigation = cycle_gate(state) if investigation_required(state) else {}
    if investigation_required(state):
        # Coverage is not understanding. Signed scoped examination can legitimately
        # conclude ADVERSE; the journal gate checks process, not favorable outcome.
        checks = {"signed_investigation_complete": bool(investigation.get("assessment_finalizable"))}
        evidence_dim = _dimension(all(checks.values()), checks, list(investigation.get("blockers", [])))

    proposal = state.get("proposal") or {}
    # WB-125: comparison may be replaced only by a still-active signed waiver
    # whose eligibility is rechecked against this actual cycle (not UI claims).
    from governance.routine_waiver import applied_waiver, eligibility
    routine_waiver_ok = bool(state.get("blind_read_waiver") and applied_waiver(state)
                             and not eligibility(state, require_challenge=True))
    reasoning_checks = {
        "assessment_present": bool(proposal),
        "rationale_present": bool(str(proposal.get("rationale") or proposal.get("reason") or "").strip()),
        "maturity_present": proposal.get("maturity") is not None,
        "sufficiency_present": bool(str(proposal.get("sufficiency") or "").strip()),
        "comparison_or_valid_routine_waiver": bool(state.get("diff")) or routine_waiver_ok,
    }
    reasoning_reasons = [k for k, ok in reasoning_checks.items() if not ok]
    reasoning_dim = _dimension(all(reasoning_checks.values()), reasoning_checks, reasoning_reasons)

    challenges = [x for x in (state.get("challenges") or []) if isinstance(x, dict)]
    blocked = 0
    strong = 0
    for env in challenges:
        if env.get("blocked") or env.get("validation_error") or env.get("validation_status") == "blocked":
            blocked += 1
        for ch in env.get("challenges") or []:
            if isinstance(ch, dict) and str(ch.get("challenge_strength") or ch.get("strength") or "").lower() == "strong":
                if not ch.get("resolved"):
                    strong += 1
    governance_checks = {
        "human_decision_present": bool(state.get("decision")),
        "no_blocked_challenge": blocked == 0,
        "no_unresolved_strong_challenge": strong == 0,
    }
    governance_reasons = []
    if blocked: governance_reasons.append(f"blocked_challenge_runs={blocked}")
    if strong: governance_reasons.append(f"unresolved_strong_challenges={strong}")
    if not state.get("decision"): governance_reasons.append("human_decision_missing")
    governance_dim = _dimension(all(governance_checks.values()), governance_checks, governance_reasons,
                               blocked_challenges=blocked, unresolved_strong_challenges=strong)

    seal_ok = True
    seal_reason = []
    try:
        result.validate_internal_consistency()
    except Exception as exc:
        seal_ok = False
        seal_reason.append(f"seal_invalid:{type(exc).__name__}:{exc}")
    prov = result.provenance
    provenance_checks = {
        "seal_valid": seal_ok,
        "human_decision_link": bool(result.human_decision_id) and result.human_decision_id == prov.human_decision_id,
        "requirement_link": result.requirement_version_id == prov.requirement_version_id,
        "evidence_link": result.evidence_set_id == prov.evidence_set_id,
        "assessment_link": result.assessment_id == prov.assessment_id,
        "challenge_link": result.challenge_set_id == prov.challenge_set_id,
        "human_decider_present": bool(str(prov.human_decider_id).strip()),
    }
    provenance_reasons = seal_reason + [k for k, ok in provenance_checks.items() if not ok]
    provenance_dim = _dimension(all(provenance_checks.values()), provenance_checks, provenance_reasons)

    dims = {"evidence": evidence_dim, "reasoning": reasoning_dim, "governance": governance_dim, "provenance": provenance_dim}
    blockers: list[str] = []
    for name, dim in dims.items():
        if not dim.passed:
            blockers.extend([f"{name}:{r}" for r in (dim.reasons or ["failed"])])
    status = GateStatus.FINALIZABLE if not blockers else GateStatus.BLOCKED
    evaluated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    gate_id = _hash({"cycle_id": cycle_id, "result_id": result.result_id, "evaluated_at": evaluated_at})[:32]
    return QualityGateOutcome(
        gate_id=gate_id, cycle_id=cycle_id, result_id=result.result_id, status=status,
        evidence=evidence_dim, reasoning=reasoning_dim, governance=governance_dim, provenance=provenance_dim,
        blockers=blockers, evaluated_at=evaluated_at, prev_hash=GENESIS, record_hash="0"*64,
        investigation=investigation, deployment_authorized=bool(investigation.get("deployment_authorized")),
    )


class QualityGateLog:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("WB_GAAR_QUALITY_GATE_STORE", DEFAULT_LOG))

    def last_hash(self) -> str:
        if not self.path.exists(): return GENESIS
        last = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip(): last = json.loads(line)
        return (last or {}).get("record_hash", GENESIS)

    def append(self, outcome: QualityGateOutcome) -> QualityGateOutcome:
        prev = self.last_hash()
        body = outcome.model_dump(mode="json")
        body["prev_hash"] = prev
        body["record_hash"] = "0"*64
        body["record_hash"] = _hash({k:v for k,v in body.items() if k != "record_hash"})
        final = QualityGateOutcome.model_validate(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_canon(final.model_dump(mode="json")) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        return final

    def read(self) -> list[QualityGateOutcome]:
        if not self.path.exists(): return []
        out=[]; prev=GENESIS
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            raw=json.loads(line)
            if raw.get("prev_hash") != prev: raise ValueError("quality gate chain is broken")
            expected=_hash({k:v for k,v in raw.items() if k != "record_hash"})
            if raw.get("record_hash") != expected: raise ValueError("quality gate record hash is invalid")
            row=QualityGateOutcome.model_validate(raw); out.append(row); prev=row.record_hash
        return out

    def latest_for_result(self, result_id: str) -> QualityGateOutcome | None:
        rows=[x for x in self.read() if x.result_id == result_id]
        return rows[-1] if rows else None


def enabled() -> bool:
    return os.environ.get("WB_GAAR_QUALITY_GATE", "0").strip().lower() in {"1","true","yes","on"}
