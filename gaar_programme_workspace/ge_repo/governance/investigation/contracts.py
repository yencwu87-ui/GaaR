"""WB140 immutable value contracts. Signatures and authorization live in store.py."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Scope(Value):
    system_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    period: str = Field(min_length=1)


class InvestigationContext(Value):
    investigation_id: str = Field(min_length=1)
    control_id: str = Field(min_length=1)
    framework: str = Field(min_length=1)
    requirement_version: str = Field(min_length=1)
    scope: Scope
    boundary: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    criticality: Literal["low", "medium", "high"]
    synthetic: bool = False


class Expectation(Value):
    element_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_version: str = Field(min_length=1)
    authority: Literal["binding", "guidance", "consultation", "internal", "unverified"]
    purpose: Literal["design", "operating", "outcome"]
    applies: bool
    applicability_reason: str = Field(min_length=1)
    uncertainty: str = ""


class ApplicableExpectations(Value):
    requirement_version: str = Field(min_length=1)
    elements: tuple[Expectation, ...] = Field(min_length=1)


class EvidenceRecord(Value):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=False)
    evidence_id: str = Field(min_length=1)
    scope: Scope
    authority: Literal["binding", "guidance", "consultation", "internal", "external", "unverified"]
    purposes: tuple[Literal["design_statement", "operating_record", "test_result", "agreement", "gap"], ...] = Field(min_length=1)
    element_ids: tuple[str, ...] = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance: tuple[str, ...] = Field(min_length=1)
    integrity_status: Literal["verified", "partial", "contested"]
    finding_status: Literal["neutral", "supports", "contradicts", "gap_identified"]


class Examination(Value):
    element_id: str
    status: Literal["SUPPORTED", "CONTRADICTED", "NOT_EVIDENCED", "NOT_EVALUATED", "NOT_APPLICABLE"]
    evidence_refs: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)


class EvidenceExamination(Value):
    evidence: tuple[EvidenceRecord, ...] = ()
    findings: tuple[Examination, ...]


class Dependency(Value):
    dependency_id: str
    upstream: str
    downstream: str
    relation: str = Field(min_length=1)
    basis_refs: tuple[str, ...] = Field(min_length=1)
    status: Literal["hypothesis", "supported"]


class Explanation(Value):
    hypothesis_id: str
    claim: str = Field(min_length=1)
    basis_refs: tuple[str, ...] = Field(min_length=1)
    alternatives: tuple[str, ...] = Field(min_length=1)
    compensating_controls_review: str = Field(min_length=1)
    dependencies: tuple[str, ...] = ()
    material: bool


class RetrievalLane(Value):
    name: Literal["expectations", "facts", "dependencies", "counterevidence", "procedures", "precedents"]
    status: Literal["COMPLETED", "UNAVAILABLE", "NOT_EVALUATED", "PARTIAL"]
    refs: tuple[str, ...] = ()
    required: bool = True
    error: str = ""


class ExplanationSet(Value):
    status: Literal["COMPLETED", "UNAVAILABLE", "NOT_EVALUATED", "PARTIAL"]
    hypotheses: tuple[Explanation, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    retrieval: tuple[RetrievalLane, ...]
    limitations: tuple[str, ...] = ()


class TestProposal(Value):
    test_id: str
    hypothesis_id: str
    tool: str
    version: str
    input_ref: str
    decision_impact: str = Field(min_length=1)
    priority: int = Field(ge=1)
    required: bool = True


class TestPlan(Value):
    tests: tuple[TestProposal, ...] = ()
    policy_id: str = Field(min_length=1)
    no_test_rationale: str = ""


class TestExecutionRecord(Value):
    test_id: str
    status: Literal["EXECUTED", "UNAVAILABLE", "NOT_EVALUATED"]
    tool: str
    version: str
    input_sha256: str
    result_json: str
    result_sha256: str
    implementation_sha256: str
    limitation: str = Field(min_length=1)


class Verification(Value):
    tests: tuple[TestExecutionRecord, ...] = ()


class ChallengeFinding(Value):
    finding_id: str
    material: bool
    claim: str = Field(min_length=1)
    basis_refs: tuple[str, ...] = Field(min_length=1)


class ChallengeRecord(Value):
    status: Literal["COMPLETED", "UNAVAILABLE", "NOT_EVALUATED", "PARTIAL"]
    input_head: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewed_refs: tuple[str, ...]
    disproof_attempts: tuple[str, ...] = Field(min_length=1)
    missing_explanations: tuple[str, ...] = ()
    findings: tuple[ChallengeFinding, ...] = ()


class Disposition(Value):
    risk_ref: str
    action: Literal["accept", "remediate", "refute", "block_deployment"]
    rationale: str = Field(min_length=1)
    basis_refs: tuple[str, ...] = Field(min_length=1)


class EscalationDecision(Value):
    risk_ref: str
    route: Literal["policy_auto", "human", "colibri"]
    rationale: str = Field(min_length=1)
    status: Literal["PENDING", "COMPLETED", "UNAVAILABLE"]
    disposition_ref: str = ""


class InvestigationConclusion(Value):
    verdict: Literal["PASS", "ADVERSE", "INCONCLUSIVE"]
    rationale: str = Field(min_length=1)
    dispositions: tuple[Disposition, ...] = ()
    escalation_decisions: tuple[EscalationDecision, ...] = ()
    uncertainty: tuple[str, ...] = ()
    deployment_requested: bool = False


STAGES = ("understand", "expectations", "examine", "explain", "plan", "verify", "challenge", "conclude")
MODELS = dict(zip(STAGES, (InvestigationContext, ApplicableExpectations, EvidenceExamination,
                          ExplanationSet, TestPlan, Verification, ChallengeRecord, InvestigationConclusion)))
ROLES = dict(zip(STAGES, ("owner", "governance", "assessor", "assessor", "test_planner", "executor", "challenger", "decision")))
