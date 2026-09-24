"""Adapter between the existing assessment cycle and the Workstream A result contract.

This is an integration boundary, not a second assessment engine. It derives stable references from
artifacts already recorded by the cycle and seals the resulting GovernanceResult only when the
feature flag explicitly enables it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from governance.result_contract import CanonicalSigner, Decision, GovernanceResult, ProvenanceTrail, create_governance_result
from governance.result_store import ResultStore


def enabled() -> bool:
    return os.environ.get("WB_GAAR_RESULT_ENABLE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _ref(prefix: str, value: Any) -> str:
    return f"{prefix}-{_sha(value)[:32]}"


def signer_from_env() -> CanonicalSigner:
    key_b64 = os.environ.get("WB_GAAR_RESULT_SIGNING_KEY_B64", "").strip()
    key_id = os.environ.get("WB_GAAR_RESULT_KEY_ID", "").strip()
    if not key_b64 or not key_id:
        raise RuntimeError(
            "GaaR result sealing is enabled but WB_GAAR_RESULT_SIGNING_KEY_B64 and "
            "WB_GAAR_RESULT_KEY_ID are not configured"
        )
    try:
        raw = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise RuntimeError("WB_GAAR_RESULT_SIGNING_KEY_B64 is not valid base64") from exc
    if len(raw) != 32:
        raise RuntimeError("WB_GAAR_RESULT_SIGNING_KEY_B64 must decode to a 32-byte Ed25519 seed")
    return CanonicalSigner.from_base64(key_id, key_b64)


def decision_for_sufficiency(sufficiency: str) -> Decision:
    value = str(sufficiency or "").strip().lower()
    return {
        "full": Decision.PASS,
        "partial": Decision.CONDITIONAL_PASS,
        "none": Decision.FAIL,
    }.get(value, None) or Decision.FAIL


def _event_by_kind(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e.get("kind") == kind]


def build_result_inputs(*, cycle_id: str, state: dict, human_decision_id: str, decision_timestamp: str) -> dict[str, Any]:
    control_id = str(state.get("control_id") or "").strip()
    framework = str(state.get("framework") or "").strip()
    if not control_id:
        raise ValueError("cycle has no control_id")

    from core.cycle import _control
    control = _control(control_id, framework)

    governance_context = state.get("governance_context") or {}

    # Transitional RequirementVersion identity. Reassessment may pin an explicit target
    # requirement identity supplied by the governed change workflow; normal cycles retain the
    # existing deterministic local identity.
    requirement_version_id = str(governance_context.get("requirement_version_id") or "").strip() or _ref("REQ", {
        "framework": framework,
        "control_id": control_id,
        "requirement": control.req,
        "maps": control.maps,
    })

    evidence = state.get("evidence") or {}
    # Reassessment deliberately reuses the sealed source result's evidence-set identity when the
    # evidence itself is unchanged. New evidence creates a normal fresh EVID identity.
    evidence_set_id = (str(governance_context.get("evidence_set_id") or "").strip()
                       or str(evidence.get("evidence_set_id") or "").strip()) or _ref("EVID", {
        "cycle_id": cycle_id,
        "evidence": evidence,
    })

    assessment_identity = state.get("assessment_identity") or {}
    assessment_id = str(assessment_identity.get("assessment_id") or "").strip() or _ref(
        "ASSESS", {"cycle_id": cycle_id, "assessment_identity": assessment_identity, "proposal": state.get("proposal")}
    )

    challenge_events = [e for e in (state.get("_events") or [])
                        if e.get("kind") in {"challenged", "independent_challenged"}]
    challenge_set_id = _ref("CHALL", {
        "cycle_id": cycle_id,
        "challenge_event_ids": [e.get("event_id") for e in challenge_events],
        "challenges": state.get("challenges") or [],
    })

    proposal = state.get("proposal") or {}
    model_version = str(state.get("proposal_model") or proposal.get("model") or "unknown")
    retrieval = evidence.get("retrieval") or {}
    retrieval_receipt_id = _ref("RETR", retrieval) if retrieval else None

    cycle_events = state.get("_events") or []
    proposal_event = next(iter(reversed(_event_by_kind(cycle_events, "proposed"))), None)
    model_invocation_id = str((proposal_event or {}).get("event_id") or f"cycle:{cycle_id}:proposal")

    prompt_version = str(
        ((assessment_identity.get("artefact_sha256") or {}).get("assessor.py"))
        or assessment_identity.get("engine_version")
        or "assessor-unversioned"
    )

    workflow_step_timestamps = {}
    for e in cycle_events:
        kind = e.get("kind")
        if kind in {"cycle_started", "evidence_bound", "proposed", "read", "compared", "blind_read_waived", "challenged", "independent_challenged", "decided"}:
            workflow_step_timestamps.setdefault(kind, str(e.get("ts") or ""))

    provenance = ProvenanceTrail(
        requirement_version_id=requirement_version_id,
        evidence_set_id=evidence_set_id,
        assessment_id=assessment_id,
        challenge_set_id=challenge_set_id,
        human_decision_id=human_decision_id,
        assessor_prompt_version=prompt_version,
        model_version=model_version,
        model_invocation_id=model_invocation_id,
        human_decider_id=str(state.get("decided_by") or ""),
        human_decision_timestamp=decision_timestamp,
        workflow_step_timestamps=workflow_step_timestamps,
        rule_versions={
            "result_contract": "gaar.result.v1",
            "cycle_engine": "wb042",
            **({"investigation_id": str(governance_context["investigation_id"]),
                "investigation_head": str(governance_context.get("investigation_head") or ""),
                "investigation_contract": "wb140.1"}
               if governance_context.get("investigation_id") else {}),
            **({"routine_blind_read_waiver": str(state["blind_read_waiver"]["policy_sha256"])}
               if state.get("blind_read_waiver") else {}),
            "evidence_intelligence": str(retrieval.get("schema") or "legacy"),
            **({"reassessment_case": str(governance_context.get("reassessment_id"))}
               if governance_context.get("reassessment_id") else {}),
            **({"governance_change": str(governance_context.get("trigger_change_id"))}
               if governance_context.get("trigger_change_id") else {}),
        },
        retrieval_receipt_id=retrieval_receipt_id,
        retrieval_pipeline_version=str(retrieval.get("schema") or "legacy"),
    )

    return {
        "requirement_version_id": requirement_version_id,
        "evidence_set_id": evidence_set_id,
        "assessment_id": assessment_id,
        "challenge_set_id": challenge_set_id,
        "human_decision_id": human_decision_id,
        "decision": decision_for_sufficiency(((state.get("decision") or {}).get("sufficiency")) or ""),
        "rationale": str(((state.get("decision") or {}).get("reason")) or ""),
        "provenance": provenance,
        "result_version": int(governance_context.get("result_version") or 1),
        "parent_result_id": governance_context.get("parent_result_id"),
        "supersedes_result_id": governance_context.get("supersedes_result_id"),
    }


def compile_for_decision(
    *,
    cycle_id: str,
    state: dict,
    decision_payload: dict[str, Any],
    human_decision_id: str,
    decision_timestamp: str,
    signer: CanonicalSigner,
) -> GovernanceResult:
    """Create a sealed result from the authoritative human decision boundary."""
    state_for_result = dict(state)
    state_for_result["decision"] = decision_payload
    state_for_result["decided_by"] = decision_payload.get("reviewer") or state.get("decided_by")
    # The existing event store doesn't expose its raw events in its projection. The caller can
    # attach them here without changing the canonical state projection.
    state_for_result["_events"] = state_for_result.get("_events") or []
    inputs = build_result_inputs(
        cycle_id=cycle_id,
        state=state_for_result,
        human_decision_id=human_decision_id,
        decision_timestamp=decision_timestamp,
    )
    return create_governance_result(signer=signer, **inputs)


def persist_and_set_current(
    result: GovernanceResult, *, actor_id: str, decision_id: str,
    governance_context: dict[str, Any] | None = None, cycle_id: str | None = None,
) -> dict[str, Any]:
    """Persist a result and project its human-governed validity transition.

    Normal decisions use FINALIZED -> CURRENT.  A reassessment replacement uses the same human
    decision boundary to atomically append R1 REASSESSING -> SUPERSEDED and R2 FINALIZED ->
    CURRENT; D never manufactures a governance decision on its own.
    """
    result_store_path = os.environ.get("WB_GAAR_RESULT_STORE", "").strip()
    store = ResultStore(result_store_path) if result_store_path else ResultStore()
    # WB140 is an independent boundary: disabling the older optional quality gate
    # cannot bypass a missing or invalid investigation.
    from governance.investigation.bridge import required as investigation_required, cycle_gate
    investigation_state = {"governance_context": governance_context or {}}
    if cycle_id:
        import events as investigation_events
        investigation_state = investigation_events.state(cycle_id) or investigation_state
    investigation_gate = None
    if investigation_required(investigation_state):
        investigation_gate = cycle_gate(investigation_state)
        if not investigation_gate["assessment_finalizable"]:
            return {"result": result, "state_event": None, "quality_gate": None,
                    "investigation_gate": investigation_gate, "blocked": True}
        signed_refs = result.provenance.rule_versions
        if signed_refs.get("investigation_id") != investigation_gate["investigation_id"] or signed_refs.get("investigation_head") != investigation_gate["head"]:
            return {"result": result, "state_event": None, "quality_gate": None,
                    "investigation_gate": {**investigation_gate, "assessment_finalizable": False,
                        "deployment_authorized": False, "blockers": ["result_does_not_seal_investigation_head"]}, "blocked": True}
        if investigation_gate.get("verdict") != "PASS" and result.decision.value != "FAIL":
            return {"result": result, "state_event": None, "quality_gate": None,
                    "investigation_gate": {**investigation_gate, "assessment_finalizable": False,
                        "deployment_authorized": False, "blockers": ["result_verdict_conflicts_with_investigation"]}, "blocked": True}
    store.append(result)

    # WB-116: a sealed human-decided result may exist while still being blocked from
    # becoming CURRENT. The quality gate never changes the control verdict; it only
    # decides whether the result package is FINALIZABLE. Disabled by default.
    gate_outcome = None
    try:
        from governance.quality_gate import enabled as quality_gate_enabled, evaluate as evaluate_quality_gate, QualityGateLog
        if quality_gate_enabled():
            if not cycle_id:
                raise RuntimeError("WB-116 quality gate requires cycle_id")
            threshold = float(os.environ.get("WB_GAAR_QUALITY_EVIDENCE_THRESHOLD", "0.70"))
            min_sources = int(os.environ.get("WB_GAAR_QUALITY_MIN_SOURCES", "1"))
            gate_outcome = QualityGateLog().append(evaluate_quality_gate(
                cycle_id=cycle_id, result=result, evidence_threshold=threshold, min_sources=min_sources))
            if gate_outcome.status.value != "FINALIZABLE":
                return {"result": result, "state_event": None, "quality_gate": gate_outcome, "blocked": True}
    except Exception:
        if os.environ.get("WB_GAAR_QUALITY_GATE", "0").strip().lower() in {"1","true","yes","on"}:
            raise

    from governance.result_contract import ResultStateLog, approve_result
    state_store_path = os.environ.get("WB_GAAR_RESULT_STATE_STORE", "").strip()
    state_log = ResultStateLog(state_store_path) if state_store_path else ResultStateLog()
    ctx = governance_context or {}
    old_result_id = str(ctx.get("supersedes_result_id") or "").strip()
    if ctx.get("is_reassessment") and old_result_id:
        from governance.result_contract import ValidityState, supersede_reassessing_result
        old_result = next((x for x in store.read() if x.result_id == old_result_id), None)
        if old_result is None:
            raise RuntimeError(f"reassessment source result not found: {old_result_id}")
        if state_log.current_state(old_result.result_id) != ValidityState.REASSESSING:
            raise RuntimeError("reassessment source result is not REASSESSING at decision boundary")
        old_event, new_event = supersede_reassessing_result(
            old_result, result, actor_id=actor_id, decision_id=decision_id,
            reason="Human reassessment approved replacement GovernanceResult",
            old_prev_hash=state_log.last_hash(),
        )
        state_log.append(old_event)
        state_log.append(new_event)
        return {"result": result, "state_event": new_event, "superseded_event": old_event, "quality_gate": gate_outcome,
                "investigation_gate": investigation_gate, "deployment_authorized": bool((investigation_gate or {}).get("deployment_authorized")), "blocked": False}

    event = approve_result(
        result,
        actor_id=actor_id,
        decision_id=decision_id,
        reason="Human governance decision recorded at the assessment boundary",
        prev_hash=state_log.last_hash(),
    )
    state_log.append(event)
    return {"result": result, "state_event": event, "quality_gate": gate_outcome,
            "investigation_gate": investigation_gate, "deployment_authorized": bool((investigation_gate or {}).get("deployment_authorized")), "blocked": False}
