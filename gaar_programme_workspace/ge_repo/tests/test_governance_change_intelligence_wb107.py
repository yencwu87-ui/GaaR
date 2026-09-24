from __future__ import annotations

from pathlib import Path
import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from governance.change_intelligence import (
    AuthorityClass,
    AuthorityEvidence,
    ChangeStatus,
    ImpactDecision,
    assess_impact,
    assess_source_authority,
    build_review_required_events,
    detect_governance_change,
)
from governance.result_contract import CanonicalSigner, Decision, ProvenanceTrail, ValidityState, create_governance_result
from governance.triangulation import SourceRegistry

ROOT = Path(__file__).resolve().parents[1]


def _signer() -> CanonicalSigner:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return CanonicalSigner.from_base64("test-c", base64.b64encode(raw).decode())


def _result(req_id: str = "REQ-M3.6-v1"):
    p = ProvenanceTrail(
        requirement_version_id=req_id,
        evidence_set_id="EVID-1",
        assessment_id="ASSESS-1",
        challenge_set_id="CHALL-1",
        human_decision_id="HD-1",
        assessor_prompt_version="assessor-v1",
        model_version="ollama:test",
        model_invocation_id="run-1",
        human_decider_id="reviewer-1",
        human_decision_timestamp="2026-09-18T08:00:00+00:00",
        retrieval_receipt_id="RR-1",
        retrieval_pipeline_version="wb104-v1",
    )
    return create_governance_result(
        requirement_version_id=req_id,
        evidence_set_id="EVID-1",
        assessment_id="ASSESS-1",
        challenge_set_id="CHALL-1",
        human_decision_id="HD-1",
        decision=Decision.PASS,
        rationale="Evidence supports the current governance conclusion.",
        provenance=p,
        signer=_signer(),
        created_at="2026-09-18T08:01:00+00:00",
    )


def test_proposed_consultation_is_not_governance_state_eligible():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = reg.sources["MAS-TRM-P012-2026"]
    auth = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS",
            jurisdiction="Singapore",
            legal_basis="consultation process",
            enforcement_status="none while proposed",
            applicability="financial institutions",
            applicable=True,
        ),
        as_of="2026-09-18",
    )
    assert auth.authority_class == AuthorityClass.CONSULTATION
    assert auth.governance_impact_eligible is False
    assert auth.canonical_requiredness_eligible is False


def test_binding_effective_source_requires_explicit_metadata_but_can_trigger_review():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = reg.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    auth = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS",
            jurisdiction="Singapore",
            legal_basis="applicable MAS Notice under governing statute",
            enforcement_status="binding notice requirements",
            applicability="governed scope",
            applicable=True,
        ),
        as_of="2026-09-18",
    )
    assert auth.authority_class == AuthorityClass.BINDING
    assert auth.governance_impact_eligible is True
    assert auth.canonical_requiredness_eligible is True


def test_change_detection_is_deterministic_and_does_not_mutate_requirements():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = reg.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    auth = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS", jurisdiction="Singapore", legal_basis="statute", enforcement_status="binding",
            applicability="governed scope", applicable=True,
        ),
        as_of="2026-09-18",
    )
    current = {"version": "1", "controls": {"M3.6": {"requirement": "AES-128"}}}
    candidate = {"version": "2", "controls": {"M3.6": {"requirement": "AES-256"}}}
    a = detect_governance_change(current, candidate, source=source, authority=auth,
                                 detected_on="2026-09-18", applicability="governed scope")
    b = detect_governance_change(current, candidate, source=source, authority=auth,
                                 detected_on="2026-09-18", applicability="governed scope")
    assert a.change_id == b.change_id
    assert a.status == ChangeStatus.CHANGE_CANDIDATE
    assert a.changed_control_ids == ("M3.6",)
    assert current["controls"]["M3.6"]["requirement"] == "AES-128"


def test_impact_maps_existing_result_and_requires_review():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = reg.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    auth = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS", jurisdiction="Singapore", legal_basis="statute", enforcement_status="binding",
            applicability="governed scope", applicable=True,
        ),
        as_of="2026-09-18",
    )
    change = detect_governance_change(
        {"version": "1", "controls": {"M3.6": {"requirement": "AES-128"}}},
        {"version": "2", "controls": {"M3.6": {"requirement": "AES-256"}}},
        source=source, authority=auth, detected_on="2026-09-18", applicability="governed scope"
    )
    result = _result("REQ-M3.6-v1")
    impact = assess_impact(
        change,
        results=[result],
        current_requirement_version_ids={"M3.6": "REQ-M3.6-v1"},
        control_materiality={"M3.6": "HIGH"},
    )
    assert impact.decision == ImpactDecision.REVIEW_REQUIRED
    assert impact.affected_result_ids == (result.result_id,)
    assert impact.materiality_by_control["M3.6"] == "HIGH"


def test_system_review_event_has_trigger_not_human_decision():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = reg.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    auth = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS", jurisdiction="Singapore", legal_basis="statute", enforcement_status="binding",
            applicability="governed scope", applicable=True,
        ),
        as_of="2026-09-18",
    )
    change = detect_governance_change(
        {"version": "1", "controls": {"M3.6": {"requirement": "AES-128"}}},
        {"version": "2", "controls": {"M3.6": {"requirement": "AES-256"}}},
        source=source, authority=auth, detected_on="2026-09-18", applicability="governed scope"
    )
    result = _result("REQ-M3.6-v1")
    impact = assess_impact(change, results=[result], current_requirement_version_ids={"M3.6": "REQ-M3.6-v1"})
    events = build_review_required_events(change, impact, results=[result], current_result_ids={result.result_id})
    assert len(events) == 1
    assert events[0].to_state == ValidityState.REVIEW_REQUIRED
    assert events[0].decision_id is None
    assert events[0].trigger_id == change.change_id


def test_historical_result_is_not_reopened_when_not_current():
    reg = SourceRegistry.from_yaml(ROOT / "requirements/triangulation/sources.yaml")
    source = reg.sources["MAS-TRM-NOTICES-BASELINE-2024"]
    auth = assess_source_authority(
        source,
        metadata=AuthorityEvidence(
            issuer="MAS", jurisdiction="Singapore", legal_basis="statute", enforcement_status="binding",
            applicability="governed scope", applicable=True,
        ),
        as_of="2026-09-18",
    )
    change = detect_governance_change(
        {"version": "1", "controls": {"M3.6": {"requirement": "AES-128"}}},
        {"version": "2", "controls": {"M3.6": {"requirement": "AES-256"}}},
        source=source, authority=auth, detected_on="2026-09-18", applicability="governed scope"
    )
    result = _result("REQ-M3.6-v1")
    impact = assess_impact(change, results=[result], current_requirement_version_ids={"M3.6": "REQ-M3.6-v1"})
    events = build_review_required_events(change, impact, results=[result], current_result_ids=set())
    assert events == ()
