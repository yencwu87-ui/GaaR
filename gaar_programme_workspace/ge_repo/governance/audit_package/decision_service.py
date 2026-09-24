"""WB-127: human decision presentation over the existing governed cycle.decide() path.

This module deliberately does not create a second decision engine.  Both single and batch
approval call :func:`core.cycle.decide` after the same decision-time preflight.  Batch mode is
therefore a UX convenience only: every control receives its own decided event, human decision
ID, sealed GovernanceResult, final Quality Gate evaluation and validity-state transition.

Local reviewer IDs are attribution only.  Authentication/RBAC is a separate production gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import events
from core import cycle as governance_cycle
from governance.watcher.store import HashChainStore

SCHEMA = "gaar.human-decision-batch.v1"
DEFAULT_BATCH_STORE = Path(__file__).resolve().parents[1] / "human_decision_batches.jsonl"


class DecisionServiceError(RuntimeError):
    pass


def _truthy(name: str) -> bool:
    return os.environ.get(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _package_fingerprint(state: dict) -> str:
    """Stable decision-target fingerprint; excludes mutable presentation/rationale text."""
    from governance.independent_challenge import fingerprint, proposal_view

    proposal = proposal_view(state.get("proposal") or {})
    ev = state.get("evidence") or {}
    anchors = [
        {k: a.get(k) for k in ("anchor_id", "sha256", "blob_ref", "locator")}
        for a in (ev.get("admitted_anchors") or []) if isinstance(a, dict)
    ]
    value = {
        "cycle_id": state.get("cycle_id"),
        "control_id": state.get("control_id"),
        "proposal": proposal,
        "evidence_set_id": ev.get("evidence_set_id"),
        "anchors": anchors,
        "waiver_policy_sha256": (state.get("blind_read_waiver") or {}).get("policy_sha256"),
    }
    return fingerprint(value)


def preflight(cycle_id: str, *, batch: bool = False) -> dict[str, Any]:
    """Read-only decision-time eligibility check against the authoritative cycle state."""
    state = events.state(cycle_id)
    if not state:
        raise DecisionServiceError(f"cycle not found: {cycle_id}")

    problems: list[str] = []
    if state.get("decision"):
        problems.append("cycle_already_decided")
    if not state.get("proposal"):
        problems.append("assessor_proposal_missing")
    if not state.get("evidence"):
        problems.append("evidence_not_bound")

    from governance.ai_auditor.conductor import ReviewConductor
    inspection = ReviewConductor().inspect(cycle_id)
    if inspection.checkpoint != "HUMAN_DECISION":
        problems.append("core_cycle_checkpoint:" + inspection.checkpoint)
    if inspection.quality_audit and not inspection.quality_audit.ready:
        problems.extend("preflight:" + b for b in inspection.quality_audit.blockers)

    is_routine = bool(state.get("blind_read_waiver"))
    if is_routine:
        from governance.routine_waiver import applied_waiver, eligibility
        if not applied_waiver(state):
            problems.append("routine_waiver_inactive_or_invalid")
        problems.extend("routine:" + x for x in eligibility(state, require_challenge=True))
        from governance.independent_challenge import verify_for_decision
        problems.extend("challenge:" + x for x in verify_for_decision(state))
    elif batch:
        problems.append("nonroutine_individual_review")

    if not _truthy("WB_GAAR_RESULT_ENABLE"):
        problems.append("sealed_result_output_disabled")
    if not _truthy("WB_GAAR_QUALITY_GATE"):
        problems.append("final_quality_gate_disabled")
    try:
        from governance.result_integration import signer_from_env
        signer = signer_from_env()
        signer_key_id = signer.key_id
    except Exception as exc:
        signer_key_id = None
        problems.append("signing_identity_unavailable:" + type(exc).__name__)

    proposal = state.get("proposal") or {}
    sufficiency = str(proposal.get("sufficiency") or "").strip().lower()
    maturity = proposal.get("maturity")
    if sufficiency not in {"full", "partial", "none"}:
        problems.append("proposal_sufficiency_invalid")
    if isinstance(maturity, bool) or not isinstance(maturity, int) or not 0 <= maturity <= 5:
        problems.append("proposal_maturity_invalid")

    return {
        "cycle_id": cycle_id,
        "control_id": state.get("control_id"),
        "framework": state.get("framework"),
        "review_tier": "routine" if is_routine else "individual",
        "batch_eligible": bool(is_routine and not problems),
        "single_eligible": not problems,
        "checkpoint": inspection.checkpoint,
        "proposal": {"sufficiency": sufficiency, "maturity": maturity},
        "package_fingerprint": _package_fingerprint(state) if state.get("proposal") and state.get("evidence") else None,
        "signer_key_id": signer_key_id,
        "blockers": list(dict.fromkeys(problems)),
        "identity_assurance": "LOCAL_ATTRIBUTION_ONLY_NOT_AUTHENTICATED",
    }


def _attestation(cycle_id: str, fingerprint: str, note: str | None) -> str:
    custom = str(note or "").strip()
    if custom:
        return custom
    return (
        f"I reviewed the complete governed audit package for cycle {cycle_id}, including admitted evidence, "
        f"recorded limitations and independent challenge results, and approve the proposed conclusion. "
        f"Package fingerprint {fingerprint[:16]}."
    )


def approve_one(cycle_id: str, *, reviewer_id: str, note: str | None = None) -> dict[str, Any]:
    """One human approval, implemented only by calling the existing cycle.decide()."""
    reviewer = str(reviewer_id or "").strip()
    if not reviewer or reviewer.upper() == "SYSTEM":
        raise DecisionServiceError("a named human reviewer attribution is required; SYSTEM is not a human decision")

    check = preflight(cycle_id, batch=False)
    if not check["single_eligible"]:
        raise DecisionServiceError("decision preflight blocked: " + "; ".join(check["blockers"]))

    # Re-read immediately before the authoritative call so stale UI state cannot be approved.
    state = events.state(cycle_id)
    current_fp = _package_fingerprint(state)
    if current_fp != check["package_fingerprint"]:
        raise DecisionServiceError("audit package changed after decision preflight")
    proposal = state["proposal"]
    reason = _attestation(cycle_id, current_fp, note)

    result = governance_cycle.decide(
        cycle_id,
        sufficiency=str(proposal["sufficiency"]),
        maturity=int(proposal["maturity"]),
        reason=reason,
        reviewer=reviewer,
        action="accept",
    )
    gate = result.get("quality_gate") or {}
    gate_status = gate.get("status")
    published_current = bool(result.get("governance_result") and gate_status != "BLOCKED")
    return {
        "cycle_id": cycle_id,
        "control_id": check["control_id"],
        "reviewer_id": reviewer,
        "human_decision_id": result.get("human_decision_id"),
        "governance_result_id": result.get("governance_result_id"),
        "quality_gate_status": gate_status,
        "published_current": published_current,
        "status": "CURRENT" if published_current else ("BLOCKED_FINALIZED" if gate_status == "BLOCKED" else "DECIDED"),
        "package_fingerprint": current_fp,
        "decision_path": "core.cycle.decide",
        "identity_assurance": "LOCAL_ATTRIBUTION_ONLY_NOT_AUTHENTICATED",
    }


def request_investigation(cycle_id: str, *, reviewer_id: str, note: str) -> dict[str, Any]:
    reviewer = str(reviewer_id or "").strip()
    text = str(note or "").strip()
    if not reviewer or reviewer.upper() == "SYSTEM":
        raise DecisionServiceError("named human reviewer attribution required")
    if len(text) < 25:
        raise DecisionServiceError("investigation request must state the issue to investigate")
    state = events.state(cycle_id)
    if not state or state.get("decision"):
        raise DecisionServiceError("cycle missing or already decided")
    row = governance_cycle.record_note(cycle_id, {
        "audit_package_human_action": "REQUEST_INVESTIGATION",
        "reviewer_id": reviewer,
        "note": text,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, actor=reviewer)
    return {"cycle_id": cycle_id, "status": "INVESTIGATION_REQUESTED", "event_id": row.get("event_id"),
            "governance_result_created": False}


def reject_proposal(cycle_id: str, *, reviewer_id: str, note: str) -> dict[str, Any]:
    """Reject the *proposal*, not decide FAIL. An alternate human judgement is still required."""
    reviewer = str(reviewer_id or "").strip()
    text = str(note or "").strip()
    if not reviewer or reviewer.upper() == "SYSTEM":
        raise DecisionServiceError("named human reviewer attribution required")
    if len(text) < 25:
        raise DecisionServiceError("proposal rejection must explain what evidence or conclusion is disputed")
    state = events.state(cycle_id)
    if not state or state.get("decision"):
        raise DecisionServiceError("cycle missing or already decided")
    row = governance_cycle.record_note(cycle_id, {
        "audit_package_human_action": "REJECT_PROPOSAL",
        "reviewer_id": reviewer,
        "note": text,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, actor=reviewer)
    return {"cycle_id": cycle_id, "status": "PROPOSAL_REJECTED_REQUIRES_HUMAN_JUDGEMENT",
            "event_id": row.get("event_id"), "governance_result_created": False}


def approve_batch(cycle_ids: Iterable[str], *, reviewer_id: str, note: str | None = None,
                  max_batch_size: int = 25) -> dict[str, Any]:
    """Approve eligible routine cycles. Every item calls approve_one(); no bulk decision path exists."""
    ids = [str(x).strip() for x in cycle_ids if str(x).strip()]
    if not ids or len(ids) > max_batch_size or len(set(ids)) != len(ids):
        raise DecisionServiceError(f"batch must contain 1..{max_batch_size} unique cycle IDs")
    reviewer = str(reviewer_id or "").strip()
    if not reviewer or reviewer.upper() == "SYSTEM":
        raise DecisionServiceError("named human reviewer attribution required")

    batch_id = "batch_" + uuid.uuid4().hex
    items: list[dict[str, Any]] = []
    for cid in ids:
        check = preflight(cid, batch=True)
        if not check["batch_eligible"]:
            items.append({"cycle_id": cid, "status": "SKIPPED", "reasons": check["blockers"],
                          "decision_path": None})
            continue
        try:
            out = approve_one(cid, reviewer_id=reviewer, note=note)
            items.append(out)
        except Exception as exc:
            # A last-moment revalidation or final gate may block this one control; continue so
            # batch convenience cannot turn into an all-or-nothing governance side effect.
            items.append({"cycle_id": cid, "status": "BLOCKED", "reasons": [f"{type(exc).__name__}:{exc}"],
                          "decision_path": "core.cycle.decide"})

    summary = {
        "batch_id": batch_id,
        "reviewer_id": reviewer,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requested": len(ids),
        "current": sum(x.get("status") == "CURRENT" for x in items),
        "blocked_finalized": sum(x.get("status") == "BLOCKED_FINALIZED" for x in items),
        "skipped": sum(x.get("status") == "SKIPPED" for x in items),
        "blocked": sum(x.get("status") == "BLOCKED" for x in items),
        "items": items,
        "path_identity": "EVERY_APPROVED_ITEM_CALLS_APPROVE_ONE_THEN_CORE.CYCLE.DECIDE",
        "identity_assurance": "LOCAL_ATTRIBUTION_ONLY_NOT_AUTHENTICATED",
    }
    store = HashChainStore(os.environ.get("WB_GAAR_BATCH_DECISION_STORE", DEFAULT_BATCH_STORE), SCHEMA)
    receipt = store.append("HumanBatchDecisionReceipt", summary)
    summary["receipt_hash"] = receipt["record_hash"]
    return summary
