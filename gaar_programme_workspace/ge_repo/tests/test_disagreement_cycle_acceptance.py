"""Comparison → Challenge (when disagreement exists) → Resolution → Decision.

Deterministic and model-free. The point is to tell a broken button from a state that simply does
not satisfy its contract — the live ledger has nothing past the proposal stage, so
`challenge_disagreement` there is unreachable rather than faulty, and testing it against that
ledger would prove nothing either way.

Three actions can look alike in the UI and must not share a permissive transition:

    Challenge my read        needs a recorded reading
    Challenge disagreement   needs a comparison AND an actual disagreement
    Record decision          needs the challenges resolved
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import challenge as CH
import compare as C

ELEMENTS = [
    {"id": "e1", "text": "Independent validation is performed before deployment.",
     "scope": "model", "locator": "x[1]"},
    {"id": "e2", "text": "Residual risk and an accountable owner are recorded.",
     "scope": "model", "locator": "x[2]"},
    {"id": "e3", "text": "Findings and conditions for use are reported before deployment.",
     "scope": "model", "locator": "x[3]"},
]

EVIDENCE = ("--- Source: pack.md ---\n"
            "Validation was performed by Model Risk Management. No member of the review team "
            "contributed to the development of v3.1. Residual risk is recorded against the "
            "Head of Consumer Credit Analytics.")


class _Ctl:
    id, lib = "M3.6", "Control Library - MAS"
    title = "Evaluation, testing & independent validation"
    req = owner = maps = artefacts = ""


@pytest.fixture
def elements(monkeypatch):
    monkeypatch.setattr(C, "elements_for", lambda control: ELEMENTS)
    return ELEMENTS


def _read(**verdicts):
    return {"sufficiency": "partial", "maturity": 3, "reason": "r",
            "element_verdicts": [{"element_id": k, "status": v} for k, v in verdicts.items()]}


def _ai(**verdicts):
    return {"sufficiency": "partial", "proposedMaturity": 3,
            "elementVerdicts": [{"element_id": k, "status": v} for k, v in verdicts.items()]}


def _stub(monkeypatch, payload):
    """Intercept at the transport, not at a guessed helper name.

    `challenge.py` reaches the model through `llm.client.model_for` / `chat`, so stubbing a
    `_chat` that does not exist silently did nothing and every test hit a real endpoint.
    """
    import llm.client as LC

    class _M:
        def __enter__(self): return "stub-model"
        def __exit__(self, *a): return False

    monkeypatch.setattr(CH, "model_for", lambda *a, **k: _M(), raising=False)
    # Challenge currently enters the common inference orchestrator with the legacy Ollama
    # callable as an explicit invoke seam, so stub both layers. Keeping the transport stub here
    # prevents this deterministic test from requiring a live LLM service.
    monkeypatch.setattr(CH, "_ollama", lambda *a, **k: json.dumps(payload), raising=False)
    monkeypatch.setattr(LC, "chat", lambda *a, **k: json.dumps(payload), raising=False)
    for name in ("chat", "complete", "generate"):
        if hasattr(CH, name):
            monkeypatch.setattr(CH, name, lambda *a, **k: json.dumps(payload))


# ------------------------------------------------------------------ the positive case

def test_a_genuine_disagreement_produces_a_comparison_with_one_disputed_element(elements):
    """human MET vs AI NOT_EVIDENCED on e1, agreement elsewhere."""
    diff = C.compare(_read(e1="met", e2="met", e3="not_evidenced"),
                     _ai(e1="not_evidenced", e2="met", e3="not_evidenced"),
                     _Ctl(), min_compared=2)
    assert diff["comparable"] is True
    assert diff["disagreements"] == ["e1"]
    assert diff["summary"]["n_compared"] == 3


def test_challenge_disagreement_runs_when_a_disagreement_exists(elements, monkeypatch):
    diff = C.compare(_read(e1="met", e2="met", e3="not_evidenced"),
                     _ai(e1="not_evidenced", e2="met", e3="not_evidenced"),
                     _Ctl(), min_compared=2)
    _stub(monkeypatch, {"overall_reasoning": "r", "sharpest": "s", "unaddressed": [],
                        "challenges": [{
                            "element_id": "e1",
                            "challenge": "The pack names the function but not the individuals.",
                            "observation": "The evidence identifies the reviewing function but not individual reviewers.",
                            "inference": "The record may not establish individual reviewer independence.",
                            "risk_to_address": "independence evidence may be incomplete",
                            "recommended_action": "request_evidence",
                            "severity": "medium", "confidence": "high",
                            "challenge_strength": "strong", "supports": "ai",
                            "factual_pointer": {"source": "pack.md", "locator": "1",
                                                "quote": "Validation was performed by Model Risk Management",
                                                "fact": "f", "what_it_supports": "s"},
                            "requirement_pointer": {"control_id": "M3.6", "locator": "e1",
                                                    "element_id": "e1",
                                                    "text": ELEMENTS[0]["text"]}}]})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE,
                                    _read(e1="met", e2="met", e3="not_evidenced"),
                                    _ai(e1="not_evidenced", e2="met", e3="not_evidenced"), diff)
    assert out.get("validation_status") != "blocked", out.get("validation_error")
    assert out["challenges"], "a disagreement with a verifiable quote should admit a challenge"


def test_the_challenge_is_scoped_to_the_disputed_element(elements, monkeypatch):
    """A challenge against an element both sides agreed on is out of scope and dropped."""
    diff = C.compare(_read(e1="met", e2="met", e3="not_evidenced"),
                     _ai(e1="not_evidenced", e2="met", e3="not_evidenced"),
                     _Ctl(), min_compared=2)
    _stub(monkeypatch, {"overall_reasoning": "r", "sharpest": "s", "unaddressed": [],
                        "challenges": [{
                            "element_id": "e2", "challenge": "Agreed element, not disputed.",
                            "challenge_strength": "weak", "supports": "neither",
                            "factual_pointer": {"source": "pack.md", "locator": "1",
                                                "quote": "Residual risk is recorded against the",
                                                "fact": "f", "what_it_supports": "s"},
                            "requirement_pointer": {"control_id": "M3.6", "locator": "e2",
                                                    "element_id": "e2",
                                                    "text": ELEMENTS[1]["text"]}}]})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE,
                                    _read(e1="met", e2="met", e3="not_evidenced"),
                                    _ai(e1="not_evidenced", e2="met", e3="not_evidenced"), diff)
    assert out["challenges"] == []
    assert out.get("out_of_scope_dropped")


def test_the_challenge_never_carries_a_rating(elements, monkeypatch):
    """The reviewer remains the authority; a challenge is a question, not a verdict."""
    diff = C.compare(_read(e1="met", e2="met", e3="not_evidenced"),
                     _ai(e1="not_evidenced", e2="met", e3="not_evidenced"),
                     _Ctl(), min_compared=2)
    _stub(monkeypatch, {"overall_reasoning": "r", "sharpest": "s", "unaddressed": [],
                        "challenges": [{
                            "element_id": "e1", "challenge": "c", "challenge_strength": "strong",
                            "supports": "ai",
                            "factual_pointer": {"source": "pack.md", "locator": "1",
                                                "quote": "Validation was performed by Model Risk Management",
                                                "fact": "f", "what_it_supports": "s"},
                            "requirement_pointer": {"control_id": "M3.6", "locator": "e1",
                                                    "element_id": "e1",
                                                    "text": ELEMENTS[0]["text"]}}]})
    out = CH.challenge_disagreement(_Ctl(), EVIDENCE,
                                    _read(e1="met", e2="met", e3="not_evidenced"),
                                    _ai(e1="not_evidenced", e2="met", e3="not_evidenced"), diff)
    for banned in ("sufficiency", "proposedMaturity", "maturity", "decision"):
        assert banned not in out, f"a challenge must not carry {banned}"


# ------------------------------------------------------------------ the negative case

def test_full_agreement_produces_no_disagreement_to_challenge(elements):
    diff = C.compare(_read(e1="met", e2="met", e3="met"),
                     _ai(e1="met", e2="met", e3="met"), _Ctl(), min_compared=2)
    assert diff["comparable"] is True
    assert diff["disagreements"] == []


def test_challenge_disagreement_refuses_when_there_is_nothing_to_challenge(elements):
    """The button being unavailable here is the contract holding, not a defect."""
    diff = C.compare(_read(e1="met", e2="met", e3="met"),
                     _ai(e1="met", e2="met", e3="met"), _Ctl(), min_compared=2)
    with pytest.raises(ValueError, match="agree on every compared element"):
        CH.challenge_disagreement(_Ctl(), EVIDENCE, _read(e1="met", e2="met", e3="met"),
                                  _ai(e1="met", e2="met", e3="met"), diff)


def test_an_incomparable_diff_is_refused_rather_than_treated_as_agreement(elements):
    """NOT_COMPARABLE is not the same fact as 'the two agreed'."""
    diff = C.compare(_read(e1="unset", e2="unset", e3="unset"),
                     _ai(e1="unset", e2="unset", e3="unset"), _Ctl(), min_compared=2)
    with pytest.raises(ValueError, match="not comparable|agree on every"):
        CH.challenge_disagreement(_Ctl(), EVIDENCE, _read(e1="unset"), _ai(e1="unset"), diff)


# ------------------------------------------------------------------ the three actions differ

def test_the_three_actions_have_different_preconditions():
    """Challenge-my-read needs a reading; challenge-disagreement needs a comparison with a
    dispute. Sharing a transition would let one run in the other's state."""
    import inspect
    read_src = inspect.getsource(CH.challenge)
    dis_src = inspect.getsource(CH.challenge_disagreement)
    assert "disagreement" not in read_src.split('"""')[1].lower()
    assert "disagreements" in dis_src and "comparable" in dis_src
