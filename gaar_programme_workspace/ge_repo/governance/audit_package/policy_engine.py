"""Conservative, deterministic review routing; never route unknown risk to routine."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

PolicyName = Literal['routine','elevated','critical']

@dataclass(frozen=True)
class ReviewPolicy:
    name: PolicyName
    require_blind_read: bool
    require_independent_assessment: bool
    allow_batch_approval: bool
    reviewer_role: str
    reason: str

@dataclass(frozen=True)
class ReviewContext:
    risk_tier: str = 'unknown'
    first_assessment: bool = True
    material_change: bool = False
    evidence_contradiction: bool = False
    unresolved_strong_challenge: bool = False
    quality_blocked: bool = False
    governance_exception: bool = False
    assessment_confidence: float | None = None
    admitted_evidence: bool = False
    freshness_verified: bool = False
    independent_review_required: bool = False
    policy_version: str = 'wb123.v1'


def route_policy(context: ReviewContext) -> ReviewPolicy:
    if not isinstance(context, ReviewContext):
        raise TypeError('typed ReviewContext required')
    risk = context.risk_tier.strip().lower()
    if risk not in {'low','medium','high','critical','unknown'}:
        raise ValueError('unrecognized risk tier must not default to routine')
    if context.assessment_confidence is not None and not 0 <= context.assessment_confidence <= 1:
        raise ValueError('assessment_confidence out of range')
    critical = (risk in {'high','critical'} or context.governance_exception or
                context.unresolved_strong_challenge or context.quality_blocked or
                context.evidence_contradiction or context.independent_review_required or
                context.first_assessment)
    if critical:
        return ReviewPolicy('critical',True,True,False,'governance_lead',
                            'high risk, first assessment, exception or integrity blocker')
    elevated = (risk == 'unknown' or context.material_change or
                context.assessment_confidence is None or context.assessment_confidence < .75 or
                not context.admitted_evidence or not context.freshness_verified)
    if elevated:
        return ReviewPolicy('elevated',True,False,False,'senior_reviewer',
                            'unknown risk, change, uncertainty or unverified evidence')
    return ReviewPolicy('routine',False,False,True,'governance_analyst',
                        'low/medium risk, admitted fresh evidence, no material exceptions')
