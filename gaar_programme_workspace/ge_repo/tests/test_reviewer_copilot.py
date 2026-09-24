from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import events


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "events.jsonl"
    monkeypatch.setattr(events, "LOG", p)
    return p


class _Ctl:
    id, lib, title, req, owner, maps = "M3.6", "MAS", "Validation", "Requirement", "CRO", ""
    elements = (("e1", "Evidence supports validation"),)
    artefacts = "report; test output"


@pytest.fixture
def wired(monkeypatch, log):
    import core.cycle as cc
    monkeypatch.setattr(cc, "_control", lambda cid, fw="": _Ctl())
    return cc


def _read(cc, cid, suff="partial", mat=2, reason="Evidence remains incomplete"):
    cc.record_read(cid, {"sufficiency": suff, "maturity": mat, "reason": reason,
                         "element_verdicts": [{"element_id": "e1", "status": "not_evidenced"}]}, actor="reviewer")


def test_schema_rejects_rating_fields():
    from copilot import _validate_response
    with pytest.raises(ValueError, match="prohibited_judgement_field"):
        _validate_response({"sufficiency": "full"})


def test_schema_rejects_unknown_fields():
    from copilot import _validate_response
    with pytest.raises(ValueError, match="unknown_copilot_field"):
        _validate_response({"foo": "bar"})


def test_valid_schema_has_no_judgement_fields():
    from copilot import _validate_response
    out = _validate_response({
        "relevant_evidence": [{"locator": "p4", "excerpt": "text", "relevance": "direct"}],
        "requirement_context": [{"element_id": "e1", "text": "element", "note": "scope"}],
        "evidence_gaps": ["missing independent report"],
        "questions": ["What version was validated?"],
        "rationale_draft": "The available evidence shows ...",
    })
    assert "sufficiency" not in out
    assert "maturity" not in out


def test_copilot_requires_initial_read(wired, log):
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    with pytest.raises(wired.CycleError, match="initial reviewer reading"):
        wired.copilot_request(cid, actor="reviewer")


def test_copilot_request_accepts_explicit_request_id(monkeypatch, wired, log):
    monkeypatch.setattr("copilot.request", lambda control, evidence, **kwargs: {
        "schema_version": "copilot.response.1", "request_id": kwargs["task_id"], "provider": "ollama", "model": "llama3.2",
        "response": {"relevant_evidence": [], "requirement_context": [], "evidence_gaps": [], "questions": [], "rationale_draft": "draft"},
    })
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    _read(wired, cid)
    out = wired.copilot_request(cid, actor="reviewer", request_id="LIVE-COP-TEST-M3_6")
    assert out["request_id"] == "LIVE-COP-TEST-M3_6"
    assert any((e.get("payload") or {}).get("request_id") == "LIVE-COP-TEST-M3_6" for e in events.cycle(cid))


def test_copilot_request_is_recorded_and_does_not_receive_reviewer_read(monkeypatch, wired, log):
    captured = {}
    monkeypatch.setattr("copilot.request", lambda control, evidence: captured.update({"evidence": dict(evidence)}) or {
        "schema_version": "copilot.response.1", "request_id": "COP-1", "provider": "ollama", "model": "llama3.2",
        "response": {"relevant_evidence": [], "requirement_context": [], "evidence_gaps": [], "questions": [], "rationale_draft": "draft"},
    })
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    _read(wired, cid)
    out = wired.copilot_request(cid, actor="reviewer")
    assert out["request_id"] == "COP-1"
    assert "sufficiency" not in captured["evidence"]
    kinds = [e["kind"] for e in events.cycle(cid)]
    assert "copilot_requested" in kinds and "copilot_presented" in kinds


def test_reference_is_explicit_and_does_not_modify_read(wired, monkeypatch, log):
    monkeypatch.setattr("copilot.request", lambda control, evidence: {
        "schema_version": "copilot.response.1", "request_id": "COP-2", "provider": "ollama", "model": "llama3.2",
        "response": {"relevant_evidence": [], "requirement_context": [], "evidence_gaps": [], "questions": [], "rationale_draft": "draft"},
    })
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    _read(wired, cid)
    wired.copilot_request(cid, actor="reviewer")
    before = events.state(cid)["read"]
    wired.copilot_reference(cid, "COP-2", actor="reviewer")
    after = events.state(cid)["read"]
    assert before == after
    assert any(e["kind"] == "copilot_reference" for e in events.cycle(cid))


def test_rating_change_after_copilot_is_logged(monkeypatch, wired, log):
    monkeypatch.setattr("copilot.request", lambda control, evidence: {
        "schema_version": "copilot.response.1", "request_id": "COP-3", "provider": "ollama", "model": "llama3.2",
        "response": {"relevant_evidence": [], "requirement_context": [], "evidence_gaps": [], "questions": [], "rationale_draft": "independent draft"},
    })
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    _read(wired, cid, "partial", 2)
    wired.copilot_request(cid, actor="reviewer")
    wired.record_read(cid, {"sufficiency": "full", "maturity": 3, "reason": "Evidence now supports the requirement",
                            "element_verdicts": [{"element_id": "e1", "status": "met"}]}, actor="reviewer")
    inf = events.state(cid)["copilot_influence"]
    assert inf["rating_changed_after_copilot"] is True
    assert inf["rationale_changed_after_copilot"] is True
    assert inf["element_judgement_changed_after_copilot"] is True
    assert inf["changed_element_ids"] == ["e1"]


def test_no_change_after_copilot_is_not_flagged(monkeypatch, wired, log):
    monkeypatch.setattr("copilot.request", lambda control, evidence: {
        "schema_version": "copilot.response.1", "request_id": "COP-4", "provider": "ollama", "model": "llama3.2",
        "response": {"relevant_evidence": [], "requirement_context": [], "evidence_gaps": [], "questions": [], "rationale_draft": "draft"},
    })
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    reading = {"sufficiency": "partial", "maturity": 2, "reason": "Evidence remains incomplete",
               "element_verdicts": [{"element_id": "e1", "status": "not_evidenced"}]}
    wired.record_read(cid, reading, actor="reviewer")
    wired.copilot_request(cid, actor="reviewer")
    wired.record_read(cid, reading, actor="reviewer")
    inf = events.state(cid)["copilot_influence"]
    assert inf["rating_changed_after_copilot"] is False
    assert inf["rationale_changed_after_copilot"] is False
    assert inf["element_judgement_changed_after_copilot"] is False


def test_concurrent_assessor_and_copilot_are_distinct_roles():
    from llm.client import roles_in_use
    roles = roles_in_use()
    assert "assess" in roles and "copilot" in roles
    assert roles["assess"] is not None and roles["copilot"] is not None


def test_app_exposes_copilot_separately_and_never_inserts_into_authoritative_read():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "Reviewer Copilot" in src
    assert "Use Copilot suggestion as reference" in src
    assert "governance_cycle.copilot_request" in src
    assert "governance_cycle.copilot_reference" in src
    # The UI only writes the reviewer record through record_read; there is no Copilot assignment
    # into sufficiency/maturity in the Copilot panel.
    panel = src[src.index("def _render_copilot("):src.index("def _render_review_workspace(")]
    assert "governance_cycle.copilot_request" in panel
    assert "governance_cycle.copilot_reference" in panel
    pure = panel[panel.index("def _render_copilot("):panel.index("def _render_copilot_revision(")]
    assert 'response.get("sufficiency")' not in pure
    assert 'response.get("maturity")' not in pure
    assert 'response.get("element_verdicts")' not in pure
    assert "governance_cycle.record_read" not in pure


def test_rating_change_at_decision_after_copilot_is_recorded(monkeypatch, wired, log):
    monkeypatch.setattr("copilot.request", lambda control, evidence, **kwargs: {
        "schema_version": "copilot.response.1", "request_id": kwargs.get("task_id", "COP-5"), "provider": "ollama", "model": "llama3.2",
        "response": {"relevant_evidence": [], "requirement_context": [], "evidence_gaps": [], "questions": [], "rationale_draft": "draft"},
    })
    cid = wired.start("M3.6", framework="MAS")
    wired.bind_evidence(cid, {"text": "evidence"})
    _read(wired, cid, "partial", 2)
    wired.copilot_request(cid, actor="reviewer")
    wired.decide(cid, sufficiency="full", maturity=3, reviewer="reviewer",
                 reason="Evidence now supports the requirement")
    inf = events.state(cid)["decision"]["copilot_influence"]
    assert inf["rating_changed_after_copilot"] is True
    assert inf["sufficiency_changed"] is True
    assert inf["maturity_changed"] is True


def test_live_ollama_transport_envelope_is_unwrapped():
    from copilot import _json_from_text, _validate_response
    raw = json.dumps({
        "response": {
            "relevant_evidence": [],
            "requirement_context": [],
            "evidence_gaps": ["x"],
            "questions": ["q"],
            "rationale_draft": "draft",
        }
    })
    parsed = _validate_response(_json_from_text(raw))
    assert parsed["evidence_gaps"] == ["x"]
    assert parsed["questions"] == ["q"]


def test_transport_envelope_does_not_hide_prohibited_judgement():
    from copilot import _json_from_text, _validate_response
    raw = json.dumps({"response": {"maturity": 3}})
    with pytest.raises(ValueError, match="prohibited_judgement_field:maturity"):
        _validate_response(_json_from_text(raw))


def test_transport_envelope_with_sibling_field_is_not_silently_accepted():
    from copilot import _json_from_text, _validate_response
    raw = json.dumps({"response": {"evidence_gaps": []}, "extra": "bad"})
    with pytest.raises(ValueError, match="unknown_copilot_field:extra,response"):
        _validate_response(_json_from_text(raw))


def test_live_ollama_single_requirement_context_object_is_normalized():
    from copilot import _json_from_text, _validate_response
    raw = json.dumps({
        "relevant_evidence": [],
        "requirement_context": {"element_id": "e1", "text": "requirement", "note": "scope"},
        "evidence_gaps": [],
        "questions": [],
        "rationale_draft": "",
    })
    parsed = _validate_response(_json_from_text(raw))
    assert parsed["requirement_context"] == [
        {"element_id": "e1", "text": "requirement", "note": "scope"}
    ]


def test_requirement_context_scalar_still_fails_closed_after_transport_normalization():
    from copilot import _json_from_text, _validate_response
    for bad in ("bad", 42):
        raw = json.dumps({
            "relevant_evidence": [],
            "requirement_context": bad,
            "evidence_gaps": [],
            "questions": [],
            "rationale_draft": "",
        })
        with pytest.raises(ValueError, match="requirement_context must be a list"):
            _validate_response(_json_from_text(raw))
