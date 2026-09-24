from types import SimpleNamespace

from core.cycle import _control
from governance.control_contract import requirement_context
from governance.knowledge import _framework_alias
from assessor import _validate


def test_mgf_shorthand_resolves_d11_to_mgf_agentic_workbook_control():
    c = _control("D1.1", "MGF")
    assert c.id == "D1.1"
    assert c.lib == "MGF Agentic"


def test_mgf_shorthand_resolves_governed_requirement_contract():
    ctx = requirement_context("D1.1", "MGF")
    assert ctx["control_id"] == "D1.1"
    assert ctx["requirement"]
    assert ctx["elements"]
    assert ctx["source"]


def test_mgf_shorthand_participates_in_testing_knowledge_aliases():
    aliases = _framework_alias("MGF")
    assert "MGF Agentic" in aliases
    assert "MGF_Agentic" in aliases


def test_partial_all_elements_met_exposes_inconsistency_and_explicit_bases():
    evidence = "Policy owner is named. Annual suitability review is completed."
    elements = [
        {"id": "e1", "text": "Policy owner is named"},
        {"id": "e2", "text": "Annual suitability review is completed"},
    ]
    out = {
        "excerpt": "Policy owner is named",
        "gaps": [],
        "rationale": "The evidence documents the control.",
        "sufficiency": "partial",
        "sufficiencyReason": "Documentation exists.",
        "proposedMaturity": 2,
        "maturityReason": "The evidence shows a documented process but not measured performance.",
        "remediation": [],
        "reviewerPrompt": "Confirm operating evidence.",
        "elementVerdicts": [
            {"element_id": "e1", "status": "met", "excerpt": "Policy owner is named"},
            {"element_id": "e2", "status": "met", "excerpt": "Annual suitability review is completed"},
        ],
    }
    result = _validate(out, evidence, [], artefacts=[], elements=elements, contract={})
    assert result["sufficiency"] == "partial"  # validator remains downgrade-only
    assert result["proposedMaturity"] == 2
    assert result["rating_consistency"] == "review_required"
    assert "every applicable canonical element is MET" in result["sufficiency_basis"]
    assert "Maturity 2/5 (documented)" in result["maturity_basis"]
    assert "documented process" in result["maturity_basis"]
