"""GaaR Workstream C — Governance Change Intelligence.

This module turns a versioned governance-source change into a first-class, auditable
``GovernanceChange`` and ``ImpactAssessment`` without changing governance state directly.

Design rules:
- Source authority is established from explicit metadata, not semantic similarity or keywords.
- A source may be informational, supervisory/contextual, or binding; the module never infers
  legal force from prose such as ``shall``.
- A detected change is a candidate for impact, not an automatic control failure.
- REVIEW_REQUIRED is emitted as a SYSTEM-triggered state event only after an explicit impact
  assessment says the existing result set is affected. Human decisions are still required for
  finalisation/supersession.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping, Sequence

from governance.result_contract import GovernanceResult, StateTransitionEvent, mark_review_required
from governance.triangulation import SourceState


SCHEMA_VERSION = "gaar.governance-change.v1"
IMPACT_SCHEMA_VERSION = "gaar.impact-assessment.v1"


class AuthorityClass(str, Enum):
    BINDING = "BINDING"
    SUPERVISORY_EXPECTATION = "SUPERVISORY_EXPECTATION"
    GUIDANCE = "GUIDANCE"
    CONSULTATION = "CONSULTATION"
    INDUSTRY_CONTEXT = "INDUSTRY_CONTEXT"
    BACKGROUND = "BACKGROUND"


class ChangeStatus(str, Enum):
    AWARENESS_ONLY = "AWARENESS_ONLY"
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"
    CHANGE_CANDIDATE = "CHANGE_CANDIDATE"


class ImpactDecision(str, Enum):
    NO_MATERIAL_IMPACT = "NO_MATERIAL_IMPACT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ChangeType(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"


@dataclass(frozen=True)
class AuthorityEvidence:
    """Explicit authority metadata required before a source can affect governance state."""

    issuer: str
    jurisdiction: str
    legal_basis: str
    enforcement_status: str
    applicability: str
    applicable: bool

    def validate(self) -> None:
        missing = [
            name for name, value in asdict(self).items()
            if name != "applicable" and not str(value).strip()
        ]
        if missing:
            raise ValueError("authority metadata incomplete: " + ", ".join(missing))


@dataclass(frozen=True)
class SourceAuthorityAssessment:
    source_id: str
    authority_class: AuthorityClass
    effective: bool
    governance_impact_eligible: bool
    canonical_requiredness_eligible: bool
    reasons: tuple[str, ...]
    metadata: AuthorityEvidence

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["authority_class"] = self.authority_class.value
        return raw


@dataclass(frozen=True)
class RequirementChange:
    control_id: str
    change_type: ChangeType
    before_hash: str | None
    after_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["change_type"] = self.change_type.value
        return raw


@dataclass(frozen=True)
class GovernanceChange:
    change_id: str
    schema_version: str
    source_id: str
    source_title: str
    source_reference: str | None
    authority: SourceAuthorityAssessment
    baseline_version: str
    candidate_version: str
    effective_from: str | None
    detected_on: str
    applicability: str
    changed_requirements: tuple[RequirementChange, ...]
    status: ChangeStatus

    @property
    def changed_control_ids(self) -> tuple[str, ...]:
        return tuple(x.control_id for x in self.changed_requirements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_title": self.source_title,
            "source_reference": self.source_reference,
            "authority": self.authority.to_dict(),
            "baseline_version": self.baseline_version,
            "candidate_version": self.candidate_version,
            "effective_from": self.effective_from,
            "detected_on": self.detected_on,
            "applicability": self.applicability,
            "changed_requirements": [x.to_dict() for x in self.changed_requirements],
            "status": self.status.value,
        }


@dataclass(frozen=True)
class ImpactAssessment:
    impact_id: str
    schema_version: str
    change_id: str
    decision: ImpactDecision
    affected_controls: tuple[str, ...]
    affected_result_ids: tuple[str, ...]
    materiality_by_control: Mapping[str, str]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "impact_id": self.impact_id,
            "schema_version": self.schema_version,
            "change_id": self.change_id,
            "decision": self.decision.value,
            "affected_controls": list(self.affected_controls),
            "affected_result_ids": list(self.affected_result_ids),
            "materiality_by_control": dict(self.materiality_by_control),
            "reasons": list(self.reasons),
        }


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _control_hash(control: Any) -> str:
    return _sha(control)


def _authority_class(normative_status: str) -> AuthorityClass:
    value = str(normative_status or "").strip().lower()
    return {
        "binding": AuthorityClass.BINDING,
        "supervisory": AuthorityClass.SUPERVISORY_EXPECTATION,
        "guidance": AuthorityClass.GUIDANCE,
        "consultation": AuthorityClass.CONSULTATION,
        "industry": AuthorityClass.INDUSTRY_CONTEXT,
        "voluntary": AuthorityClass.INDUSTRY_CONTEXT,
        "internal": AuthorityClass.BACKGROUND,
    }.get(value, AuthorityClass.BACKGROUND)


def assess_source_authority(
    source: SourceState,
    *,
    metadata: AuthorityEvidence,
    as_of: str,
) -> SourceAuthorityAssessment:
    """Classify authority using explicit registry metadata and explicit authority evidence.

    ``governance_impact_eligible`` means the source may create a governed review trigger.
    ``canonical_requiredness_eligible`` is stricter and is true only for explicitly binding,
    effective sources with complete metadata. Supervisory expectations may trigger review, but
    they do not become binding requirements through this module.
    """
    metadata.validate()
    asof = date.fromisoformat(as_of)
    cls = _authority_class(source.normative_status)
    reasons: list[str] = []

    effective = source.is_live_on(asof)
    if not effective:
        if source.effective_from and asof < date.fromisoformat(source.effective_from):
            reasons.append("source is not yet effective")
        else:
            reasons.append("source is not currently effective")
    if not metadata.applicable:
        reasons.append("source applicability does not match the governed scope")

    if source.normative_status == "binding" and cls == AuthorityClass.BINDING:
        reasons.append("registry marks the source as binding")
    elif source.normative_status == "supervisory":
        reasons.append("registry marks the source as supervisory expectation")
    else:
        reasons.append("source is not classified as binding or supervisory")

    governance_eligible = bool(
        metadata.applicable
        and effective
        and cls in {AuthorityClass.BINDING, AuthorityClass.SUPERVISORY_EXPECTATION}
    )
    canonical_requiredness = bool(
        metadata.applicable
        and effective
        and cls == AuthorityClass.BINDING
    )
    if governance_eligible:
        reasons.append("source is eligible to generate a governance-impact candidate")
    else:
        reasons.append("source cannot automatically affect governance state")

    return SourceAuthorityAssessment(
        source_id=source.source_id,
        authority_class=cls,
        effective=effective,
        governance_impact_eligible=governance_eligible,
        canonical_requiredness_eligible=canonical_requiredness,
        reasons=tuple(reasons),
        metadata=metadata,
    )


def detect_governance_change(
    current_requirements: Mapping[str, Any],
    candidate_requirements: Mapping[str, Any],
    *,
    source: SourceState,
    authority: SourceAuthorityAssessment,
    detected_on: str,
    applicability: str,
) -> GovernanceChange:
    """Compare requirement versions and create a change candidate.

    This function never mutates the live requirement set and never changes GovernanceResult state.
    """
    current_controls = current_requirements.get("controls") or {}
    candidate_controls = candidate_requirements.get("controls") or {}
    changes: list[RequirementChange] = []

    for control_id in sorted(set(current_controls) | set(candidate_controls)):
        if control_id not in current_controls:
            changes.append(RequirementChange(
                control_id=control_id,
                change_type=ChangeType.ADDED,
                before_hash=None,
                after_hash=_control_hash(candidate_controls[control_id]),
            ))
        elif control_id not in candidate_controls:
            changes.append(RequirementChange(
                control_id=control_id,
                change_type=ChangeType.REMOVED,
                before_hash=_control_hash(current_controls[control_id]),
                after_hash=None,
            ))
        elif current_controls[control_id] != candidate_controls[control_id]:
            changes.append(RequirementChange(
                control_id=control_id,
                change_type=ChangeType.CHANGED,
                before_hash=_control_hash(current_controls[control_id]),
                after_hash=_control_hash(candidate_controls[control_id]),
            ))

    if not changes:
        status = ChangeStatus.AWARENESS_ONLY
    elif authority.governance_impact_eligible:
        status = ChangeStatus.CHANGE_CANDIDATE
    elif source.effective_from and date.fromisoformat(detected_on) < date.fromisoformat(source.effective_from):
        status = ChangeStatus.NOT_YET_EFFECTIVE
    else:
        status = ChangeStatus.AWARENESS_ONLY

    identity = {
        "schema_version": SCHEMA_VERSION,
        "source_id": source.source_id,
        "source_sha": source.content_sha256,
        "baseline_version": str(current_requirements.get("version", "")),
        "candidate_version": str(candidate_requirements.get("version", "")),
        "changes": [x.to_dict() for x in changes],
        "effective_from": source.effective_from,
        "applicability": applicability,
    }
    change_id = f"GC-{_sha(identity)[:32]}"

    return GovernanceChange(
        change_id=change_id,
        schema_version=SCHEMA_VERSION,
        source_id=source.source_id,
        source_title=source.title,
        source_reference=source.source_uri,
        authority=authority,
        baseline_version=str(current_requirements.get("version", "")),
        candidate_version=str(candidate_requirements.get("version", "")),
        effective_from=source.effective_from,
        detected_on=detected_on,
        applicability=applicability,
        changed_requirements=tuple(changes),
        status=status,
    )


def assess_impact(
    change: GovernanceChange,
    *,
    results: Sequence[GovernanceResult],
    current_requirement_version_ids: Mapping[str, str],
    control_materiality: Mapping[str, str] | None = None,
) -> ImpactAssessment:
    """Map changed controls to existing GovernanceResults.

    Materiality is a transparent policy input. This function does not use model confidence or
    semantic similarity, and it does not produce FAIL/CONDITIONAL_PASS decisions.
    """
    materiality_policy = {str(k): str(v).upper() for k, v in (control_materiality or {}).items()}
    changed = tuple(sorted(change.changed_control_ids))
    affected_result_ids: list[str] = []
    materiality: dict[str, str] = {}
    reasons: list[str] = []

    result_by_req: dict[str, list[str]] = {}
    for result in results:
        result_by_req.setdefault(result.requirement_version_id, []).append(result.result_id)

    for control_id in changed:
        ids = result_by_req.get(str(current_requirement_version_ids.get(control_id) or ""), [])
        affected_result_ids.extend(ids)
        materiality[control_id] = materiality_policy.get(control_id, "MEDIUM")
        if ids:
            reasons.append(f"{control_id}: existing GovernanceResult(s) are linked to the changed requirement")
        else:
            reasons.append(f"{control_id}: no existing GovernanceResult found for the current requirement version")

    affected_result_ids = sorted(set(affected_result_ids))

    if change.status != ChangeStatus.CHANGE_CANDIDATE:
        decision = ImpactDecision.NO_MATERIAL_IMPACT
        reasons.append(f"change status {change.status.value} does not permit automatic governance-state impact")
    elif affected_result_ids:
        decision = ImpactDecision.REVIEW_REQUIRED
        reasons.append("affected finalized/current governance results require reassessment review")
    else:
        decision = ImpactDecision.NO_MATERIAL_IMPACT
        reasons.append("no existing GovernanceResult is mapped to the changed requirements")

    identity = {
        "schema_version": IMPACT_SCHEMA_VERSION,
        "change_id": change.change_id,
        "decision": decision.value,
        "affected_controls": changed,
        "affected_result_ids": affected_result_ids,
        "materiality": materiality,
    }
    impact_id = f"IA-{_sha(identity)[:32]}"
    return ImpactAssessment(
        impact_id=impact_id,
        schema_version=IMPACT_SCHEMA_VERSION,
        change_id=change.change_id,
        decision=decision,
        affected_controls=changed,
        affected_result_ids=tuple(affected_result_ids),
        materiality_by_control=materiality,
        reasons=tuple(reasons),
    )


def build_review_required_events(
    change: GovernanceChange,
    impact: ImpactAssessment,
    *,
    results: Sequence[GovernanceResult],
    current_result_ids: set[str] | None = None,
    actor_id: str = "governance-change-engine",
    prev_hash: str = "0" * 64,
) -> tuple[StateTransitionEvent, ...]:
    """Create system-triggered CURRENT -> REVIEW_REQUIRED events.

    The events carry ``trigger_id=GovernanceChange.change_id`` and deliberately leave
    ``decision_id`` empty: no human decision has happened at this point.
    """
    if impact.decision != ImpactDecision.REVIEW_REQUIRED:
        return ()
    result_by_id = {x.result_id: x for x in results}
    events: list[StateTransitionEvent] = []
    chain = prev_hash
    active_ids = set(current_result_ids) if current_result_ids is not None else None
    for result_id in impact.affected_result_ids:
        if active_ids is not None and result_id not in active_ids:
            continue
        result = result_by_id.get(result_id)
        if not result:
            continue
        event = mark_review_required(
            result,
            actor_id=actor_id,
            trigger_id=change.change_id,
            reason=(
                f"GovernanceChange {change.change_id} affects requirement version "
                f"{change.candidate_version} for {len(impact.affected_controls)} control(s)"
            ),
            prev_hash=chain,
        )
        events.append(event)
        chain = event.event_hash
    return tuple(events)
