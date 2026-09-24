from __future__ import annotations

from pathlib import Path

from inference.policy import build_plan, control_complexity, signals_for_control
from playbook import load_controls

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "AI_Governance_Playbook_MGF_SAFR_v0.5.2_requirement_elements_audited.xlsx"


def _mas_controls():
    return {c.id: c for c in load_controls(WORKBOOK)["MAS"]}


def test_real_m36_is_structurally_critical(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    c = _mas_controls()["M3.6"]
    profile = control_complexity(c)
    assert profile["element_count"] == 14
    assert profile["expected_artefact_count"] == 14
    assert profile["band"] == "critical"
    assert profile["score"] == 3

    plan = build_plan(signals_for_control(c, role="assess"))
    assert plan.control_complexity_band == "critical"
    assert plan.provider == "colibri"


def test_real_m12_is_structurally_routine(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    c = _mas_controls()["M1.2"]
    profile = control_complexity(c)
    assert profile["element_count"] == 0
    assert profile["expected_artefact_count"] == 1
    assert profile["band"] == "routine"
    assert profile["score"] == 0

    plan = build_plan(signals_for_control(c, role="assess"))
    assert plan.control_complexity_band == "routine"
    assert plan.provider == "ollama"


def test_canonical_get_control_contract_dict_is_supported_directly(monkeypatch):
    from governance.control_contract import get_control_contract

    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    c = get_control_contract("M3.6", "MAS")
    assert isinstance(c, dict)
    profile = control_complexity(c)
    assert profile["element_count"] == 14
    assert profile["expected_artefact_count"] == 1
    assert profile["score"] == 2
    assert profile["band"] == "complex"

    signals = signals_for_control(c, role="assess")
    assert signals.control_id == "M3.6"
    plan = build_plan(signals)
    assert plan.control_complexity_band == "complex"
    assert plan.provider == "colibri"


def test_missing_dict_fields_degrade_safely(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    result = control_complexity({"control_id": "X"})
    assert result["score"] == 0
    assert result["band"] == "routine"
    assert result["element_count"] == 0
    assert result["expected_artefact_count"] == 0


def test_none_and_wrong_type_fields_do_not_create_false_complexity():
    result = control_complexity({
        "control_id": "X",
        "elements": None,
        "requirement": 123456,
        "expected_evidence": {"not": "a supported evidence list"},
    })
    assert result["score"] == 0
    assert result["band"] == "routine"
    assert result["element_count"] == 0
    assert result["expected_artefact_count"] == 0
    assert result["requirement_chars"] == 0


def test_object_with_none_fields_is_safe():
    class Partial:
        id = "X"
        elements = None
        req = None
        artefacts = None

    result = control_complexity(Partial())
    assert result["score"] == 0
    assert result["band"] == "routine"


def test_live_probe_ledger_fields_separate_control_and_task_reasoning(monkeypatch, tmp_path):
    import inference.orchestrator as orch

    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    calls = []
    monkeypatch.setattr(orch, "call_colibri", lambda system, user, model, max_tokens=None: calls.append((model, max_tokens)) or "OK")
    from inference import signals_for_control
    c = _mas_controls()["M3.6"]
    raw, plan, rec = orch.run_with_escalation(
        role="assess",
        system="system",
        user="probe",
        signals=signals_for_control(c, role="assess", evidence_chars=120),
        control_id="M3.6",
        task_id="TEST-LIVE-PROBE-FIELDS",
    )
    assert raw == "OK"
    assert plan.provider == "colibri"
    assert rec["control_complexity_band"] == "critical"
    assert rec["complexity_band"] == "critical"
    assert "many_control_elements" in rec["control_complexity_reasons"]
    assert "many_elements" in rec["complexity_reasons"]
    assert calls == [("glm-5.2-colibri", plan.num_predict)]
