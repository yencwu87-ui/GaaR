"""The base-package core guards the register listed as "Test required" (kit v15 to v18).

Each test reaches one refusal through a real configuration, not a stub of the guard, and expects its exact
message: the whole message, anchored, so a different refusal that happens to share words cannot pass it
(defect D15). Where a check records its refusal instead of raising (doctor), the recorded reason is compared
whole. The register (docs/quality/unexercised_guards.md) moves each of these from "Test required" to
"Reached by a test".
"""
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from tests.test_guards_exercised import _cli, _load, series  # noqa: F401  (series is a fixture)


def exactly(message):
    return "^" + re.escape(message) + "$"


def _scope(config, root, iid="CHG-WEEKLY-2026-09-29"):
    from governance.investigation import InvestigationEngine, InvestigationStore
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    return engine.snapshot(iid)[1]["understand"].scope


def _static_collector(root, name, raw, scope, evidence_id):
    (root / name).write_bytes(raw)
    return {"root": ".", "path": name, "source_id": name, "sha256": hashlib.sha256(raw).hexdigest(),
            "scope": scope.model_dump(), "authority": "internal", "provenance": ["test"],
            "segments": [{"start": 0, "end": len(raw.decode()), "evidence_id": evidence_id, "element_ids": ["e1"],
                          "purposes": ["operating_record"]}]}


# ---------------------------------------------------------------------------------------------------------
# runtime.py — signing identities
# ---------------------------------------------------------------------------------------------------------

def test_a_signer_whose_key_is_not_trusted_for_its_role_is_refused(series):
    from governance.operations.runtime import signers_for
    _, config_path = series
    config, root = _load(config_path)
    config["trusted_keys"][config["signers"]["assessor"]["key_id"]]["roles"] = ["executor"]
    with pytest.raises(ValueError, match=exactly("untrusted signing identity for assessor")):
        signers_for(config, root)


def test_a_signer_whose_trusted_public_key_differs_is_refused(series):
    from governance.operations.runtime import signers_for
    _, config_path = series
    config, root = _load(config_path)
    challenger = config["trusted_keys"][config["signers"]["challenger"]["key_id"]]
    challenger["public_key"] = config["trusted_keys"][config["signers"]["assessor"]["key_id"]]["public_key"]
    with pytest.raises(ValueError, match=exactly("untrusted signing identity for challenger")):
        signers_for(config, root)


def test_a_challenger_sharing_the_assessors_key_is_refused(series):
    from governance.operations.runtime import signers_for
    _, config_path = series
    config, root = _load(config_path)
    assessor = config["signers"]["assessor"]
    config["trusted_keys"][assessor["key_id"]]["roles"].append("challenger")   # trusted for both: only independence fails
    config["signers"]["challenger"] = dict(assessor)
    with pytest.raises(ValueError, match=exactly("independent challenger key required")):
        signers_for(config, root)
    assert signers_for(*_load(config_path))                                     # the unaltered workspace passes


# ---------------------------------------------------------------------------------------------------------
# runtime.py — the source registry (doctor records the refusal as the source's reason)
# ---------------------------------------------------------------------------------------------------------

def _doctor_reason(config, root, sid):
    from governance.operations.runtime import doctor
    report = doctor(config, root)
    assert report["status"] == "BLOCKED" and "source:" + sid in report["blockers"]
    return report["checks"]["source:" + sid]


def test_a_source_registered_under_a_different_id_is_refused(series):
    _, config_path = series
    config, root = _load(config_path)
    config["sources"] = {"SOME-OTHER-ID": config["sources"]["INTERNAL-CHANGE.MGMT"]}
    assert _doctor_reason(config, root, "SOME-OTHER-ID") == {
        "status": "UNAVAILABLE", "reason": "registry source identity mismatch"}


def _fixture_source(config, root, content=b"evaluation fixture snapshot"):
    (root / "fixture.snapshot").write_bytes(content)
    config["sources"]["FIXTURE"] = {"source_id": "FIXTURE", "evaluation_fixture": True, "authority": "internal",
                                    "snapshot_path": "fixture.snapshot",
                                    "sha256": hashlib.sha256(b"evaluation fixture snapshot").hexdigest()}


@pytest.mark.parametrize("change", [
    lambda c: c.update(operation_mode="production"),
    lambda c: c["sources"]["FIXTURE"].update(authority="binding"),
])
def test_an_evaluation_fixture_source_is_refused_outside_evaluation_mode(series, change):
    _, config_path = series
    config, root = _load(config_path)
    _fixture_source(config, root)
    change(config)
    assert _doctor_reason(config, root, "FIXTURE") == {
        "status": "UNAVAILABLE", "reason": "evaluation fixture source is forbidden outside evaluation mode"}


def test_a_changed_evaluation_fixture_snapshot_is_refused(series):
    from governance.operations.runtime import doctor
    _, config_path = series
    config, root = _load(config_path)
    assert config["operation_mode"] == "evaluation"
    _fixture_source(config, root)
    assert doctor(config, root)["checks"]["source:FIXTURE"] == {"status": "AVAILABLE"}      # unchanged: accepted
    (root / "fixture.snapshot").write_bytes(b"evaluation fixture snapshot, edited")
    assert _doctor_reason(config, root, "FIXTURE") == {
        "status": "UNAVAILABLE", "reason": "evaluation fixture source hash mismatch"}


# ---------------------------------------------------------------------------------------------------------
# runtime.py — the static file collector
# ---------------------------------------------------------------------------------------------------------

def test_a_static_collector_path_escaping_its_root_is_refused(series):
    from governance.operations.runtime import collect
    _, config_path = series
    config, root = _load(config_path)
    scope = _scope(config, root)
    (root / "approved").mkdir()
    item = _static_collector(root, "outside.json", b'{"x": 1}', scope, "E1")
    item.update(root="approved", path="../outside.json")                 # the file exists; it is simply not inside
    with pytest.raises(ValueError, match=exactly("collector path outside approved root")):
        collect({**config, "collectors": [item], "periodic_evidence": None}, root, scope)


def test_a_static_export_over_budget_is_refused(series):
    from governance.operations.runtime import collect
    _, config_path = series
    config, root = _load(config_path)
    scope = _scope(config, root)
    item = _static_collector(root, "big.json", b'{"x": 1}', scope, "E1")
    with (root / "big.json").open("wb") as handle:
        handle.truncate(20_000_001)                                       # sparse: no real 20 MB written
    with pytest.raises(ValueError, match=exactly("evidence export exceeds collector budget")):
        collect({**config, "collectors": [item], "periodic_evidence": None}, root, scope)


def test_two_collectors_emitting_the_same_evidence_identity_are_refused(series):
    from governance.operations.runtime import collect
    _, config_path = series
    config, root = _load(config_path)
    scope = _scope(config, root)
    first = _static_collector(root, "a.json", b'{"a": 1}', scope, "E1")
    second = _static_collector(root, "b.json", b'{"b": 2}', scope, "E1")
    assert len(collect({**config, "collectors": [first], "periodic_evidence": None}, root, scope)) == 1
    with pytest.raises(ValueError, match=exactly("duplicate collected evidence identity")):
        collect({**config, "collectors": [first, second], "periodic_evidence": None}, root, scope)


# ---------------------------------------------------------------------------------------------------------
# runtime.py — the production entry point
# ---------------------------------------------------------------------------------------------------------

def test_the_production_entry_point_rejects_a_synthetic_investigation(series):
    import sys
    from governance.investigation import InvestigationEngine, InvestigationStore
    from governance.operations.runtime import doctor, run
    home, config_path = series
    config, root = _load(config_path)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import gaar_pilot
    _, owner = gaar_pilot.load_human(str(home / ".gaar-test-keys/owner.key"), "Test Owner", "owner", root)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    values = engine.snapshot("CHG-WEEKLY-2026-09-29")[1]
    iid = "SYNTHETIC-PROBE"
    engine.append(iid, "understand", values["understand"].model_copy(update={"investigation_id": iid, "synthetic": True}), owner)
    engine.append(iid, "expectations", values["expectations"], owner)
    config["expected_heads"][iid] = engine.snapshot(iid)[0][-1]["record_hash"]
    assert doctor(config, root)["status"] == "CONFIGURED"                 # nothing earlier stops it
    with pytest.raises(ValueError, match=exactly("production entry point rejects synthetic investigations")):
        run(config, root, iid)


# ---------------------------------------------------------------------------------------------------------
# lifecycle.py
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("pin", ["missing", "other_result"])
def test_a_result_event_pinned_to_a_state_that_is_not_there_is_refused(series, tmp_path, pin):
    from governance.production.journal import Journal
    from governance.production.lifecycle import actor_signer, verify_state_pins
    from governance.result_contract import ResultStateLog
    _, config_path = series
    config, root = _load(config_path)
    sealer = actor_signer(config, root, "result_sealer")
    state_log = ResultStateLog(tmp_path / "states.jsonl")
    journal = Journal(tmp_path / "operations.sqlite", config["trusted_keys"])
    verify_state_pins(journal, state_log)                                 # nothing pinned yet: accepted
    if pin == "missing":
        state_hash = "f" * 64
    else:
        state_hash = _one_state_event(state_log)                          # a real state, of another result
    journal.append("result_current", "result_current",
                   {"result_id": "RESULT-X", "state_event_hash": state_hash, "state": "CURRENT"}, sealer, "result_sealer")
    with pytest.raises(ValueError, match=exactly("signed result-state anchor is missing or altered")):
        verify_state_pins(journal, state_log)


def _one_state_event(state_log):
    from governance.result_contract import (CanonicalSigner, Decision, ProvenanceTrail, approve_result,
                                            create_governance_result)
    import base64
    signer = CanonicalSigner.from_base64("TEST-SEALER", base64.b64encode(b"\x01" * 32).decode())
    ids = {"requirement_version_id": "r", "evidence_set_id": "e", "assessment_id": "a", "challenge_set_id": "c",
           "human_decision_id": "d"}
    provenance = ProvenanceTrail(**ids, assessor_prompt_version="p", model_version="m", model_invocation_id="i",
                                 human_decider_id="h", human_decision_timestamp="2026-09-20T00:00:00Z",
                                 workflow_step_timestamps={}, rule_versions={}, retrieval_receipt_id="x",
                                 retrieval_pipeline_version="y")
    result = create_governance_result(**ids, decision=Decision.FAIL, rationale="another result", provenance=provenance,
                                      signer=signer, created_at="2026-09-20T00:00:00Z")
    state_log.append(approve_result(result, actor_id="h", decision_id="d", reason="another result",
                                    timestamp="2026-09-20T00:00:00Z", prev_hash=state_log.last_hash()))
    return state_log.read()[-1].event_hash


def _inconclusive_sealable_case(tmp_path, monkeypatch):
    """A real run of the programme fixture whose record is INCONCLUSIVE: nothing observed contradicts the
    obligation, and no executed test found anything, so the verdict cannot be ADVERSE."""
    import governance.production.lifecycle as life
    import governance.production.orchestrator as orch
    from governance.investigation.store import canonical
    from governance.production.journal import Journal
    from governance.production.qualification import fingerprint
    from tests.test_wb143_149_programme import environment
    config, engine, signers, iid, _ = environment(tmp_path, monkeypatch, seal_fixture=True)
    package = json.loads((tmp_path / "E1.json").read_text())
    package["changes"] = []
    raw = canonical(package).encode()
    (tmp_path / "E1.json").write_bytes(raw)
    config["collectors"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    config["collectors"][0]["segments"][0]["end"] = len(raw.decode())
    scripted = orch.LiveClient.__call__

    def nothing_contradicted(client, prompt):
        out = scripted(client, prompt)
        if client.stage == "examine":
            data = json.loads(out)
            data["findings"][0]["status"] = "NOT_EVIDENCED"
            return canonical(data)
        return out
    monkeypatch.setattr(orch.LiveClient, "__call__", nothing_contradicted)
    config["operation_mode"] = "production"
    qualified = {"status": "QUALIFIED", "fingerprint": fingerprint(config)}
    monkeypatch.setattr(orch, "qualification_check", lambda *a: qualified)
    monkeypatch.setattr(life, "check_qualification", lambda *a: qualified)
    monkeypatch.setattr(life, "actor_signer", lambda c, r, role: signers[role])
    assert orch.run(config, tmp_path, iid)["checkpoint"] == "COMPLETE"
    rows, values = engine.snapshot(iid)
    assert values["conclude"].verdict == "INCONCLUSIVE"

    def decide(**extra):
        payload = {"investigation_id": iid, "investigation_head": rows[-1]["record_hash"], "decision": "FAIL",
                   "decision_id": "TEST-DECISION", "at": "2026-09-20T00:00:00Z",
                   "rationale": "Test-only decision on an inconclusive record; not production proof", **extra}
        approver = signers["owner"]
        document = {"payload": payload, "key_id": approver.key_id, "signature": approver.sign(canonical(payload).encode())}
        (tmp_path / "decision.json").write_text(canonical(document))
        config["result_decisions"] = {iid: "decision.json"}
    journal = Journal(orch.case_directory(config, tmp_path, iid) / "operations.sqlite", config["trusted_keys"])
    return config, engine, journal, iid, decide


def test_sealing_an_inconclusive_record_without_the_assurance_only_mapping_is_refused(tmp_path, monkeypatch):
    import governance.production.lifecycle as life
    config, engine, journal, iid, decide = _inconclusive_sealable_case(tmp_path, monkeypatch)
    decide()                                                              # FAIL, but not marked assurance-only
    with pytest.raises(ValueError, match=exactly(
            "inconclusive requires explicit assurance-only FAIL mapping; no operational breach inferred")):
        life.seal(config, tmp_path, iid, engine, journal)
    assert journal.latest("result_sealed") is None
    decide(assurance_only_fail=True)                                      # the explicit mapping is the only difference
    assert life.seal(config, tmp_path, iid, engine, journal)["investigation_verdict"] == "INCONCLUSIVE"


def test_a_sealed_event_naming_a_different_investigation_head_is_refused(tmp_path, monkeypatch):
    """Registered in kit v15 as 'proposed defensive-unreachable'. The proposal was wrong: no store tampering is
    needed. A holder of the trusted result_sealer key can append a second, validly signed result_sealed event
    that carries the same human approval but a result bound to another head, and seal() must refuse it."""
    import governance.production.lifecycle as life
    from governance.result_contract import GovernanceResult, create_governance_result
    config, engine, journal, iid, decide = _inconclusive_sealable_case(tmp_path, monkeypatch)
    decide(assurance_only_fail=True)
    life.seal(config, tmp_path, iid, engine, journal)
    sealed = journal.latest("result_sealed")
    result = GovernanceResult.model_validate(sealed["payload"]["result"])
    provenance = result.provenance.model_copy(update={"rule_versions": {**result.provenance.rule_versions,
                                                                        "investigation_head": "0" * 64}})
    ids = {k: getattr(result, k) for k in ("requirement_version_id", "evidence_set_id", "assessment_id",
                                           "challenge_set_id", "human_decision_id")}
    sealer = life.actor_signer(config, tmp_path, "result_sealer")
    other = create_governance_result(**ids, decision=result.decision, rationale=result.rationale, provenance=provenance,
                                     signer=sealer, created_at=result.created_at)
    journal.append("sealed_result:again", "result_sealed", {**sealed["payload"], "result": other.model_dump(mode="json")},
                   sealer, "result_sealer")
    with pytest.raises(ValueError, match=exactly("sealed result belongs to a different investigation head")):
        life.seal(config, tmp_path, iid, engine, journal)
