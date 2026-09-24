from __future__ import annotations

import json
import re
import uuid

from governance.challenge_pointers import locate_quote, parse_evidence_sources
from inference.orchestrator import run_with_escalation
from inference.policy import signals_for_control

from ..schemas import ControlNarrativeInput, ControlNarrativeOutput

_FORBIDDEN = {
    "sufficiency", "maturity", "decision", "final_decision", "verdict", "outcome", "approval",
    "approve", "reject", "supports", "challenge_strength", "compliance", "rating", "score",
}
_ALLOWED = {"narrative", "evidence_anchors", "demonstrates", "limitations"}


def _parse(raw: str) -> dict:
    txt = str(raw or "").strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt, flags=re.I)
        txt = re.sub(r"\s*```$", "", txt)
    value = json.loads(txt)
    if set(value) == {"response"} and isinstance(value.get("response"), dict):
        value = value["response"]
    if not isinstance(value, dict):
        raise ValueError("Control Narrative response must be a JSON object")
    return value


def validate(value: dict, evidence_text: str) -> ControlNarrativeOutput:
    lowered = {str(k).strip().lower().replace("-", "_") for k in value}
    bad = sorted(lowered & _FORBIDDEN)
    if bad:
        raise ValueError("prohibited_control_narrative_field:" + ",".join(bad))
    unknown = sorted(set(value) - _ALLOWED)
    if unknown:
        raise ValueError("unknown_control_narrative_field:" + ",".join(map(str, unknown)))
    anchors = value.get("evidence_anchors", [])
    if not isinstance(anchors, list):
        raise ValueError("evidence_anchors must be a list")
    sources = parse_evidence_sources(evidence_text)
    checked = []
    for item in anchors:
        if not isinstance(item, dict) or set(item) - {"locator", "quote", "purpose"}:
            raise ValueError("evidence_anchors items must contain only locator/quote/purpose")
        quote = str(item.get("quote") or "").strip()
        if not quote:
            raise ValueError("evidence anchor quote is required")
        hit = locate_quote(quote, sources)
        if not hit:
            raise ValueError("control narrative quote is not verifiable in supplied evidence")
        checked.append({"locator": hit.get("locator", ""), "quote": quote, "purpose": str(item.get("purpose") or "")})
    candidate = dict(value)
    candidate["evidence_anchors"] = checked
    return ControlNarrativeOutput.model_validate(candidate)


def _prompt(inp: ControlNarrativeInput) -> tuple[str, str]:
    system = (
        "You are Control Narrative Copilot in a governed audit system. Convert supplied evidence into a concise, "
        "audit-ready explanation of how the evidence expresses the intent of the governed control in practice. "
        "Be persuasive through clarity, not exaggeration. Every evidence anchor quote must be copied verbatim. "
        "Always state limitations: what the evidence does not prove. Do NOT output sufficiency, maturity, ratings, "
        "compliance, approval/rejection, challenge strength, or a governance decision. Return JSON only."
    )
    user = json.dumps({
        "control": {"id": inp.control_id, "framework": inp.framework, "requirement": inp.requirement},
        "requirement_elements": [e.model_dump() for e in inp.requirement_context],
        "evidence": inp.evidence_text[:24000],
        "response_schema": {
            "narrative": "",
            "evidence_anchors": [{"locator": "", "quote": "", "purpose": ""}],
            "demonstrates": [""],
            "limitations": [""],
        },
    }, ensure_ascii=False)
    return system, user


def run(value: ControlNarrativeInput | dict, *, control=None, review_id: str | None = None) -> ControlNarrativeOutput:
    inp = value if isinstance(value, ControlNarrativeInput) else ControlNarrativeInput.model_validate(value)
    if not inp.evidence_text.strip():
        return ControlNarrativeOutput(
            narrative="No evidence is currently bound; an audit-ready control narrative cannot be grounded.",
            evidence_anchors=[], demonstrates=[], limitations=["No evidence is bound to this review cycle."],
        )
    system, user = _prompt(inp)
    signals = signals_for_control(control, role="copilot", evidence_chars=len(inp.evidence_text)) if control is not None else None
    task_id = f"NARR-{inp.control_id}-{uuid.uuid4().hex[:10]}"

    def _validate(raw: str):
        try:
            validate(_parse(raw), inp.evidence_text)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    raw, _plan, _rec = run_with_escalation(
        role="copilot", system=system, user=user, signals=signals, validate=_validate,
        control_id=inp.control_id, task_id=task_id, review_id=review_id,
    )
    return validate(_parse(raw), inp.evidence_text)
