from __future__ import annotations

import re
from datetime import datetime, timezone

from ..schemas import EvidenceExaminerInput, EvidenceExaminerOutput

_STOP = {
    "the", "and", "or", "to", "of", "a", "an", "is", "are", "be", "for", "with", "that",
    "this", "in", "on", "as", "by", "from", "must", "shall", "should", "its", "their", "it",
}


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", (text or "").lower()) if w not in _STOP}


def _freshness(age_days: int | None, max_age_days: int) -> int:
    if age_days is None:
        return 100
    if age_days <= 0:
        return 100
    return max(0, min(100, round(100 * (1 - min(age_days, max_age_days) / max_age_days))))


def run(value: EvidenceExaminerInput | dict, *, threshold: float = 0.70, max_age_days: int = 365) -> EvidenceExaminerOutput:
    inp = value if isinstance(value, EvidenceExaminerInput) else EvidenceExaminerInput.model_validate(value)
    freshness = _freshness(inp.evidence_age_days, max_age_days)
    if not inp.requirement_context:
        return EvidenceExaminerOutput(
            evaluation_status="NOT_EVALUATED",
            sufficiency_score=None,
            evidence_freshness=f"{freshness}%",
            open_evidence_gaps=["NO_GOVERNED_ELEMENTS: no requirement elements were supplied for evaluation"],
            covered_elements=[],
            recommended_action="COLLECT_MORE",
            rationale=(
                "Deterministic preflight was not evaluated because zero governed requirement "
                "elements were supplied. Evidence freshness is reported separately and cannot "
                "turn an empty evaluation into a sufficiency score."
            ),
        )
    evidence_terms = _terms(inp.evidence_text)
    covered: list[str] = []
    gaps: list[str] = []
    element_scores: list[float] = []
    for element in inp.requirement_context:
        terms = _terms(element.text)
        if not terms:
            score = 1.0 if inp.evidence_text.strip() else 0.0
        else:
            hit = len(terms & evidence_terms)
            # Lexical coverage is deliberately conservative and deterministic. It is a triage signal,
            # not a governance verdict; the assessor/challenger still perform semantic reasoning.
            score = min(1.0, hit / max(1, min(5, len(terms))))
        element_scores.append(score)
        if score >= 0.40:
            covered.append(element.element_id)
        else:
            gaps.append(f"{element.element_id}: evidence does not visibly cover the governed element")

    coverage = sum(element_scores) / len(element_scores)
    score = round((coverage * 0.85) + ((freshness / 100) * 0.15), 3)
    action = "NONE" if score >= threshold and inp.evidence_text.strip() else "COLLECT_MORE"
    rationale = (
        f"Deterministic preflight: {len(covered)}/{len(inp.requirement_context)} governed elements have visible "
        f"lexical coverage; evidence freshness={freshness}%. This is a triage signal, not a sufficiency verdict."
    )
    return EvidenceExaminerOutput(
        evaluation_status="EVALUATED",
        sufficiency_score=score,
        evidence_freshness=f"{freshness}%",
        open_evidence_gaps=gaps,
        covered_elements=covered,
        recommended_action=action,
        rationale=rationale,
    )
