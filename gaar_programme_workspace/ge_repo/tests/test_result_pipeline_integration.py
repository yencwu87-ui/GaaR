from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

import events
from core import cycle
from governance.result_contract import ResultStateLog, ValidityState
from governance.result_store import ResultStore


def _test_key() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode("ascii")


def _prepare_cycle():
    cid = cycle.start("M3.6", actor="system")
    cycle.bind_evidence(
        cid,
        {
            "text": "Independent evaluation report covers the deployed model version and retains test results.",
            "retrieval": {
                "schema": "evidence-intelligence.1",
                "matches": [],
                "sufficiency": {"status": "PASS"},
            },
        },
    )
    cycle.record_read(
        cid,
        {
            "sufficiency": "full",
            "maturity": 4,
            "reason": "The retained independent evaluation report covers the deployed model and records the test results.",
        },
        actor="reviewer-01",
    )
    return cid


def test_gaar_result_compiler_is_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(events, "LOG", tmp_path / "events.jsonl")
    monkeypatch.delenv("WB_GAAR_RESULT_ENABLE", raising=False)
    cid = _prepare_cycle()

    rec = cycle.decide(
        cid,
        sufficiency="full",
        maturity=4,
        reviewer="reviewer-01",
        reason="The retained independent evaluation report covers the deployed model and records the test results.",
    )

    assert "governance_result_id" not in rec
    assert not (tmp_path / "results.jsonl").exists()


def test_gaar_result_compiler_wires_human_decision_to_sealed_result(monkeypatch, tmp_path):
    # Legacy contract fixture; mandatory investigation defaults are tested separately.
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
    monkeypatch.setattr(events, "LOG", tmp_path / "events.jsonl")
    monkeypatch.setenv("WB_GAAR_RESULT_ENABLE", "1")
    monkeypatch.setenv("WB_GAAR_RESULT_SIGNING_KEY_B64", _test_key())
    monkeypatch.setenv("WB_GAAR_RESULT_KEY_ID", "test-gaar-key")
    monkeypatch.setenv("WB_GAAR_RESULT_STORE", str(tmp_path / "results.jsonl"))
    monkeypatch.setenv("WB_GAAR_RESULT_STATE_STORE", str(tmp_path / "result_state_events.jsonl"))

    cid = _prepare_cycle()
    rec = cycle.decide(
        cid,
        sufficiency="full",
        maturity=4,
        reviewer="reviewer-01",
        reason="The retained independent evaluation report covers the deployed model and records the test results.",
    )

    assert rec["governance_result_id"]
    assert rec["human_decision_id"]
    assert rec["governance_result"]["result_id"] == rec["governance_result_id"]
    assert rec["governance_result"]["content_hash"]

    state = cycle.state(cid)
    assert state["stage"] == "decided"
    assert state["decision"]["governance_result_id"] == rec["governance_result_id"]
    assert state["decision"]["human_decision_id"] == rec["human_decision_id"]

    stored = ResultStore(tmp_path / "results.jsonl").read()
    assert len(stored) == 1
    assert stored[0].result_id == rec["governance_result_id"]
    assert stored[0].human_decision_id == rec["human_decision_id"]

    state_log = ResultStateLog(tmp_path / "result_state_events.jsonl")
    assert state_log.current_state(stored[0].result_id) == ValidityState.CURRENT
    assert state_log.read()[0].decision_id == rec["human_decision_id"]

    assert events.verify(tmp_path / "events.jsonl")["intact"] is True
