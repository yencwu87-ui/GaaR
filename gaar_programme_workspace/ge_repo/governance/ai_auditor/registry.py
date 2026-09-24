from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from .skills import evidence_examiner, challenge_auditor, control_narrative, provenance_auditor, quality_auditor
from governance.investigation.bridge import agent_context


@dataclass(frozen=True)
class SkillSpec:
    name: str
    runner: Callable[..., Any]
    may_mutate_state: bool = False
    description: str = ""


_REGISTRY = {
    "investigation_context": SkillSpec("investigation_context", agent_context, False, "Verified shared investigation and dependencies"),
    "evidence_examiner": SkillSpec("evidence_examiner", evidence_examiner.run, False, "Deterministic evidence preflight"),
    "challenge_auditor": SkillSpec("challenge_auditor", challenge_auditor.run, False, "Validate challenge posture"),
    "control_narrative": SkillSpec("control_narrative", control_narrative.run, False, "Grounded control-intent narrative"),
    "provenance_auditor": SkillSpec("provenance_auditor", provenance_auditor.run, False, "Verify sealed result provenance"),
    "quality_auditor": SkillSpec("quality_auditor", quality_auditor.run, False, "Pre-finalization completeness preflight"),
}


def get(name: str) -> SkillSpec:
    if name not in _REGISTRY:
        raise KeyError(f"unknown AI Auditor skill: {name}")
    return _REGISTRY[name]


def list_skills() -> list[SkillSpec]:
    return list(_REGISTRY.values())
