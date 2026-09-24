from __future__ import annotations

import pytest
from pydantic import ValidationError

import events
from governance.ai_auditor.schemas import (
    EvidenceExaminerInput, EvidenceExaminerOutput,
)
from governance.ai_auditor.skills import evidence_examiner
from governance.ai_auditor.skills.control_narrative import validate as validate_narrative
from governance.ai_auditor.registry import list_skills
from governance.ai_auditor.conductor import ReviewConductor
from ui.agile_review import framework_groups, standup_summary
from ui.ai_auditor_dashboard import decision_metrics


def test_evidence_examiner_requirement_context_is_typed():
    base = dict(control_id="2.1", framework="SAFR", requirement_version_id="REQ-1",
                evidence_set_id="EVID-1", evidence_text="threshold review before deployment")
    with pytest.raises(ValidationError):
        EvidenceExaminerInput(**base, requirement_context="string")
    with pytest.raises(ValidationError):
        EvidenceExaminerInput(**base, requirement_context=42)


def test_evidence_examiner_output_range_is_fail_closed():
    with pytest.raises(ValidationError):
        EvidenceExaminerOutput(sufficiency_score=1.5, evidence_freshness="100%",
                               open_evidence_gaps=[], covered_elements=[], recommended_action="NONE", rationale="x")


def test_evidence_examiner_is_deterministic():
    value = {
        "control_id":"2.1", "framework":"SAFR", "requirement_version_id":"REQ-1", "evidence_set_id":"EVID-1",
        "requirement_context":[{"element_id":"e1","text":"threshold governance review before deployment"}],
        "evidence_text":"Threshold governance parameters are reviewed before deployment.",
    }
    assert evidence_examiner.run(value).model_dump() == evidence_examiner.run(value).model_dump()


def test_evidence_examiner_zero_elements_is_not_evaluated_not_false_green():
    value = {
        "control_id":"M3.6", "framework":"MAS", "requirement_version_id":"REQ-1",
        "evidence_set_id":"EVID-1", "requirement_context":[],
        "evidence_text":"Fresh evidence exists, but no governed elements were supplied.",
    }
    out = evidence_examiner.run(value)
    assert out.evaluation_status == "NOT_EVALUATED"
    assert out.sufficiency_score is None
    assert out.recommended_action == "COLLECT_MORE"
    assert any("NO_GOVERNED_ELEMENTS" in gap for gap in out.open_evidence_gaps)


def test_control_narrative_cannot_smuggle_rating_or_unverified_quote():
    with pytest.raises(ValueError, match="prohibited_control_narrative_field"):
        validate_narrative({"narrative":"x","evidence_anchors":[],"demonstrates":[],"limitations":[],"maturity":5}, "source")
    with pytest.raises(ValueError, match="not verifiable"):
        validate_narrative({"narrative":"x","evidence_anchors":[{"quote":"invented quote","locator":"","purpose":"x"}],"demonstrates":[],"limitations":[]}, "actual evidence")


def test_all_registered_skills_are_state_free():
    assert list_skills()
    assert all(not spec.may_mutate_state for spec in list_skills())


def test_framework_fair_review_keeps_safr_visible():
    rows = []
    for i in range(60):
        rows.append({"library":"MAS","control_id":f"M{i}","next_action":{"kind":"review"},"challenge":{},"has_evidence":True,"has_read":True,"has_proposal":True,"has_compare":True})
    for i in range(60):
        rows.append({"library":"MGF Agentic","control_id":f"G{i}","next_action":{"kind":"review"},"challenge":{},"has_evidence":True,"has_read":True,"has_proposal":True,"has_compare":True})
    rows.append({"library":"SAFR","control_id":"2.1","next_action":{"kind":"decision"},"challenge":{},"has_evidence":True,"has_read":True,"has_proposal":True,"has_compare":True})
    groups = framework_groups(rows)
    assert set(groups) >= {"MAS","MGF Agentic","SAFR"}
    assert groups["SAFR"][0]["control_id"] == "2.1"
    assert "SAFR" in standup_summary(rows)["frameworks"]


def test_safr_decision_is_counted_in_ledger_dashboard(monkeypatch):
    monkeypatch.setattr(events, "decided", lambda: [
        {"framework":"SAFR","control_id":"2.1","decision":{"sufficiency":"full"}},
        {"framework":"MAS","control_id":"2.2","decision":{"sufficiency":"partial"}},
    ])
    m = decision_metrics()
    assert m["by_framework"]["SAFR"] == 1
    assert m["total"] == 2


def test_conductor_stops_at_human_decision_and_never_calls_decide(monkeypatch):
    # Legacy contract fixture; mandatory investigation defaults are tested separately.
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
    state = {
        "cycle_id":"C1", "control_id":"2.1", "framework":"SAFR",
        "evidence":{"text":"threshold governance review before deployment"},
        "read":{"sufficiency":"full","maturity":3,"reason":"x"},
        "proposal":{"sufficiency":"full","maturity":3},
        "diff":{"comparable":True,"disagreements":[]},
        "challenges":[],
    }
    class C:
        id="2.1"; lib="SAFR"; req="threshold governance review before deployment"; elements=(("e1",req),)
    monkeypatch.setattr(events, "state", lambda cid: dict(state))
    conductor = ReviewConductor()
    monkeypatch.setattr(conductor, "_control", lambda s: C())
    called = {"decide":0}
    from core import cycle
    monkeypatch.setattr(cycle, "decide", lambda *a, **k: called.__setitem__("decide", called["decide"]+1))
    out = conductor.run_to_checkpoint("C1")
    assert out.checkpoint == "HUMAN_DECISION"
    assert called["decide"] == 0


def test_quality_auditor_requires_human_decision(monkeypatch):
    from governance.ai_auditor.skills import quality_auditor
    monkeypatch.setattr(events, "state", lambda cid: {
        "cycle_id":cid,"control_id":"X","evidence":{"text":"x"},"proposal":{"x":1},"diff":{"comparable":True},"challenges":[]
    })
    out = quality_auditor.run({"cycle_id":"C1","require_human_decision":True})
    assert not out.ready
    assert "human_decision_missing" in out.blockers
