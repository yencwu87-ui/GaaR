# WB-115 — AI Auditor Runtime, Agile Review and Living Results

## Status

**Build-green / live-Mac-pending.** This package is built on the executable WB-113 checkpoint. It
keeps the WB-113 disagreement grounding modes and Challenge Copilot, the Copilot dict→list transport
fix, Colibrì routed generation budgets and D reassessment integration.

## New runtime

- `governance/ai_auditor/` — typed skill contracts, policy loader, bounded skill registry,
  Review Conductor and read-only Living Governance projection.
- `config/ai_auditor_policy.yaml` — policy-defined human checkpoints and evidence preflight threshold.
- `tools/live_wb115_probe.py` — safe live probe. `--run` cannot call the final decision boundary.
- `WB115_LIVE_VALIDATION.md` — Mac acceptance protocol.

## New / upgraded skills

- Evidence Examiner — deterministic triage, typed input/output, [0,1] score validation.
- Challenge Auditor — projects admitted/blocked/strong challenge posture into a next action.
- Control Narrative Copilot — audit-ready narrative, verbatim evidence anchors and explicit limitations;
  prohibited from emitting sufficiency, maturity, compliance or a final decision.
- Provenance Auditor — verifies sealed result/store/state projection without mutation.
- Quality Auditor — preflight only in WB-115. Full blocking quality gate is WB-116.

## UI / operating model

- Puppet-inspired operations-console visual treatment.
- **AI Auditor** tab — stand-up metrics, Conductor control, grounded narrative and governed activity stream.
- **Living Results** tab — current state projected from immutable GovernanceResult + state events.
- Review queue no longer has a global first-50 truncation. Framework-aware sections ensure SAFR stays visible
  when MAS + MGF Agentic + SAFR are all selected.
- Review modes: **Focus**, **Kanban**, **Stand-up**.
- Kanban stages: BACKLOG → AUTOMATION → HUMAN READ → VERIFY → EXCEPTION → DECISION → DONE.
- Outcomes page now includes ledger-backed decision counts for every framework, including SAFR.
- Sidebar modes: Manual, Assisted, Supervised Autopilot.
- Review workspace includes Review Conductor panel and processing/activity stream.

## Authority boundary

The Conductor never calls `core.cycle.decide()`. It stops at human read, human exception and final
human decision checkpoints. Skills are registered as `may_mutate_state=False`; stateful review steps
are invoked only through the Conductor and existing governed cycle API.

## Validation performed in build environment

- `tests/test_wb115_ai_auditor.py`: 9 passed.
- WB-113 + Reviewer Copilot + correlation + D reassessment + Colibrì + result contract/dashboard bundle: 87 passed.
- App/assessor/challenge runtime bundle: 21 passed.
- Challenger hardening/Copilot probe/MAS change bundle: 47 passed.
- SAFR authoring: 11 passed.
- SAFR S1.2/S2.1 authoring: 10 passed.
- WB-112 MGF alias/explainability + WB-115: 13 passed.
- `python -m compileall -q .`: passed.

These suites overlap; counts are intentionally not summed into a misleading single total. Streamlit
is not installed in this build container, so browser rendering remains part of live Mac acceptance.

## Live acceptance still required

Use `WB115_LIVE_VALIDATION.md`. WB-115 is green only when the Mac proves SAFR visibility, immediate
ledger-backed dashboard update, Conductor stop nodes, WB-113 MAS/SAFR challenge behavior, bounded
Control Narrative, intact result provenance and read-only Living Results.
