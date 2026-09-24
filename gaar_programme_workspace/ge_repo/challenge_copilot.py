"""Bounded Copilot for an admitted disagreement challenge.

This assistant does not re-run the challenger and cannot alter challenge strength, support,
sufficiency, maturity, or any governance decision. It explains the already-admitted challenge,
surfaces evidence to verify, and helps the human reviewer formulate questions/notes.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from governance.control_contract import requirement_context
from governance.challenge_pointers import locate_quote, parse_evidence_sources
from inference.orchestrator import run_with_escalation
from inference.policy import signals_for_control

SCHEMA_VERSION = "challenge_copilot.response.1"
ALLOWED_KEYS = {"challenge_explanation", "evidence_to_verify", "questions", "reviewer_note_draft"}
FORBIDDEN_KEYS = {
    "sufficiency", "maturity", "proposedmaturity", "proposed_maturity", "final_decision",
    "decision", "outcome", "verdict", "judgement", "judgment", "disposition", "approval",
    "approve", "reject", "supports", "challenge_strength", "severity", "confidence",
}


def _json_from_text(raw: str) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Challenge Copilot response was not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Challenge Copilot response must be a JSON object")
    if set(value) == {"response"} and isinstance(value.get("response"), dict):
        value = value["response"]
    return value


def _validate_response(value: dict, evidence_text: str) -> dict:
    lowered = {str(k).strip().lower().replace("-", "_"): k for k in value}
    forbidden = sorted(k for k in lowered if k in FORBIDDEN_KEYS)
    if forbidden:
        raise ValueError("prohibited_challenge_copilot_field:" + ",".join(forbidden))
    unknown = sorted(k for k in value if k not in ALLOWED_KEYS)
    if unknown:
        raise ValueError("unknown_challenge_copilot_field:" + ",".join(map(str, unknown)))

    explanation = value.get("challenge_explanation", "")
    draft = value.get("reviewer_note_draft", "")
    if not isinstance(explanation, str) or not isinstance(draft, str):
        raise ValueError("challenge_explanation and reviewer_note_draft must be strings")
    questions = value.get("questions", [])
    if not isinstance(questions, list) or any(not isinstance(x, str) for x in questions):
        raise ValueError("questions must be a list of strings")

    sources = parse_evidence_sources(evidence_text)
    checked: list[dict[str, str]] = []
    evidence = value.get("evidence_to_verify", [])
    if not isinstance(evidence, list):
        raise ValueError("evidence_to_verify must be a list")
    for item in evidence:
        if not isinstance(item, dict) or set(item) - {"locator", "excerpt", "purpose"}:
            raise ValueError("evidence_to_verify items must contain only locator/excerpt/purpose")
        excerpt = str(item.get("excerpt") or "").strip()
        purpose = str(item.get("purpose") or "").strip()
        if excerpt:
            hit = locate_quote(excerpt, sources)
            if not hit:
                raise ValueError("evidence_to_verify excerpt is not verifiable in supplied evidence")
            checked.append({"locator": hit.get("locator", ""), "excerpt": excerpt, "purpose": purpose})
        elif purpose:
            checked.append({"locator": str(item.get("locator") or ""), "excerpt": "", "purpose": purpose})

    return {
        "challenge_explanation": explanation.strip(),
        "evidence_to_verify": checked,
        "questions": [x.strip() for x in questions if x.strip()],
        "reviewer_note_draft": draft.strip(),
    }


def _prompt(control, evidence_text: str, challenge_envelope: dict) -> tuple[str, str]:
    cid = getattr(control, "id", "")
    lib = getattr(control, "lib", "")
    ctx = requirement_context(cid, lib) or {}
    admitted = list(challenge_envelope.get("challenges") or [])
    # Keep only already-governed fields. The Copilot is not allowed to see or invent a hidden
    # rating target; its job is to help the reviewer understand the admitted objection.
    compact = []
    for row in admitted:
        if not isinstance(row, dict):
            continue
        compact.append({
            "element_id": (row.get("requirement_pointer") or {}).get("element_id", ""),
            "requirement": (row.get("requirement_pointer") or {}).get("text", ""),
            "observation": row.get("observation", ""),
            "inference": row.get("inference", ""),
            "challenge": row.get("challenge", ""),
            "anchor_kind": row.get("anchor_kind", "factual_pointer"),
            "factual_pointer": row.get("factual_pointer") or {},
            "absence_pointer": row.get("absence_pointer") or {},
            "reviewer_pointer": row.get("reviewer_pointer") or {},
            "risk_to_address": row.get("risk_to_address", ""),
            "resolution_pointer": row.get("resolution_pointer", ""),
        })
    system = (
        "You are Challenge Copilot for a governed human reviewer. You are shown only challenges "
        "that have already passed deterministic admission. Explain what the admitted challenge is "
        "asking the reviewer to verify and surface relevant evidence/questions. Do NOT decide whether "
        "the challenge is correct. Do NOT output or alter sufficiency, maturity, supports, challenge "
        "strength, severity, confidence, a disposition, approval/rejection, or any governance decision. "
        "Return ONLY JSON matching the supplied schema. Evidence excerpts must be copied verbatim."
    )
    user = json.dumps({
        "task": "help the reviewer understand and respond to the admitted disagreement challenge",
        "control": {"id": cid, "framework": lib, "requirement": str(ctx.get("requirement") or "")},
        "admitted_challenges": compact,
        "evidence": evidence_text[:24000],
        "response_schema": {
            "challenge_explanation": "",
            "evidence_to_verify": [{"locator": "", "excerpt": "", "purpose": ""}],
            "questions": [""],
            "reviewer_note_draft": "",
        },
    }, ensure_ascii=False)
    return system, user


def request(control, evidence: dict, challenge_envelope: dict, *, task_id: str | None = None,
            review_id: str | None = None) -> dict:
    if not (challenge_envelope or {}).get("challenges"):
        raise ValueError("Challenge Copilot requires at least one admitted challenge")
    evidence_text = str((evidence or {}).get("text") or "")
    system, user = _prompt(control, evidence_text, challenge_envelope)
    signals = signals_for_control(control, role="copilot", evidence_chars=len(evidence_text))
    task_id = task_id or f"CHCOP-{uuid.uuid4().hex[:12]}"

    def validate(raw: str):
        try:
            _validate_response(_json_from_text(raw), evidence_text)
            return True, ""
        except ValueError as exc:
            return False, str(exc)

    raw, plan, rec = run_with_escalation(
        role="copilot", system=system, user=user, signals=signals, validate=validate,
        control_id=getattr(control, "id", ""), task_id=task_id, review_id=review_id,
    )
    parsed = _validate_response(_json_from_text(raw), evidence_text)
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": task_id,
        "review_id": review_id,
        "provider": plan.provider,
        "model": plan.model,
        "inference": rec,
        "response": parsed,
    }
