from __future__ import annotations

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class TaskSignals:
    role: str
    control_id: str = ""
    evidence_chars: int = 0
    element_count: int = 0
    ambiguity: float = 0.0
    prior_failures: int = 0
    reviewer_disagreement: bool = False
    high_risk: bool = False
    regulatory_freshness: bool = False
    evidence_contradiction: bool = False
    material_change: bool = False
    unresolved_strong_challenge: bool = False
    broader_risk_corroborated: bool = False
    control_complexity_score: int = 0
    control_complexity_reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class InferencePlan:
    tier: str
    provider: str
    model: str
    max_attempts: int = 1
    num_ctx: int = 16384
    num_predict: int = 1200
    parallel_read_only: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)
    # Aggregate task complexity after adding runtime difficulty signals.
    complexity_score: int = 0
    complexity_band: str = "routine"
    complexity_reasons: tuple[str, ...] = field(default_factory=tuple)
    # Structural complexity of the governed control itself, kept distinct from runtime task tier.
    control_complexity_score: int = 0
    control_complexity_band: str = "routine"
    control_complexity_reasons: tuple[str, ...] = field(default_factory=tuple)
    deep_reasoning: bool = False
    escalation_policy: str = "legacy"
    escalation_reasons: tuple[str, ...] = field(default_factory=tuple)


def _role_env(role: str) -> str | None:
    direct = os.environ.get(f"WB_MODEL_{role.upper()}")
    if direct:
        return direct
    if role.startswith("challenge_") or role == "challenge":
        return os.environ.get("WB_MODEL_CHALLENGE")
    return None


def _provider_role_env(role: str) -> str | None:
    direct = os.environ.get(f"WB_PROVIDER_{role.upper()}")
    if direct:
        return direct.lower().strip()
    if role.startswith("challenge_") or role == "challenge":
        direct = os.environ.get("WB_CHALLENGE_PROVIDER")
        if direct:
            return direct.lower().strip()
    return None


def _normalise_elements(value) -> list:
    """Return only supported element collections; never treat a scalar/string as N elements."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def _normalise_requirement(value) -> str:
    """Only textual requirement fields contribute to structural complexity."""
    return value if isinstance(value, str) else ""


def _normalise_artefacts(value) -> list[str]:
    """Normalise supported evidence/artefact representations without inflating malformed values."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.replace("\n", ";").split(";") if x.strip()]
    return []


def control_complexity(control) -> dict:
    """Deterministically classify the structural complexity of one governed control.

    This is deliberately not an LLM judgement. It uses control-contract structure only so the
    engine can explain why a control/task is routed to a deeper inference tier. Runtime signals
    are added by ``build_plan`` on top of this control-level baseline.
    Both canonical control-contract dicts and workbook Control objects are supported.
    Unsupported/malformed field shapes degrade to zero contribution rather than raising or
    accidentally converting a scalar into many synthetic elements.
    """
    if isinstance(control, dict):
        elements = _normalise_elements(control.get("elements"))
        requirement = _normalise_requirement(control.get("req") or control.get("requirement"))
        raw_artefacts = control.get("artefacts")
        if raw_artefacts is None:
            raw_artefacts = control.get("expected_evidence")
        artefacts = _normalise_artefacts(raw_artefacts)
    else:
        elements = _normalise_elements(getattr(control, "elements", None))
        requirement = _normalise_requirement(
            getattr(control, "req", None) or getattr(control, "requirement", None)
        )
        artefacts = _normalise_artefacts(getattr(control, "artefacts", None))
    score = 0
    reasons: list[str] = []

    if len(elements) >= 12:
        score += 2
        reasons.append("many_control_elements")
    elif len(elements) >= 8:
        score += 1
        reasons.append("multiple_control_elements")

    if len(artefacts) >= 5:
        score += 1
        reasons.append("many_expected_artefacts")

    if len(requirement) >= 900:
        score += 1
        reasons.append("long_governed_requirement")

    band = "critical" if score >= 3 else ("complex" if score >= 1 else "routine")
    return {
        "score": score,
        "band": band,
        "reasons": tuple(reasons),
        "element_count": len(elements),
        "expected_artefact_count": len(artefacts),
        "requirement_chars": len(requirement),
    }


def signals_for_control(control, *, role: str, evidence_chars: int = 0, ambiguity: float = 0.0,
                        prior_failures: int = 0, reviewer_disagreement: bool = False,
                        high_risk: bool = False, regulatory_freshness: bool = False,
                        evidence_contradiction: bool = False, material_change: bool = False,
                        unresolved_strong_challenge: bool = False) -> TaskSignals:
    profile = control_complexity(control)
    if isinstance(control, dict):
        control_id = control.get("control_id") or control.get("id") or ""
    else:
        control_id = getattr(control, "id", "") or ""
    return TaskSignals(
        role=role,
        control_id=str(control_id),
        evidence_chars=evidence_chars,
        element_count=profile["element_count"],
        ambiguity=ambiguity,
        prior_failures=prior_failures,
        reviewer_disagreement=reviewer_disagreement,
        high_risk=high_risk,
        regulatory_freshness=regulatory_freshness,
        evidence_contradiction=evidence_contradiction,
        material_change=material_change,
        unresolved_strong_challenge=unresolved_strong_challenge,
        control_complexity_score=profile["score"],
        control_complexity_reasons=profile["reasons"],
    )


def _complexity_band(score: int) -> str:
    return "critical" if score >= 3 else ("complex" if score >= 1 else "routine")


def governed_colibri_decision(tier: str, signals: TaskSignals) -> dict:
    """Return the policy decision for deep reasoning without changing governance authority.

    WB-117/F keeps provider escalation explicit and explainable.  In governed mode a merely
    `complex` control does not automatically justify Colibri; one of the configured material
    reasoning signals must be present, or the control itself must be structurally critical.
    """
    enabled = os.environ.get("WB_COLIBRI_ENABLED", "0") == "1"
    reasons: list[str] = []
    threshold = float(os.environ.get("WB_COLIBRI_AMBIGUITY_THRESHOLD", "0.50"))
    failure_threshold = max(1, int(os.environ.get("WB_COLIBRI_FAILURE_THRESHOLD", "1")))
    control_band = _complexity_band(int(signals.control_complexity_score))

    if signals.ambiguity >= threshold:
        reasons.append("ambiguity")
    if signals.evidence_contradiction:
        reasons.append("evidence_contradiction")
    if signals.reviewer_disagreement:
        reasons.append("reviewer_assessor_disagreement")
    if signals.unresolved_strong_challenge:
        reasons.append("unresolved_strong_challenge")
    if signals.broader_risk_corroborated:
        reasons.append("broader_risk_corroborated")
    if signals.high_risk:
        reasons.append("high_risk_control")
    if signals.material_change:
        reasons.append("material_regulatory_change")
    if signals.prior_failures >= failure_threshold:
        reasons.append("prior_validation_failure")
    if control_band == "critical":
        reasons.append("critical_control_complexity")

    # Provider selection is transport/reasoning-depth policy only; it never changes a governance verdict.
    # regulatory_freshness alone is deliberately not materiality.  It increases task tier but
    # cannot by itself spend the deep-reasoning budget.
    allowed = bool(enabled and reasons)
    return {
        "enabled": enabled,
        "escalate": allowed,
        "policy": "governed-v1",
        "reasons": tuple(dict.fromkeys(reasons)),
    }


def _provider_for(tier: str, signals: TaskSignals) -> str:
    explicit = _provider_role_env(signals.role)
    if explicit:
        return explicit

    governed_mode = os.environ.get("WB_COLIBRI_GOVERNED_ESCALATION", "0") == "1"
    if governed_mode:
        decision = governed_colibri_decision(tier, signals)
        if decision["escalate"]:
            return "colibri"
    else:
        # Backward-compatible WB-111 routing. F/WB-117 replaces this when governed mode is on.
        colibri_enabled = os.environ.get("WB_COLIBRI_ENABLED", "0") == "1"
        control_band = _complexity_band(int(signals.control_complexity_score))
        difficult = (control_band in {"complex", "critical"}
                    or signals.reviewer_disagreement
                    or signals.high_risk or tier == "critical")
        if colibri_enabled and difficult:
            return "colibri"

    if signals.role.startswith("challenge"):
        return "ollama"
    return (os.environ.get("WB_DEFAULT_PROVIDER") or "ollama").lower().strip()


def _model_for_tier(tier: str, role: str, provider: str = "ollama") -> str:
    if provider == "colibri":
        return os.environ.get("COLIBRI_MODEL") or "glm-5.2-colibri"

    if role.startswith("challenge") and os.environ.get("WB_INFERENCE_FALLBACK") == "1":
        alt = (os.environ.get("WB_MODEL_CHALLENGE_FALLBACK")
               or os.environ.get("WB_MODEL_FAST"))
        primary = _primary_model(tier, role)
        if alt and alt != primary:
            return alt
        return primary
    return _primary_model(tier, role)

def fallback_state(tier: str, role: str) -> dict[str, str]:
    """What an operator needs in the log to tell a fallback from a retry.

    `fallback_model == primary_model` is a retry however the flag is set, and a diagnostic that
    reports it as a fallback sends someone looking for a broken alternative model that was never
    configured.
    """
    primary = _primary_model(tier, role)
    enabled = os.environ.get("WB_INFERENCE_FALLBACK") == "1"
    alt = (os.environ.get("WB_MODEL_CHALLENGE_FALLBACK")
           or os.environ.get("WB_MODEL_FAST")) if role.startswith("challenge") else None
    if not enabled:
        return {"primary_model": primary, "mode": "no_fallback_configured",
                "on_failure": "blocked", "fallback_model": ""}
    if alt and alt != primary:
        return {"primary_model": primary, "mode": "fallback", "on_failure": "retry_other_model",
                "fallback_model": alt}
    return {"primary_model": primary, "mode": "retry", "on_failure": "retry_same_model",
            "fallback_model": primary,
            "note": ("no distinct fallback model is configured; set "
                     "WB_MODEL_CHALLENGE_FALLBACK to a model you have pulled")}


def _primary_model(tier: str, role: str) -> str:
    role_model = _role_env(role)
    if tier == "critical":
        return os.environ.get("WB_MODEL_CRITICAL") or os.environ.get("WB_MODEL_STRONG") or role_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"
    if tier == "strong":
        return os.environ.get("WB_MODEL_STRONG") or role_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"
    return os.environ.get("WB_MODEL_FAST") or role_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"



def _generation_budget(tier: str, control_band: str) -> int:
    """Select a deterministic generation budget from task tier and control complexity band.

    Task-tier settings remain backwards compatible with WB_NUM_PREDICT_*. Control-band settings
    act as floors, so a structurally complex control cannot accidentally receive a routine-sized
    budget even when another runtime signal path is changed later.
    """
    tier_defaults = {"routine": 1200, "strong": 1800, "critical": 2400}
    band_defaults = {"routine": 1200, "complex": 1800, "critical": 2400}
    task_budget = int(os.environ.get(f"WB_NUM_PREDICT_{tier.upper()}", tier_defaults[tier]))
    control_budget = int(os.environ.get(
        f"WB_CONTROL_BUDGET_{control_band.upper()}", band_defaults[control_band]
    ))
    if task_budget < 1 or control_budget < 1:
        raise ValueError("inference generation budgets must be >= 1")
    return max(task_budget, control_budget)

def build_plan(signals: TaskSignals) -> InferencePlan:
    reasons: list[str] = list(signals.control_complexity_reasons)
    score = int(signals.control_complexity_score)
    if signals.evidence_chars > 24000:
        score += 1; reasons.append("large_evidence")
    if signals.element_count > 8:
        score += 1; reasons.append("many_elements")
    if signals.ambiguity >= 0.5:
        score += 1; reasons.append("ambiguous_task")
    if signals.prior_failures:
        score += min(2, signals.prior_failures); reasons.append("prior_validation_failure")
    if signals.reviewer_disagreement:
        score += 2; reasons.append("reviewer_assessor_disagreement")
    if signals.high_risk:
        score += 2; reasons.append("high_risk_control")
    if signals.regulatory_freshness:
        score += 1; reasons.append("regulatory_freshness")

    if score >= 3:
        tier = "critical"
    elif score >= 1:
        tier = "strong"
    else:
        tier = "routine"

    env_ctx = {"routine": "16384", "strong": "24576", "critical": "32768"}[tier]
    provider = _provider_for(tier, signals)
    governed_mode = os.environ.get("WB_COLIBRI_GOVERNED_ESCALATION", "0") == "1"
    escalation = governed_colibri_decision(tier, signals) if governed_mode else {
        "policy": "legacy", "reasons": tuple(), "escalate": provider == "colibri"
    }
    # An explicit fallback provider is useful when the primary challenger transport fails.
    # `run_with_escalation()` enables fallback mode only for the second plan.
    if (signals.role.startswith("challenge") and
            os.environ.get("WB_INFERENCE_FALLBACK") == "1"):
        fallback_provider = os.environ.get("WB_CHALLENGE_FALLBACK_PROVIDER", "").strip().lower()
        if fallback_provider and fallback_provider != provider:
            provider = fallback_provider

    complexity_band = _complexity_band(score)
    control_band = _complexity_band(int(signals.control_complexity_score))
    return InferencePlan(
        tier=tier,
        provider=provider,
        model=_model_for_tier(tier, signals.role, provider),
        max_attempts=2 if signals.role.startswith("challenge") else (1 if tier == "routine" else 2),
        num_ctx=int(os.environ.get(f"WB_NUM_CTX_{tier.upper()}", env_ctx)),
        num_predict=_generation_budget(tier, control_band),
        parallel_read_only=signals.role in {"assess", "challenge", "elements"},
        reasons=tuple(reasons),
        complexity_score=score,
        complexity_band=complexity_band,
        complexity_reasons=tuple(reasons),
        control_complexity_score=int(signals.control_complexity_score),
        control_complexity_band=control_band,
        control_complexity_reasons=tuple(signals.control_complexity_reasons or ()),
        deep_reasoning=(provider == "colibri"),
        escalation_policy=str(escalation.get("policy") or "legacy"),
        escalation_reasons=tuple(escalation.get("reasons") or ()),
    )
