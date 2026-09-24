from __future__ import annotations
import json


def _write(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_maturity_never_calls_proposed_only_dossier_admitted(tmp_path, monkeypatch):
    from governance.maturity import evaluate
    acquisition = tmp_path / "acquisition.jsonl"
    dossier = tmp_path / "dossier.jsonl"
    _write(acquisition, [{"payload": {
        "acquisition_id":"EA-1", "control_id":"M3.6", "framework":"MAS",
        "recommended_action":"REVIEW_CANDIDATES", "gaps":[],
        "preflight":{"evaluation_status":"EVALUATED"}}}])
    _write(dossier, [{"payload": {
        "dossier_id":"ED-1", "control_id":"M3.6", "framework":"MAS",
        "binding_status":"PROPOSED_ONLY", "gaps":[],
        "required_elements":[{"element":"scope", "candidate_anchors":["E01"]}]}}])
    monkeypatch.setenv("WB_GAAR_SCOUT_ACQUISITION_STORE", str(acquisition))
    monkeypatch.setenv("WB_GAAR_DOSSIER_STORE", str(dossier))
    monkeypatch.setenv("WB_GAAR_ADMISSION_STORE", str(tmp_path / "missing-admission.jsonl"))
    monkeypatch.setenv("WB_EVENT_LOG", str(tmp_path / "missing-events.jsonl"))
    monkeypatch.setenv("WB_GAAR_QUALITY_GATE_STORE", str(tmp_path / "missing-gates.jsonl"))
    monkeypatch.setenv("WB_GAAR_RESULT_STORE", str(tmp_path / "missing-results.jsonl"))
    monkeypatch.setenv("WB_GAAR_RESULT_STATE_STORE", str(tmp_path / "missing-states.jsonl"))
    monkeypatch.setenv("WB_INFERENCE_TASK_METRICS", str(tmp_path / "missing-inference.jsonl"))
    monkeypatch.setenv("WB_GAAR_REPLAY_PROOF_STORE", str(tmp_path / "missing-replay.jsonl"))
    out = evaluate()
    assert out["milestones"][0]["status"] == "GREEN"
    assert out["milestones"][1]["status"] == "GREEN"
    assert out["milestones"][2]["status"] == "NOT_PROVEN"
    assert out["status"] == "IN_PROGRESS"


def test_watcher_plain_language_never_turns_failure_green():
    from governance.watcher.operator_view import explain_status, summary
    assert explain_status("UNABLE_TO_CHECK")["plain_status"] == "Blocked"
    assert "not an all-clear" in explain_status("UNABLE_TO_CHECK")["meaning"]
    result = summary([{"source_id":"NFRA", "status":"UNABLE_TO_CHECK"}])
    assert result["counts"]["Working"] == 0
    assert "blocked" in result["next_action"].lower()


def test_watcher_summary_prioritises_publication_review():
    from governance.watcher.operator_view import summary
    result = summary([{"source_id":"HKMA", "status":"UP_TO_DATE"}], pending_publications=2)
    assert result["counts"]["Working"] == 1
    assert result["next_action"] == "Review 2 discovered publication(s)."


def test_deterministic_result_replay_verifies_all_sealed_material():
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    from governance.replay_verifier import verify
    from governance.result_contract import CanonicalSigner, Decision, ProvenanceTrail, create_governance_result

    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    signer = CanonicalSigner.from_base64("replay-test", base64.b64encode(raw).decode())
    provenance = ProvenanceTrail(
        requirement_version_id="REQ-1", evidence_set_id="EVID-1", assessment_id="ASSESS-1",
        challenge_set_id="CHALL-1", human_decision_id="HD-1", assessor_prompt_version="v1",
        model_version="model-1", model_invocation_id="run-1", human_decider_id="reviewer-1",
        human_decision_timestamp="2026-09-20T00:00:00+00:00",
    )
    result = create_governance_result(
        requirement_version_id="REQ-1", evidence_set_id="EVID-1", assessment_id="ASSESS-1",
        challenge_set_id="CHALL-1", human_decision_id="HD-1", decision=Decision.PASS,
        rationale="Governed conclusion.", provenance=provenance, signer=signer,
        created_at="2026-09-20T00:01:00+00:00",
    )
    proof = verify(result, control_id="M3.6", framework="MAS")
    assert proof["status"] == "PASS"
    assert all(proof["checks"].values())
