# WB-117 — Governed Colibri Escalation (F)

WB-117 makes deep reasoning a governed inference-policy decision. Colibri remains a provider,
never a governance actor.

## Governed-v1 triggers
When `WB_COLIBRI_ENABLED=1` and `WB_COLIBRI_GOVERNED_ESCALATION=1`, Colibri is eligible only for:
- ambiguity at/above `WB_COLIBRI_AMBIGUITY_THRESHOLD` (default 0.50)
- evidence contradiction
- reviewer/assessor disagreement
- unresolved strong challenge
- high-risk control
- material regulatory change
- prior validation failure (threshold configurable)
- structurally critical control

`regulatory_freshness` alone is not treated as materiality. A merely `complex` control alone no
longer spends the deep-reasoning budget in governed mode.

## Authority boundary
Provider escalation changes reasoning depth only. It cannot set sufficiency, maturity, challenge
strength, a human decision, quality-gate outcome, or GovernanceResult validity state.

## Observability
Inference telemetry now records `deep_reasoning`, `escalation_policy`, and `escalation_reasons`,
alongside provider/model and the router-selected generation/context budgets.

## Live probe
Use `tools/live_wb117_colibri_probe.py` to inspect routing without generating governance state.
