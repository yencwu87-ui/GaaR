import json
from pathlib import Path

import pytest

import challenge as CH
import challenge_copilot as CC
import events
from core import cycle as CYCLE

CONTROL_ID = "M3.12"
E2_TEXT = "Change records link approval, implementation and the deployed system/version."
EVIDENCE = """Change management extract, Q1.
CHG-4471 approved 14 March 09:12 by the change authority.
Deployment log records release of pricing-model v3 at 13 March 22:40.
All changes in the period were raised in the register."""
QUOTE = "Deployment log records release of pricing-model v3 at 13 March 22:40."
BLIND = {"sufficiency": "full", "maturity": 4,
         "reason": "I conclude the evidence fully demonstrates approval before deployment.",
         "element_verdicts": [{"element_id": "e2", "status": "met"}]}
AI = {"sufficiency": "partial", "proposedMaturity": 3, "rationale": "approval postdates release",
      "gaps": [], "flags": [],
      "elementVerdicts": [{"element_id": "e2", "status": "not_evidenced", "excerpt": QUOTE}]}
DIFF = {"comparable": True, "disagreements": ["e2"], "diff_sha": "wb113-diff",
        "rows": [{"element_id": "e2", "text": E2_TEXT, "reviewer": "met", "ai": "not_evidenced",
                  "direction": "reviewer_more_generous", "ai_excerpt": QUOTE}]}


class _Ctl:
    id, lib, title, req, maps = CONTROL_ID, "Control Library - MAS", "Change management", "req", ""


def _base(anchor: dict, anchor_name: str, *, strength="strong", supports="assessor"):
    row = {
        "observation": "the disputed verdict needs to be revisited",
        "evidence_basis": [QUOTE] if anchor_name == "factual_pointer" else ["reviewer reasoning is broader than the evidence"],
        "requirement_basis": [E2_TEXT], "knowledge_basis": [],
        "inference": "the grounded anchor does not support the disputed verdict",
        "challenge": "what governed evidence resolves this disagreement?",
        "factual_pointer": {}, "absence_pointer": {}, "reviewer_pointer": {},
        "requirement_pointer": {"control_id": CONTROL_ID, "locator": "controls.M3.12.elements[e2]",
                                "element_id": "e2", "text": E2_TEXT},
        "risk_to_address": "incorrectly calibrated governance conclusion",
        "resolution_pointer": "the governed approval record and deployment timestamp",
        "recommended_action": "revisit_read", "severity": "medium", "confidence": "high",
        "supports": supports,
        "claim_test": {"claim": "e2 is met", "fact_meaning": "the anchor narrows the claim",
                       "rebuttal": "the anchor challenges the disputed verdict", "rebuttal_strength": strength,
                       "risk_addressed": "incorrect governance conclusion"},
    }
    row[anchor_name] = anchor
    return row


def _stub(monkeypatch, payload):
    monkeypatch.setattr(CH, "PROVIDER", "ollama")
    monkeypatch.setattr(CH, "_ollama", lambda system, user: json.dumps(payload))
    monkeypatch.setattr(CH, "model_name", lambda: "stub-model")
    monkeypatch.setattr(CH, "scan_injection", lambda t: [])


def test_positive_evidence_disagreement_can_be_strong(monkeypatch):
    row = _base({"source": "reviewer_supplied", "locator": "line:3", "quote": QUOTE,
                 "fact": QUOTE, "what_it_supports": "deployment preceded approval"}, "factual_pointer")
    _stub(monkeypatch, {"overall_reasoning": "timestamps contradict the generous read",
                        "challenges": [row], "sharpest": "verify chronology", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    c = out["challenges"][0]
    assert c["anchor_kind"] == "factual_pointer"
    assert c["challenge_strength"] == "strong"
    assert c["supports"] == "assessor"
    assert c["factual_pointer"]["quote"] == QUOTE


def test_reviewer_reasoning_anchor_is_admitted_but_cannot_be_strong(monkeypatch):
    quote = "I conclude the evidence fully demonstrates approval before deployment."
    row = _base({"quote": quote, "what_it_supports": "reviewer conclusion overreaches"},
                "reviewer_pointer", strength="strong", supports="assessor")
    _stub(monkeypatch, {"overall_reasoning": "the conclusion is broader than the evidence",
                        "challenges": [row], "sharpest": "verify the inference", "unaddressed": []})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE, BLIND, AI, DIFF)
    c = out["challenges"][0]
    assert c["anchor_kind"] == "reviewer_pointer"
    assert c["challenge_strength"] == "weak"
    assert c["reviewer_pointer"]["quote"] == quote
    assert out["challenge_outcome"] == "weak_or_refining"


def test_challenge_copilot_schema_refuses_governance_judgement():
    with pytest.raises(ValueError, match="prohibited_challenge_copilot_field"):
        CC._validate_response({"challenge_explanation": "x", "questions": [],
                               "evidence_to_verify": [], "reviewer_note_draft": "",
                               "maturity": 4}, EVIDENCE)


def test_challenge_copilot_verifies_quoted_evidence():
    out = CC._validate_response({
        "challenge_explanation": "Verify the chronology before responding.",
        "evidence_to_verify": [{"locator": "", "excerpt": QUOTE, "purpose": "check deployment time"}],
        "questions": ["Was there an emergency approval path?"],
        "reviewer_note_draft": "I will verify the approval timestamp against deployment.",
    }, EVIDENCE)
    assert out["evidence_to_verify"][0]["locator"] == "line:3"


def test_event_store_accepts_challenge_copilot_event_kinds():
    for kind in ("challenge_copilot_requested", "challenge_copilot_presented", "challenge_copilot_rejected"):
        assert kind in events.KINDS
