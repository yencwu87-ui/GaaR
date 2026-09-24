from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

import events
from governance.quality_gate import evaluate, GateStatus, QualityGateLog
from governance.result_contract import CanonicalSigner, Decision, ProvenanceTrail, create_governance_result
from governance.result_integration import persist_and_set_current


def _signer():
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return CanonicalSigner.from_base64("wb116-test", base64.b64encode(raw).decode())


def _result():
    prov = ProvenanceTrail(
        requirement_version_id="REQ-1", evidence_set_id="EVID-1", assessment_id="ASS-1",
        challenge_set_id="CH-1", human_decision_id="HD-1", assessor_prompt_version="v1",
        model_version="ollama:test", model_invocation_id="run-1", human_decider_id="human-1",
        human_decision_timestamp="2026-09-19T00:00:00+00:00", workflow_step_timestamps={"assessor":"2026-09-19T00:00:00+00:00"},
        rule_versions={"result_contract":"v1"}, retrieval_receipt_id="RR-1", retrieval_pipeline_version="v1")
    return create_governance_result(
        requirement_version_id="REQ-1", evidence_set_id="EVID-1", assessment_id="ASS-1", challenge_set_id="CH-1",
        human_decision_id="HD-1", decision=Decision.PASS, rationale="Human approved grounded result.",
        provenance=prov, signer=_signer(), created_at="2026-09-19T00:00:00+00:00")


class _Control:
    id="2.1"; lib="SAFR"; req="Threshold governance is reviewed before deployment"
    elements=(("e1", "threshold governance review before deployment"),)


class _Conductor:
    class P: freshness_max_age_days=365
    policy=P()
    def _control(self, state): return _Control()
    def _req_elements(self, control, state):
        from governance.ai_auditor.schemas import RequirementElement
        return [RequirementElement(element_id="e1", text="threshold governance review before deployment")]


def _good_state():
    return {
        "cycle_id":"C1", "control_id":"2.1", "framework":"SAFR",
        "evidence":{"text":"Threshold governance parameters are reviewed before deployment.", "source_id":"policy.md"},
        "proposal":{"sufficiency":"full","maturity":3,"rationale":"Grounded rationale"},
        "diff":{"comparable":True,"disagreements":[]}, "challenges":[],
        "decision":{"sufficiency":"full","maturity":3,"reason":"approved"},
    }


def test_quality_gate_finalizable_when_four_dimensions_pass(monkeypatch):
    import governance.quality_gate as qg
    monkeypatch.setattr(events, "state", lambda cid: _good_state())
    monkeypatch.setattr(qg, "ReviewConductor", _Conductor)
    out=evaluate(cycle_id="C1", result=_result(), evidence_threshold=0.50, min_sources=1)
    assert out.status == GateStatus.FINALIZABLE
    assert out.evidence.passed and out.reasoning.passed and out.governance.passed and out.provenance.passed


def test_quality_gate_blocks_missing_reasoning(monkeypatch):
    import governance.quality_gate as qg
    state=_good_state(); state["proposal"]={"sufficiency":"full","maturity":3}
    monkeypatch.setattr(events, "state", lambda cid: state)
    monkeypatch.setattr(qg, "ReviewConductor", _Conductor)
    out=evaluate(cycle_id="C1", result=_result(), evidence_threshold=0.50, min_sources=1)
    assert out.status == GateStatus.BLOCKED
    assert any(x.startswith("reasoning:") for x in out.blockers)


def test_quality_gate_log_is_hash_chained(tmp_path, monkeypatch):
    import governance.quality_gate as qg
    monkeypatch.setattr(events, "state", lambda cid: _good_state())
    monkeypatch.setattr(qg, "ReviewConductor", _Conductor)
    log=QualityGateLog(tmp_path/"gate.jsonl")
    row=log.append(evaluate(cycle_id="C1", result=_result(), evidence_threshold=0.50, min_sources=1))
    assert log.read()[0].record_hash == row.record_hash
    assert log.latest_for_result(row.result_id).status == GateStatus.FINALIZABLE


def test_persist_blocks_current_when_quality_gate_blocks(tmp_path, monkeypatch):
    import governance.quality_gate as qg
    monkeypatch.setenv("WB_GAAR_QUALITY_GATE", "1")
    monkeypatch.setenv("WB_GAAR_RESULT_STORE", str(tmp_path/"results.jsonl"))
    monkeypatch.setenv("WB_GAAR_RESULT_STATE_STORE", str(tmp_path/"states.jsonl"))
    monkeypatch.setenv("WB_GAAR_QUALITY_GATE_STORE", str(tmp_path/"gates.jsonl"))
    state=_good_state(); state["proposal"]={"sufficiency":"full","maturity":3}
    monkeypatch.setattr(events, "state", lambda cid: state)
    monkeypatch.setattr(qg, "ReviewConductor", _Conductor)
    out=persist_and_set_current(_result(), actor_id="human-1", decision_id="HD-1", cycle_id="C1")
    assert out["blocked"] is True
    assert out["state_event"] is None
    assert out["quality_gate"].status == GateStatus.BLOCKED
    assert not (tmp_path/"states.jsonl").exists()

def test_persist_sets_current_when_quality_gate_finalizable(tmp_path, monkeypatch):
    import governance.quality_gate as qg
    from governance.result_contract import ResultStateLog, ValidityState
    monkeypatch.setenv("WB_GAAR_QUALITY_GATE", "1")
    monkeypatch.setenv("WB_GAAR_RESULT_STORE", str(tmp_path/"results.jsonl"))
    monkeypatch.setenv("WB_GAAR_RESULT_STATE_STORE", str(tmp_path/"states.jsonl"))
    monkeypatch.setenv("WB_GAAR_QUALITY_GATE_STORE", str(tmp_path/"gates.jsonl"))
    monkeypatch.setenv("WB_GAAR_QUALITY_EVIDENCE_THRESHOLD", "0.50")
    monkeypatch.setattr(events, "state", lambda cid: _good_state())
    monkeypatch.setattr(qg, "ReviewConductor", _Conductor)
    out=persist_and_set_current(_result(), actor_id="human-1", decision_id="HD-1", cycle_id="C1")
    assert out["blocked"] is False
    assert out["quality_gate"].status == GateStatus.FINALIZABLE
    assert ResultStateLog(tmp_path/"states.jsonl").current_state(out["result"].result_id) == ValidityState.CURRENT


@pytest.fixture(autouse=True)
def legacy_quality_gate_contract(monkeypatch):
    """This module tests WB116 compatibility; WB140 tests enforce the default gate."""
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
