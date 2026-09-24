from __future__ import annotations

from pathlib import Path
import base64
import copy
import yaml

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from governance.change_intelligence import (
    AuthorityEvidence,
    ImpactDecision,
    assess_impact,
    assess_source_authority,
    detect_governance_change,
    build_review_required_events,
)
from governance.change_runtime import ChangeImpactStore, apply_change
from governance.reassessment import (
    ReassessmentCaseStore,
    begin_case_execution,
    complete_with_replacement,
    open_reassessment_case,
    reconfirm_without_replacement,
)
from governance.result_contract import (
    CanonicalSigner,
    Decision,
    ProvenanceTrail,
    ResultStateLog,
    ValidityState,
    create_governance_result,
)
from governance.result_store import ResultStore
from governance.triangulation import SourceRegistry

ROOT = Path(__file__).resolve().parents[1]


def _signer() -> CanonicalSigner:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return CanonicalSigner.from_base64("test-reassessment", base64.b64encode(raw).decode())


def _result(req_id: str = "REQ-MAS-M3.6-v2", evidence: str = "EVID-1", n: str = "1"):
    p = ProvenanceTrail(
        requirement_version_id=req_id,
        evidence_set_id=evidence,
        assessment_id=f"ASSESS-{n}",
        challenge_set_id=f"CHALL-{n}",
        human_decision_id=f"HD-{n}",
        assessor_prompt_version="assessor-test-v1",
        model_version="ollama:test",
        model_invocation_id=f"run-{n}",
        human_decider_id="reviewer-1",
        human_decision_timestamp="2026-09-18T09:00:00+00:00",
    )
    return create_governance_result(
        requirement_version_id=req_id,
        evidence_set_id=evidence,
        assessment_id=f"ASSESS-{n}",
        challenge_set_id=f"CHALL-{n}",
        human_decision_id=f"HD-{n}",
        decision=Decision.PASS,
        rationale="Current evidence supports the governance conclusion.",
        provenance=p,
        signer=_signer(),
        created_at=f"2026-09-18T09:01:0{n}+00:00",
    )


def _binding_change():
    registry = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = registry.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    authority = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS",
            jurisdiction="Singapore",
            legal_basis="applicable MAS Notice under governing statute",
            enforcement_status="binding notice requirements",
            applicability="governed MAS scope",
            applicable=True,
        ),
        as_of="2026-09-18",
    )
    current = {"version": "2", "controls": {"M3.6": {"requirement": "current"}}}
    candidate = {"version": "3", "controls": {"M3.6": {"requirement": "updated material requirement"}}}
    return detect_governance_change(
        current,
        candidate,
        source=source,
        authority=authority,
        detected_on="2026-09-18",
        applicability="governed MAS scope",
    )


def test_reassessment_runtime_emits_only_current_review_event(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_GAAR_CHANGE_INTELLIGENCE", "1")
    old = _result()
    store = ResultStore(tmp_path / "results.jsonl")
    state = ResultStateLog(tmp_path / "states.jsonl")
    # Seed old result as CURRENT using an existing human approval event.
    from governance.result_contract import approve_result
    store.append(old)
    state.append(approve_result(old, actor_id="reviewer-1", decision_id="HD-1", reason="approved"))

    change = _binding_change()
    impact = assess_impact(
        change,
        results=[old],
        current_requirement_version_ids={"M3.6": old.requirement_version_id},
        control_materiality={"M3.6": "HIGH"},
    )
    assert impact.decision == ImpactDecision.REVIEW_REQUIRED

    outcome = apply_change(
        change,
        impact,
        result_store=store,
        state_log=state,
        change_store=ChangeImpactStore(tmp_path / "change_impact.jsonl"),
    )
    assert len(outcome["state_events"]) == 1
    e = outcome["state_events"][0]
    assert e.from_state == ValidityState.CURRENT
    assert e.to_state == ValidityState.REVIEW_REQUIRED
    assert e.actor_type.value == "SYSTEM"
    assert e.decision_id is None
    assert e.trigger_id == change.change_id


def test_reassessment_case_can_reconfirm_same_result(tmp_path):
    old = _result()
    from governance.result_contract import approve_result
    state = ResultStateLog(tmp_path / "states.jsonl")
    state.append(approve_result(old, actor_id="reviewer-1", decision_id="HD-1", reason="approved"))

    change = _binding_change()
    impact = assess_impact(
        change,
        results=[old],
        current_requirement_version_ids={"M3.6": old.requirement_version_id},
    )
    review_event = build_review_required_events(
        change, impact, results=[old], current_result_ids={old.result_id}, prev_hash=state.last_hash()
    )[0]
    state.append(review_event)

    cases = ReassessmentCaseStore(tmp_path / "cases.jsonl")
    case = open_reassessment_case(review_event=review_event, change=change, impact=impact, result=old, store=cases)
    begin_case_execution(case, result=old, state_log=state, timestamp="2026-09-18T09:05:00+00:00")
    assert state.current_state(old.result_id) == ValidityState.REASSESSING

    event = reconfirm_without_replacement(
        case,
        result=old,
        state_log=state,
        actor_id="reviewer-1",
        decision_id="HD-RECHECK-1",
        timestamp="2026-09-18T09:10:00+00:00",
    )
    assert event.from_state == ValidityState.REASSESSING
    assert event.to_state == ValidityState.CURRENT
    assert event.actor_type.value == "HUMAN"
    assert state.current_state(old.result_id) == ValidityState.CURRENT


def test_reassessment_case_can_supersede_with_new_result(tmp_path):
    old = _result()
    new = _result(req_id="REQ-MAS-M3.6-v3", evidence="EVID-2", n="2")
    # Explicit parent lineage required.
    new = new.model_copy(update={"parent_result_id": old.result_id, "supersedes_result_id": old.result_id})

    from governance.result_contract import approve_result
    state = ResultStateLog(tmp_path / "states.jsonl")
    result_store = ResultStore(tmp_path / "results.jsonl")
    result_store.append(old)
    result_store.append(new)
    state.append(approve_result(old, actor_id="reviewer-1", decision_id="HD-1", reason="approved"))

    change = _binding_change()
    impact = assess_impact(
        change,
        results=[old],
        current_requirement_version_ids={"M3.6": old.requirement_version_id},
    )
    review_event = build_review_required_events(
        change, impact, results=[old], current_result_ids={old.result_id}, prev_hash=state.last_hash()
    )[0]
    state.append(review_event)
    cases = ReassessmentCaseStore(tmp_path / "cases.jsonl")
    case = open_reassessment_case(review_event=review_event, change=change, impact=impact, result=old, store=cases)
    begin_case_execution(case, result=old, state_log=state, timestamp="2026-09-18T09:05:00+00:00")

    old_event, new_event = complete_with_replacement(
        case,
        old_result=old,
        new_result=new,
        state_log=state,
        actor_id="reviewer-1",
        decision_id="HD-REASSESS-2",
        timestamp="2026-09-18T09:20:00+00:00",
    )
    assert old_event.from_state == ValidityState.REASSESSING
    assert old_event.to_state == ValidityState.SUPERSEDED
    assert old_event.replacement_result_id == new.result_id
    assert new_event.from_state == ValidityState.FINALIZED
    assert new_event.to_state == ValidityState.CURRENT
    assert state.current_state(old.result_id) == ValidityState.SUPERSEDED
    assert state.current_state(new.result_id) == ValidityState.CURRENT


def test_real_m3_6_requirement_corpus_is_versionable():
    doc = yaml.safe_load((ROOT / "requirements/mas.yaml").read_text())
    req = doc["controls"]["M3.6"]["requirement"]
    assert "independently validated" in req.lower()
    candidate = copy.deepcopy(doc)
    candidate["version"] = int(doc["version"]) + 1
    candidate["controls"]["M3.6"]["requirement"] = req + " Re-validation is required after material evaluation-method changes."
    assert candidate["controls"]["M3.6"]["requirement"] != req
