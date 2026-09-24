from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequirementElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    element_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    note: str = ""


class EvidenceExaminerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_id: str = Field(min_length=1)
    framework: str = ""
    requirement_version_id: str = Field(min_length=1)
    evidence_set_id: str = Field(min_length=1)
    requirement_context: list[RequirementElement]
    evidence_text: str = ""
    evidence_age_days: int | None = Field(default=None, ge=0)


class EvidenceExaminerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluation_status: Literal["EVALUATED", "NOT_EVALUATED"] = "EVALUATED"
    sufficiency_score: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_freshness: str = Field(pattern=r"^(100|[0-9]{1,2})%$")
    open_evidence_gaps: list[str] = Field(default_factory=list)
    covered_elements: list[str] = Field(default_factory=list)
    recommended_action: Literal["NONE", "COLLECT_MORE"]
    rationale: str = Field(min_length=1)


class ChallengeAuditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_id: str = Field(min_length=1)
    challenge_envelope: dict


class ChallengeAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admitted_count: int = Field(ge=0)
    strong_unresolved_count: int = Field(ge=0)
    blocked: bool
    recommended_action: Literal["NONE", "ESCALATE_TO_COPILOT", "REQUIRE_HUMAN"]
    reasons: list[str] = Field(default_factory=list)


class ControlNarrativeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control_id: str = Field(min_length=1)
    framework: str = ""
    requirement: str = Field(min_length=1)
    evidence_text: str = ""
    requirement_context: list[RequirementElement] = Field(default_factory=list)


class EvidenceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locator: str = ""
    quote: str = Field(min_length=1)
    purpose: str = ""


class ControlNarrativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narrative: str = Field(min_length=1)
    evidence_anchors: list[EvidenceAnchor] = Field(default_factory=list)
    demonstrates: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ProvenanceAuditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: str = Field(min_length=1)


class ProvenanceAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    checks: dict[str, bool]
    failures: list[str] = Field(default_factory=list)


class QualityAuditInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle_id: str = Field(min_length=1)
    require_human_decision: bool = True


class QualityAuditOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: bool
    dimensions: dict[str, bool]
    blockers: list[str] = Field(default_factory=list)


class ConductorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle_id: str
    control_id: str
    framework: str = ""
    stage: str
    next_action: str
    checkpoint: Literal[
        "NONE", "HUMAN_READ", "HUMAN_EXCEPTION", "HUMAN_DECISION", "EVIDENCE_REQUIRED", "CHALLENGE_REQUIRED", "INVESTIGATION_REQUIRED", "COMPLETE"
    ]
    reasons: list[str] = Field(default_factory=list)
    invoked_skills: list[str] = Field(default_factory=list)
    narrative: ControlNarrativeOutput | None = None
    evidence_examiner: EvidenceExaminerOutput | None = None
    challenge_audit: ChallengeAuditOutput | None = None
    quality_audit: QualityAuditOutput | None = None


class HumanExceptionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_sufficiency_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    freshness_max_age_days: int = Field(default=365, ge=1)
    require_human_on_strong_challenge: bool = True
    require_human_on_blocked_challenge: bool = True
    require_human_on_critical_control: bool = True
    final_decision_requires_human: bool = True
