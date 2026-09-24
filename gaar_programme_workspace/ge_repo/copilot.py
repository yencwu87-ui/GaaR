"""Governed Reviewer Copilot.

Copilot is constrained assistance after a reviewer has recorded an initial reading. It is not an
assessor and has no schema fields capable of representing sufficiency, maturity, element verdicts,
or a final governance decision.
"""
from __future__ import annotations

import difflib
import json
import re
import uuid
from typing import Any

from governance.control_contract import requirement_context
from inference.orchestrator import run_with_escalation
from inference.policy import signals_for_control

SCHEMA_VERSION = "copilot.response.1"
ALLOWED_KEYS = {
    "relevant_evidence",
    "requirement_context",
    "evidence_gaps",
    "questions",
    "rationale_draft",
}
FORBIDDEN_KEYS = {
    "sufficiency", "maturity", "proposedmaturity", "proposed_maturity",
    "final_decision", "decision", "outcome", "element_judgement",
    "element_judgements", "element_verdict", "element_verdicts", "verdict",
    "judgement", "judgment", "deciding_rule", "which_rule_decided_it",
    "authoritative_answer", "disposition", "approval", "approve", "reject",
}


def _json_from_text(raw: str) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Copilot response was not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Copilot response must be a JSON object")

    # Ollama may return the model JSON inside a transport envelope such as
    # {"response": {<copilot-schema>}}. Normalize that exact envelope before
    # schema validation; do not silently accept sibling/unknown envelope keys.
    if set(value) == {"response"} and isinstance(value.get("response"), dict):
        value = value["response"]

    # Ollama can emit a single requirement_context object even though the governed schema is a
    # list of objects. Normalize only that transport-shape quirk before strict validation. Other
    # invalid types (string, number, etc.) still fail closed in _validate_response().
    if "requirement_context" in value and isinstance(value["requirement_context"], dict):
        value["requirement_context"] = [value["requirement_context"]]
    return value


def _validate_response(value: dict) -> dict:
    lowered = {str(k).strip().lower().replace("-", "_"): k for k in value}
    forbidden = sorted(key for key in lowered if key in FORBIDDEN_KEYS)
    if forbidden:
        raise ValueError(
            "prohibited_judgement_field:" + ",".join(forbidden)
        )
    unknown = sorted(key for key in value if key not in ALLOWED_KEYS)
    if unknown:
        raise ValueError("unknown_copilot_field:" + ",".join(sorted(map(str, unknown))))

    out: dict[str, Any] = {
        "relevant_evidence": [],
        "requirement_context": [],
        "evidence_gaps": [],
        "questions": [],
        "rationale_draft": "",
    }

    if not isinstance(value.get("relevant_evidence", []), list):
        raise ValueError("relevant_evidence must be a list")
    for item in value.get("relevant_evidence", []):
        if not isinstance(item, dict):
            raise ValueError("relevant_evidence items must be objects")
        if set(item) - {"locator", "excerpt", "relevance"}:
            raise ValueError("relevant_evidence contains unsupported fields")
        if not isinstance(item.get("excerpt", ""), str) or not isinstance(item.get("locator", ""), str):
            raise ValueError("relevant_evidence locator/excerpt must be strings")
        if not isinstance(item.get("relevance", ""), str):
            raise ValueError("relevant_evidence relevance must be a string")
        out["relevant_evidence"].append({
            "locator": item.get("locator", ""),
            "excerpt": item.get("excerpt", ""),
            "relevance": item.get("relevance", ""),
        })

    if not isinstance(value.get("requirement_context", []), list):
        raise ValueError("requirement_context must be a list")
    for item in value.get("requirement_context", []):
        if not isinstance(item, dict):
            raise ValueError("requirement_context items must be objects")
        if set(item) - {"element_id", "text", "note"}:
            raise ValueError("requirement_context contains unsupported fields")
        out["requirement_context"].append({
            "element_id": str(item.get("element_id", "")),
            "text": str(item.get("text", "")),
            "note": str(item.get("note", "")),
        })

    for field in ("evidence_gaps", "questions"):
        value_list = value.get(field, [])
        if not isinstance(value_list, list) or any(not isinstance(x, str) for x in value_list):
            raise ValueError(f"{field} must be a list of strings")
        out[field] = [x.strip() for x in value_list if x.strip()]

    draft = value.get("rationale_draft", "")
    if not isinstance(draft, str):
        raise ValueError("rationale_draft must be a string")
    out["rationale_draft"] = draft.strip()
    return out


def _prompt(control, evidence_text: str) -> tuple[str, str]:
    cid = getattr(control, "id", "")
    lib = getattr(control, "lib", "")
    ctx = requirement_context(cid, lib) or {}
    elements = [
        {"id": str(e.get("id")), "text": str(e.get("text"))}
        for e in (ctx.get("elements") or [])
        if isinstance(e, dict) and e.get("text")
    ]
    system = (
        "You are Reviewer Copilot for a governed human review. "
        "You provide evidence-oriented assistance AFTER the reviewer has already recorded an initial reading. "
        "You are not the reviewer and must not make the reviewer's judgement. "
        "Return ONLY JSON matching the supplied schema. "
        "Do not output sufficiency, maturity, element verdicts, final decisions, approvals, dispositions, "
        "or a statement of which rule decided the review. "
        "A rationale_draft may help the reviewer phrase evidence, but it must remain optional and advisory."
    )
    user = json.dumps({
        "task": "assist the reviewer with evidence and drafting context",
        "control": {"id": cid, "framework": lib, "requirement": str(ctx.get("requirement") or ""),
                    "elements": elements},
        "evidence": evidence_text[:24000],
        "response_schema": {
            "relevant_evidence": [{"locator": "", "excerpt": "", "relevance": ""}],
            "requirement_context": [{"element_id": "", "text": "", "note": ""}],
            "evidence_gaps": [""],
            "questions": [""],
            "rationale_draft": "",
        },
    }, ensure_ascii=False)
    return system, user


def request(control, evidence: dict, *, task_id: str | None = None, review_id: str | None = None) -> dict:
    """Generate one bounded Copilot response. The initial reviewer reading is intentionally not
    passed to the model to avoid turning Copilot into a second source of anchoring."""
    evidence_text = str((evidence or {}).get("text") or "")
    system, user = _prompt(control, evidence_text)
    signals = signals_for_control(
        control,
        role="copilot",
        evidence_chars=len(evidence_text),
    )
    task_id = task_id or f"COP-{uuid.uuid4().hex[:12]}"

    def validate(raw: str):
        try:
            _validate_response(_json_from_text(raw))
            return True, ""
        except ValueError as exc:
            return False, str(exc)

    raw, plan, rec = run_with_escalation(
        role="copilot",
        system=system,
        user=user,
        signals=signals,
        validate=validate,
        control_id=getattr(control, "id", ""),
        task_id=task_id,
        review_id=review_id,
    )
    parsed = _validate_response(_json_from_text(raw))
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": task_id,
        "review_id": review_id,
        "provider": plan.provider,
        "model": plan.model,
        "control_complexity_score": plan.control_complexity_score,
        "control_complexity_band": plan.control_complexity_band,
        "task_complexity_score": plan.complexity_score,
        "task_complexity_band": plan.complexity_band,
        "inference": rec,
        "response": parsed,
    }


def similarity(a: str, b: str) -> float | None:
    a = " ".join(str(a or "").split()).strip().lower()
    b = " ".join(str(b or "").split()).strip().lower()
    if not a or not b:
        return None
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)


def _norm_element_judgements(read: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in (read or {}).get("element_verdicts") or []:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("element_id") or item.get("id") or "").strip()
        if not eid:
            continue
        out[eid] = {k: v for k, v in item.items() if k not in {"element_id", "id"}}
    return out


def compare_readings(initial: dict, final: dict, *, copilot_interaction: bool) -> dict:
    rationale_changed = str(initial.get("reason", "")) != str(final.get("reason", ""))
    suff_changed = initial.get("sufficiency") != final.get("sufficiency")
    mat_changed = initial.get("maturity") != final.get("maturity")
    before = _norm_element_judgements(initial)
    after = _norm_element_judgements(final)
    ids = sorted(set(before) | set(after))
    changed_elements = [eid for eid in ids if before.get(eid) != after.get(eid)]
    similarity_to_latest_draft = None
    return {
        "copilot_present": bool(copilot_interaction),
        "rationale_changed": rationale_changed,
        "sufficiency_changed": suff_changed,
        "maturity_changed": mat_changed,
        "element_judgement_changed": bool(changed_elements),
        "changed_element_ids": changed_elements,
        "rating_changed_after_copilot": bool(copilot_interaction and (suff_changed or mat_changed or changed_elements)),
        "rationale_changed_after_copilot": bool(copilot_interaction and rationale_changed),
        "element_judgement_changed_after_copilot": bool(copilot_interaction and changed_elements),
        "similarity_to_latest_draft": similarity_to_latest_draft,
    }
