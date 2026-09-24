from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from governance.result_contract import (
    ActorType,
    CanonicalSigner,
    Decision,
    GovernanceResult,
    ProvenanceTrail,
    ResultStateLog,
    StateTransitionEvent,
    TransitionTrigger,
    ValidityState,
    approve_result,
    create_governance_result,
    mark_review_required,
    supersede_result,
)


def signer() -> CanonicalSigner:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return CanonicalSigner.from_base64("test-gaar-key", base64.b64encode(raw).decode())


def provenance() -> ProvenanceTrail:
    return ProvenanceTrail(
        requirement_version_id="REQ-V2",
        evidence_set_id="EVID-01",
        assessment_id="ASSESS-01",
        challenge_set_id="CHALL-01",
        human_decision_id="HD-01",
        assessor_prompt_version="assessor-test-v1",
        model_version="ollama:test-model",
        model_invocation_id="model-run-01",
        human_decider_id="reviewer-01",
        human_decision_timestamp="2026-09-18T08:00:00+00:00",
        workflow_step_timestamps={"assessor": "2026-09-18T07:59:00+00:00"},
        rule_versions={"result_contract": "v1"},
        retrieval_receipt_id="RR-01",
        retrieval_pipeline_version="wb104-v1",
    )


def result(**overrides) -> GovernanceResult:
    args = dict(
        requirement_version_id="REQ-V2",
        evidence_set_id="EVID-01",
        assessment_id="ASSESS-01",
        challenge_set_id="CHALL-01",
        human_decision_id="HD-01",
        decision=Decision.PASS,
        rationale="Evidence supports the assessed control conclusion.",
        provenance=provenance(),
        signer=signer(),
        created_at="2026-09-18T08:01:00+00:00",
    )
    args.update(overrides)
    return create_governance_result(**args)


def test_result_is_sealed_and_deterministic_identity():
    s = signer()
    p = provenance()
    a = create_governance_result(
        requirement_version_id="REQ-V2", evidence_set_id="EVID-01", assessment_id="ASSESS-01",
        challenge_set_id="CHALL-01", human_decision_id="HD-01", decision=Decision.PASS,
        rationale="Evidence supports the assessed control conclusion.", provenance=p, signer=s,
        created_at="2026-09-18T08:01:00+00:00",
    )
    b = create_governance_result(
        requirement_version_id="REQ-V2", evidence_set_id="EVID-01", assessment_id="ASSESS-01",
        challenge_set_id="CHALL-01", human_decision_id="HD-01", decision=Decision.PASS,
        rationale="Evidence supports the assessed control conclusion.", provenance=p, signer=s,
        created_at="2026-09-18T09:01:00+00:00",
    )
    assert a.result_id == b.result_id
    assert a.content_hash != b.content_hash  # creation timestamp is storage metadata, not identity
    assert a.sealed_record.signature


def test_result_is_immutable():
    r = result()
    try:
        r.rationale = "tampered"
        assert False, "frozen result should reject mutation"
    except Exception:
        pass


def test_tamper_is_detected_on_revalidation():
    r = result()
    raw = r.model_dump(mode="json")
    raw["rationale"] = "tampered"
    try:
        GovernanceResult.model_validate(raw)
        assert False, "tampering must be detected"
    except ValueError:
        pass


def test_state_transitions_do_not_mutate_result():
    r = result()
    event = approve_result(r, actor_id="reviewer-01", decision_id="HD-01", reason="Approved")
    assert event.from_state == ValidityState.FINALIZED
    assert event.to_state == ValidityState.CURRENT
    assert r.result_id == event.result_id


def test_change_signal_can_open_review_but_cannot_finalize():
    r = result()
    event = mark_review_required(
        r, actor_id="change-engine", trigger_id="CHANGE-01", reason="Material requirement change detected"
    )
    assert event.actor_type == ActorType.SYSTEM
    assert event.to_state == ValidityState.REVIEW_REQUIRED

    try:
        # System must not be able to finalize the result.
        from governance.result_contract import make_state_event
        make_state_event(
            result=r,
            to_state=ValidityState.CURRENT,
            actor_type=ActorType.SYSTEM,
            actor_id="change-engine",
            trigger=TransitionTrigger.REASSESSMENT,
            reason="system attempt",
            current_state=ValidityState.FINALIZED,
        )
        assert False, "system finalization should be blocked"
    except ValueError:
        pass


def test_supersession_is_two_immutable_events():
    old = result()
    new = result(
        evidence_set_id="EVID-02",
        assessment_id="ASSESS-02",
        challenge_set_id="CHALL-02",
        human_decision_id="HD-02",
        rationale="Updated evidence supports the reassessed conclusion.",
        parent_result_id=old.result_id,
        supersedes_result_id=old.result_id,
        provenance=ProvenanceTrail(
            requirement_version_id="REQ-V2",
            evidence_set_id="EVID-02",
            assessment_id="ASSESS-02",
            challenge_set_id="CHALL-02",
            human_decision_id="HD-02",
            assessor_prompt_version="assessor-test-v1",
            model_version="ollama:test-model",
            model_invocation_id="model-run-02",
            human_decider_id="reviewer-01",
            human_decision_timestamp="2026-09-18T09:00:00+00:00",
            workflow_step_timestamps={"assessor": "2026-09-18T08:59:00+00:00"},
            rule_versions={"result_contract": "v1"},
            retrieval_receipt_id="RR-02",
            retrieval_pipeline_version="wb104-v1",
        ),
    )
    old_event, new_event = supersede_result(
        old, new, actor_id="reviewer-01", decision_id="HD-02", timestamp="2026-09-18T09:00:00+00:00"
    )
    assert old_event.to_state == ValidityState.SUPERSEDED
    assert old_event.replacement_result_id == new.result_id
    assert new_event.to_state == ValidityState.CURRENT
    assert new.parent_result_id == old.result_id


def test_append_only_state_log_replays(tmp_path: Path):
    r = result()
    event = approve_result(r, actor_id="reviewer-01", decision_id="HD-01", reason="Approved")
    log = ResultStateLog(tmp_path / "result_state_events.jsonl")
    log.append(event)
    assert log.current_state(r.result_id) == ValidityState.CURRENT
    assert len(log.read()) == 1


def test_reassessment_state_sequence_is_explicit_and_human_bounded():
    from governance.result_contract import begin_reassessment, reconfirm_current
    r = result()
    review = mark_review_required(r, actor_id="change-engine", trigger_id="GC-1", reason="material change")
    assert review.to_state == ValidityState.REVIEW_REQUIRED
    state = ResultStateLog()
    begin = begin_reassessment(r, actor_id="reassessment-engine", case_id="RC-1", reason="start", prev_hash="0"*64)
    assert begin.to_state == ValidityState.REASSESSING
    try:
        from governance.result_contract import make_state_event, ActorType, TransitionTrigger
        make_state_event(result=r, to_state=ValidityState.CURRENT, actor_type=ActorType.SYSTEM,
                         actor_id="system", trigger=TransitionTrigger.REASSESSMENT,
                         reason="bad", current_state=ValidityState.REASSESSING)
        assert False, "system must not finalize reassessment"
    except ValueError:
        pass
