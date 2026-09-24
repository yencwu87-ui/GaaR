"""Eight user acceptance cases, with negative/security variants in each case.

Offline; no real credentials, network, human approval or live model claims.
"""
import copy
import json
import sqlite3

import pytest

from governance.investigation.contracts import (EvidenceExamination, ExplanationSet,
    Verification, ChallengeRecord, InvestigationConclusion)
from governance.investigation.service import admit_segments, dependency_closure, resolve_question, sha_bytes
from governance.investigation.store import canonical
from tools.wb140_demo import fixture_environment, prepare, finish


def test_01_authentic_negative_evidence_enters_assessment(tmp_path):
    engine, signers = fixture_environment(tmp_path)
    iid = prepare(engine, signers, stop="examine")
    _, v = engine.snapshot(iid)
    evidence = v["examine"].evidence
    assert evidence[0].finding_status == "gap_identified"
    assert evidence[0].integrity_status == "verified"
    assert evidence[0].source_sha256 == evidence[1].source_sha256
    assert evidence[0].purposes != evidence[1].purposes
    assert v["examine"].findings[0].status == "CONTRADICTED"
    # A forged acquisition hash must be rejected regardless of favorable content.
    with pytest.raises(ValueError, match="hash mismatch"):
        admit_segments(source_bytes=b"fake", source_sha256="0" * 64, source_id="X",
            scope=v["understand"].scope, expected_scope=v["understand"].scope,
            segments=[], authority="internal", provenance=("fixture",))


def test_02_missing_or_wrong_purpose_evidence_cannot_pass(tmp_path):
    engine, signers = fixture_environment(tmp_path / "missing")
    iid = prepare(engine, signers, missing=True)
    finish(engine, signers, iid, conclude=False)
    engine.append(iid, "conclude", InvestigationConclusion(verdict="PASS", rationale="Attempted false green"), signers["decision"])
    assert not engine.gate(iid)["assessment_finalizable"]
    assert "pass_without_element_support" in engine.gate(iid)["blockers"]
    # Policy alone cannot prove operating effectiveness, even when labeled supportive.
    engine2, signers2 = fixture_environment(tmp_path / "policy")
    iid2 = prepare(engine2, signers2, wrong_purpose=True, stop="examine")
    _, v = engine2.snapshot(iid2)
    ev = list(v["examine"].evidence)
    ev[0] = ev[0].model_copy(update={"finding_status": "supports"})
    findings = list(v["examine"].findings)
    findings[0] = findings[0].model_copy(update={"status": "SUPPORTED"})
    with pytest.raises(ValueError, match="wrong-purpose"):
        engine2._check("examine", EvidenceExamination(evidence=tuple(ev), findings=tuple(findings)), v)


def test_03_cross_system_records_rejected(tmp_path):
    engine, signers = fixture_environment(tmp_path)
    iid = prepare(engine, signers, stop="examine")
    _, v = engine.snapshot(iid)
    scope = v["understand"].scope
    for changed in (scope.model_copy(update={"system_id": "different"}),
                    scope.model_copy(update={"version": "different"}),
                    scope.model_copy(update={"period": "different"})):
        with pytest.raises(ValueError, match="cross-system"):
            admit_segments(source_bytes=b"negative record", source_sha256=sha_bytes(b"negative record"),
                source_id="X", scope=changed, expected_scope=scope, segments=[], authority="internal", provenance=("fixture",))


def test_04_alternatives_compensating_controls_and_dependencies_examined(tmp_path):
    engine, signers = fixture_environment(tmp_path)
    iid = prepare(engine, signers)
    _, v = engine.snapshot(iid)
    h = v["explain"].hypotheses[0]
    assert h.alternatives and h.compensating_controls_review
    edges = dependency_closure("ASSET.INVENTORY", v["explain"].dependencies)
    assert edges[0].downstream == "ASSET.PATCH"
    assert edges[0].status == "hypothesis"  # no automatic downstream failure
    bad = v["explain"].model_dump()
    bad["hypotheses"][0]["alternatives"] = ()
    with pytest.raises(ValueError):
        ExplanationSet.model_validate(bad)
    def broken(q):
        raise RuntimeError("offline")
    lanes = {x.name: x for x in resolve_question({}, {"facts": lambda q: [], "counterevidence": broken})}
    assert lanes["facts"].status == "COMPLETED" and not lanes["facts"].refs
    assert lanes["counterevidence"].status == "UNAVAILABLE"
    assert lanes["precedents"].status == "NOT_EVALUATED"
    # Exercise the actual bounded agent sequence, including assessor/explainer/
    # planner contracts and the full-record independent challenge callback.
    from governance.investigation.agents import run_to_checkpoint
    second, keys = fixture_environment(tmp_path / "agent-sequence")
    second.append(iid, "understand", v["understand"], keys["owner"])
    second.append(iid, "expectations", v["expectations"], keys["governance"])
    def challenge_reply(prompt):
        context = json.loads(prompt)["investigation"]
        assert context["record"]["verify"]["tests"][0]["status"] == "EXECUTED"
        return ChallengeRecord(status="COMPLETED", input_head=context["input_head"],
            reviewed_refs=("E1", "E2", "H1", "T1"),
            disproof_attempts=("Checked retirement alternative against supplied scope and export limitations",)).model_dump_json()
    outcome = run_to_checkpoint(second, iid, keys, evidence=v["examine"].evidence,
        providers={"precedents": lambda q: []}, invokes={
            "examine": lambda p: v["examine"].model_dump_json(),
            "explain": lambda p: v["explain"].model_dump_json(),
            "plan": lambda p: v["plan"].model_dump_json(),
            "challenge": challenge_reply})
    assert outcome["checkpoint"] == "COMPLETE"
    assert outcome["gate"]["assessment_finalizable"]
    assert not outcome["gate"]["deployment_authorized"]


def test_05_executed_tests_distinct_and_replayable(tmp_path):
    engine, signers = fixture_environment(tmp_path)
    iid = prepare(engine, signers)
    _, v = engine.snapshot(iid)
    assert "verify" not in v
    engine.execute_plan(iid, signers["executor"])
    _, v = engine.snapshot(iid)
    test = v["verify"].tests[0]
    result = json.loads(test.result_json)
    assert test.status == "EXECUTED"
    assert result["discovered_count"] == result["inventory_count"] == 3
    assert result["unregistered_and_missing_both"] == ["c"]
    tampered = test.model_copy(update={"result_json": '{"passed":true}'})
    with pytest.raises(ValueError, match="does not replay"):
        engine._check("verify", Verification(tests=(tampered,)), v)
    # Changing signed history or using a key authorized for another stage fails.
    with pytest.raises(ValueError):
        engine.append(iid, "challenge", {"status": "COMPLETED", "input_head": "0" * 64,
             "reviewed_refs": ["E1", "E2", "H1", "T1"], "disproof_attempts": ["test"]}, signers["assessor"])
    with sqlite3.connect(engine.store.path) as con:
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            con.execute("DELETE FROM stages")
    # User's change-management case: compare actual logs to approvals, access,
    # freezes, intended scope, incident timing and recovery evidence.
    from tools.wb140_change_fixture import package
    from governance.investigation.change_test import reconcile_changes
    data = package()
    checked = reconcile_changes(data)
    codes = {f["code"] for f in checked["findings"]}
    assert {"APPROVAL_AFTER_EXECUTION", "CREDENTIAL_NOT_APPROVED_FOR_CHANGE", "PRIVILEGE_NOT_ESTABLISHED",
            "DEVIATES_FROM_APPROVED_SCOPE", "IMPLEMENTATION_CONTENT_MISMATCH",
            "FREEZE_WITHOUT_PRIOR_EXCEPTION", "RECOVERY_NOT_ESTABLISHED"} <= codes
    assert checked["observations"][0]["code"] == "POST_INCIDENT_CHANGE"
    # A ticket-free observed change is still investigated.
    data["changes"][0]["ticket_id"] = "not-in-ticket-export"
    assert "NO_MATCHING_APPROVED_TICKET" in {f["code"] for f in reconcile_changes(data)["findings"]}
    # Collection failure cannot produce a clean change-review conclusion.
    data["collection"]["complete"] = False
    assert reconcile_changes(data)["status"] == "NOT_COMPARABLE"
    # Resolve approval/scope/access/freeze/recovery differences. Incident proximity
    # remains an observation, not a manufactured breach.
    data = package()
    change, ticket = data["changes"][0], data["tickets"][0]
    ticket.update(approved_at="2026-09-19T09:30:00Z", allowed_actions=change["actions"],
                  allowed_credentials=[change["credential_id"]], approved_spec_hash=change["actual_spec_hash"])
    data["privilege_grants"] = [{"grant_id": "G1", "actor_id": change["actor_id"], "credential_id": change["credential_id"],
        "approved_by": "privilege-owner", "approved_at": "2026-09-19T09:30:00Z", "valid_from": "2026-09-19T10:00:00Z",
        "valid_until": "2026-09-19T11:00:00Z", "allowed_targets": ["db-prod"], "allowed_actions": change["actions"]}]
    data["freeze_exceptions"] = [{"freeze_id": "FREEZE-1", "event_id": change["event_id"],
        "approved_by": "freeze-owner", "approved_at": "2026-09-19T09:30:00Z"}]
    data["recoveries"] = [{"event_id": change["event_id"], "method": "rollback", "approved_by": "recovery-owner",
        "status": "succeeded", "completed_at": "2026-09-19T10:45:00Z"}]
    assert not reconcile_changes(data)["findings"]
    assert reconcile_changes(data)["observations"]
    change_engine, change_keys = fixture_environment(tmp_path / "signed-change")
    change_id = prepare(change_engine, change_keys, scenario="change")
    change_gate = finish(change_engine, change_keys, change_id)
    assert change_gate["assessment_finalizable"] and not change_gate["deployment_authorized"]
    _, change_record = change_engine.snapshot(change_id)
    assert change_record["verify"].tests[0].tool == "change_reconciliation"
    assert change_record["verify"].tests[0].status == "EXECUTED"


def test_06_material_risk_reaches_full_challenge_and_disposition(tmp_path):
    engine, signers = fixture_environment(tmp_path)
    iid = prepare(engine, signers)
    engine.execute_plan(iid, signers["executor"])
    packet = engine.challenge_input(iid)
    assert set(packet["record"]) == {"understand", "expectations", "examine", "explain", "plan", "verify"}
    assert packet["record"]["explain"]["hypotheses"][0]["alternatives"]
    with pytest.raises(ValueError, match="omitted"):
        engine.append(iid, "challenge", ChallengeRecord(status="COMPLETED", input_head=packet["input_head"],
            reviewed_refs=("E1",), disproof_attempts=("Skipped the wider risks",)), signers["challenger"])
    challenge = ChallengeRecord(status="COMPLETED", input_head=packet["input_head"],
        reviewed_refs=("E1", "E2", "H1", "T1"), disproof_attempts=("Examined timing and retirement alternatives",))
    engine.append(iid, "challenge", challenge, signers["challenger"])
    engine.append(iid, "conclude", InvestigationConclusion(verdict="ADVERSE", rationale="No risk disposition"), signers["decision"])
    assert "material_risk_undispositioned:H1" in engine.gate(iid)["blockers"]


def test_07_adverse_finalizable_without_deployment_and_legacy_gate_wired(tmp_path, monkeypatch):
    engine, signers = fixture_environment(tmp_path)
    iid = prepare(engine, signers)
    gate = finish(engine, signers, iid)
    assert gate["assessment_finalizable"] and gate["verdict"] == "ADVERSE"
    assert not gate["deployment_authorized"]
    assert all(x["route"] == "policy_auto" for x in gate["escalation_decisions"])
    from governance.investigation import bridge
    _, v = engine.snapshot(iid)
    state = {"control_id": "ASSET.INVENTORY", "framework": "INTERNAL-DEMO",
        "evidence": {"text": "\n".join(x.text for x in v["examine"].evidence)},
        "governance_context": {"investigation_id": iid, "investigation_head": gate["head"],
           "requirement_version_id": "demo-v1", "assessment_scope": v["understand"].scope.model_dump()}}
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(tmp_path / "public_config.json"))
    assert bridge.cycle_gate(state)["assessment_finalizable"]
    bad = copy.deepcopy(state)
    bad["governance_context"]["investigation_head"] = "0" * 64
    assert not bridge.cycle_gate(bad)["assessment_finalizable"]
    bad = copy.deepcopy(state)
    bad["evidence"] = {"text": "another system"}
    assert not bridge.cycle_gate(bad)["assessment_finalizable"]
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
    assert bridge.required(state)  # bound records cannot downgrade to legacy mode
    # The existing persistence boundary blocks before appending a result, even
    # when the legacy quality gate is disabled.
    import governance.result_integration as integration
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "1")
    monkeypatch.setenv("WB_GAAR_QUALITY_GATE", "0")
    monkeypatch.setenv("WB_GAAR_RESULT_STORE", str(tmp_path / "results.jsonl"))
    blocked = integration.persist_and_set_current(object(), actor_id="fixture", decision_id="fixture", governance_context={})
    assert blocked["blocked"] and blocked["state_event"] is None
    # Real signed FAIL result through the existing quality/persistence path. The
    # test isolates state lookup/control registry, not signatures or result logic.
    from types import SimpleNamespace
    import events
    import governance.quality_gate as qg
    from governance.result_contract import ProvenanceTrail, create_governance_result, Decision
    state.update(cycle_id="C-SYNTHETIC", proposal={"sufficiency": "partial", "maturity": 2, "rationale": "Identity gap established"},
                 diff={"comparable": True}, challenges=[], decision={"reason": "Synthetic adverse decision"})
    monkeypatch.setattr(events, "state", lambda cid: state)
    monkeypatch.setattr(qg, "ReviewConductor", lambda: SimpleNamespace(
        _control=lambda s: None, _req_elements=lambda c, s: [],
        policy=SimpleNamespace(freshness_max_age_days=90)))
    provenance = ProvenanceTrail(requirement_version_id="demo-v1", evidence_set_id="E",
        assessment_id="A", challenge_set_id="CH", human_decision_id="HD", assessor_prompt_version="wb140",
        model_version="SCRIPTED_SYNTHETIC", model_invocation_id="I", human_decider_id="SYNTHETIC-HUMAN-ROLE",
        human_decision_timestamp="2026-09-20T00:00:00Z", rule_versions={"investigation_id": iid, "investigation_head": gate["head"]})
    result = create_governance_result(requirement_version_id="demo-v1", evidence_set_id="E", assessment_id="A",
        challenge_set_id="CH", human_decision_id="HD", decision=Decision.FAIL, rationale="Synthetic adverse assessment",
        provenance=provenance, signer=signers["decision"])
    evaluated = qg.evaluate(cycle_id="C-SYNTHETIC", result=result)
    assert evaluated.status.value == "FINALIZABLE"  # zero lexical coverage does not erase the valid investigation
    assert not evaluated.deployment_authorized
    monkeypatch.setenv("WB_GAAR_RESULT_STATE_STORE", str(tmp_path / "result_states.jsonl"))
    persisted = integration.persist_and_set_current(result, actor_id="SYNTHETIC-HUMAN-ROLE", decision_id="HD", cycle_id="C-SYNTHETIC")
    assert not persisted["blocked"] and not persisted["deployment_authorized"]
    assert persisted["result"].decision == Decision.FAIL
    from inference.policy import governed_colibri_decision
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    routing = governed_colibri_decision("complex", engine.inference_signals(iid, "challenge"))
    assert "broader_risk_corroborated" in routing["reasons"]


def test_08_required_failures_block_decisions(tmp_path):
    for option, expected in (("unavailable", "retrieval:counterevidence:UNAVAILABLE"),
                             ("not_evaluated", "element_examination_not_evaluated"),
                             ("unknown_tool", "test:T1:UNAVAILABLE")):
        engine, signers = fixture_environment(tmp_path / option)
        iid = prepare(engine, signers, **{option: True})
        gate = finish(engine, signers, iid)
        assert not gate["assessment_finalizable"]
        assert not gate["deployment_authorized"]
        assert expected in gate["blockers"]
