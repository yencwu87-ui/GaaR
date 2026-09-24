from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

import events
from governance.change_intelligence import (
    AuthorityEvidence,
    assess_impact,
    assess_source_authority,
    build_review_required_events,
    detect_governance_change,
)
from governance.reassessment import start_reassessment_cycle
from governance.result_contract import (
    CanonicalSigner,
    Decision,
    ProvenanceTrail,
    ResultStateLog,
    ValidityState,
    approve_result,
    create_governance_result,
)
from governance.result_integration import build_result_inputs, persist_and_set_current
from governance.result_store import ResultStore
from governance.triangulation import SourceRegistry

ROOT = Path(__file__).resolve().parents[1]


def _signer() -> CanonicalSigner:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return CanonicalSigner.from_base64("test-d-live", base64.b64encode(raw).decode())


def _result(*, req="REQ-MAS-M3.6-v2", evidence="EVID-SEALED-1", hd="HD-OLD"):
    p = ProvenanceTrail(
        requirement_version_id=req,
        evidence_set_id=evidence,
        assessment_id="ASSESS-OLD",
        challenge_set_id="CHALL-OLD",
        human_decision_id=hd,
        assessor_prompt_version="assessor-test-v1",
        model_version="ollama:test",
        model_invocation_id="run-old",
        human_decider_id="reviewer-1",
        human_decision_timestamp="2026-09-18T09:00:00+00:00",
    )
    return create_governance_result(
        requirement_version_id=req,
        evidence_set_id=evidence,
        assessment_id="ASSESS-OLD",
        challenge_set_id="CHALL-OLD",
        human_decision_id=hd,
        decision=Decision.PASS,
        rationale="Existing result is current.",
        provenance=p,
        signer=_signer(),
        created_at="2026-09-18T09:01:00+00:00",
    )


def _change_and_impact(old):
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
    current = {"version": "2", "controls": {"M3.6": {"requirement": "current requirement"}}}
    candidate = {
        "version": "3",
        "controls": {
            "M3.6": {
                "requirement": "Updated material requirement requiring re-validation after material method changes.",
                "elements": [{"id": "M3.6.1", "text": "Independent validation is performed."}],
            }
        },
    }
    change = detect_governance_change(
        current,
        candidate,
        source=source,
        authority=authority,
        detected_on="2026-09-18",
        applicability="governed MAS scope",
    )
    impact = assess_impact(
        change,
        results=[old],
        current_requirement_version_ids={"M3.6": old.requirement_version_id},
        control_materiality={"M3.6": "HIGH"},
    )
    return change, impact, candidate


def _seed_source_cycle(tmp_path: Path, old):
    events.LOG = tmp_path / "events.jsonl"
    cid = "M3-6-sourcecycle"
    events.append(
        "cycle_started", cycle_id=cid, actor="system", control_id="M3.6", framework="MAS",
        payload={"title": "Model validation"},
    )
    evidence = {
        "text": "Independent validation evidence package.",
        "file_name": "validation.md",
        "bundle_hash": "bundle-old",
    }
    events.append(
        "evidence_bound", cycle_id=cid, actor="system", control_id="M3.6", framework="MAS",
        payload=evidence,
    )
    events.append(
        "decided", cycle_id=cid, actor="reviewer-1", control_id="M3.6", framework="MAS",
        payload={"governance_result_id": old.result_id, "human_decision_id": old.human_decision_id},
    )
    return cid, evidence


def test_d_start_reuses_source_evidence_and_sets_governed_context(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_GAAR_REASSESSMENT_WORKFLOW", "1")
    old = _result()
    result_store = ResultStore(tmp_path / "results.jsonl")
    state_log = ResultStateLog(tmp_path / "states.jsonl")
    result_store.append(old)
    state_log.append(approve_result(old, actor_id="reviewer-1", decision_id="HD-OLD", reason="approved"))
    _, evidence = _seed_source_cycle(tmp_path, old)

    change, impact, candidate = _change_and_impact(old)
    review_event = build_review_required_events(
        change, impact, results=[old], current_result_ids={old.result_id}, prev_hash=state_log.last_hash()
    )[0]
    state_log.append(review_event)

    out = start_reassessment_cycle(
        review_event=review_event,
        change=change,
        impact=impact,
        candidate_requirements=candidate,
        result_store=result_store,
        state_log=state_log,
    )
    assert out["enabled"] is True
    assert state_log.current_state(old.result_id) == ValidityState.REASSESSING
    s = events.state(out["cycle_id"])
    assert s["evidence"] == evidence
    ctx = s["governance_context"]
    assert ctx["is_reassessment"] is True
    assert ctx["supersedes_result_id"] == old.result_id
    assert ctx["parent_result_id"] == old.result_id
    assert ctx["evidence_set_id"] == old.evidence_set_id
    assert ctx["trigger_change_id"] == change.change_id
    assert "Updated material requirement" in ctx["requirement_override"]["requirement"]


def test_result_compiler_preserves_reassessment_lineage_and_evidence_identity():
    old = _result()
    state = {
        "control_id": "M3.6",
        "framework": "MAS",
        "evidence": {"text": "same evidence"},
        "proposal": {"sufficiency": "full", "model": "ollama:test"},
        "decision": {"sufficiency": "full", "reason": "Human approved reassessment."},
        "decided_by": "reviewer-2",
        "governance_context": {
            "is_reassessment": True,
            "reassessment_id": "RC-1",
            "trigger_change_id": "GC-1",
            "requirement_version_id": "REQ-TARGET-v3",
            "evidence_set_id": old.evidence_set_id,
            "parent_result_id": old.result_id,
            "supersedes_result_id": old.result_id,
            "result_version": 2,
        },
        "_events": [],
    }
    inputs = build_result_inputs(
        cycle_id="M3-6-newcycle",
        state=state,
        human_decision_id="HD-NEW",
        decision_timestamp="2026-09-18T10:00:00+00:00",
    )
    assert inputs["requirement_version_id"] == "REQ-TARGET-v3"
    assert inputs["evidence_set_id"] == old.evidence_set_id
    assert inputs["parent_result_id"] == old.result_id
    assert inputs["supersedes_result_id"] == old.result_id
    assert inputs["result_version"] == 2


def test_human_decision_boundary_supersedes_r1_and_sets_r2_current(tmp_path, monkeypatch):
    # Legacy contract fixture; mandatory investigation defaults are tested separately.
    monkeypatch.setenv("WB_INVESTIGATION_REQUIRED", "0")
    old = _result()
    result_store_path = tmp_path / "results.jsonl"
    state_path = tmp_path / "states.jsonl"
    monkeypatch.setenv("WB_GAAR_RESULT_STORE", str(result_store_path))
    monkeypatch.setenv("WB_GAAR_RESULT_STATE_STORE", str(state_path))
    store = ResultStore(result_store_path)
    states = ResultStateLog(state_path)
    store.append(old)
    states.append(approve_result(old, actor_id="reviewer-1", decision_id="HD-OLD", reason="approved"))

    change, impact, _candidate = _change_and_impact(old)
    review_event = build_review_required_events(
        change, impact, results=[old], current_result_ids={old.result_id}, prev_hash=states.last_hash()
    )[0]
    states.append(review_event)
    from governance.result_contract import begin_reassessment
    states.append(begin_reassessment(
        old, actor_id="reassessment-engine", case_id="RC-1", reason="started", prev_hash=states.last_hash()
    ))

    p = old.provenance.model_copy(update={
        "requirement_version_id": "REQ-TARGET-v3",
        "human_decision_id": "HD-NEW",
        "human_decider_id": "reviewer-2",
        "human_decision_timestamp": "2026-09-18T10:00:00+00:00",
    })
    new = create_governance_result(
        requirement_version_id="REQ-TARGET-v3",
        evidence_set_id=old.evidence_set_id,
        assessment_id=old.assessment_id,
        challenge_set_id=old.challenge_set_id,
        human_decision_id="HD-NEW",
        decision=Decision.PASS,
        rationale="Reassessment approved.",
        provenance=p,
        signer=_signer(),
        result_version=2,
        parent_result_id=old.result_id,
        supersedes_result_id=old.result_id,
    )
    out = persist_and_set_current(
        new,
        actor_id="reviewer-2",
        decision_id="HD-NEW",
        governance_context={"is_reassessment": True, "supersedes_result_id": old.result_id},
    )
    assert out["superseded_event"].to_state == ValidityState.SUPERSEDED
    assert out["state_event"].to_state == ValidityState.CURRENT
    states2 = ResultStateLog(state_path)
    assert states2.current_state(old.result_id) == ValidityState.SUPERSEDED
    assert states2.current_state(new.result_id) == ValidityState.CURRENT
