import json
from types import SimpleNamespace

import assessor as A


def test_risk_pass_is_visible_without_changing_control_verdict(monkeypatch):
    monkeypatch.setattr(A, "PROVIDER", "anthropic")
    monkeypatch.setattr(A, "ELEMENT_PASS", "off")
    monkeypatch.setattr(A, "_contract_elements", lambda c: [])
    monkeypatch.setattr(A, "_prompt", lambda *a, **k: "test")
    monkeypatch.setattr(A, "_artefacts", lambda c: [])
    monkeypatch.setattr(A, "_contract_for", lambda c: {})
    monkeypatch.setattr(A, "_validate", lambda parsed, *a, **k: parsed)
    evidence = "Asset c is missing from the inventory export."
    baseline = {"sufficiency": "partial", "proposedMaturity": 2, "gaps": ["e1: inventory incomplete"]}
    calls = []
    def fake(system, user, pdf):
        calls.append(system)
        if "wider risk implications" in system:
            return json.dumps({"hypotheses": [{"observation_quote": evidence,
                "possible_effect": "Patch coverage may also be incomplete.",
                "related_control_topic": "Patch coverage",
                "alternative_explanation": "A delayed inventory export.",
                "proposed_test": "Reconcile the asset IDs with a same-time patch export.",
                "priority_reason": "Unknown population could distort reporting."}]})
        return json.dumps(baseline)
    monkeypatch.setattr(A, "_anthropic", fake)
    c = SimpleNamespace(id="TEST", lib="TEST", req="Inventory", title="Inventory", maps="", owner="", artefacts="")
    monkeypatch.setenv("WB_ASSESSOR_RISK_REVIEW", "1")
    out = A.assess(c, evidence)
    assert len(calls) == 2
    assert out["risk_review"]["status"] == "REVIEWED"
    assert out["risk_review"]["hypotheses"][0]["test_status"] == "NOT_RUN"
    for k, v in baseline.items():
        assert out[k] == v
    monkeypatch.setenv("WB_ASSESSOR_RISK_REVIEW", "0")
    calls.clear()
    disabled = A.assess(c, evidence)
    assert len(calls) == 1
    assert disabled["risk_review"]["status"] == "DISABLED"
