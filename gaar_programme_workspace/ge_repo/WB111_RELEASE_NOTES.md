# WB-111 — Colibrì budgets, Copilot live compatibility, and Operations UI

## Scope

WB-111 is additive on top of the WB-110 D-integrated GaaR checkpoint. It does not create a new
assessment or reassessment engine.

## Colibrì generation budget

- `llm/colibri.py` now accepts an explicit `max_tokens` generation budget.
- `inference/orchestrator.py` passes the budget chosen by the governed `InferencePlan`.
- `inference/policy.py` selects the budget from both task tier and control complexity band.
- Existing `WB_NUM_PREDICT_ROUTINE|STRONG|CRITICAL` settings remain supported.
- New optional control-band floors are:
  - `WB_CONTROL_BUDGET_ROUTINE`
  - `WB_CONTROL_BUDGET_COMPLEX`
  - `WB_CONTROL_BUDGET_CRITICAL`
- Direct Colibrì adapter use can still fall back to `COLIBRI_MAX_TOKENS`.
- Inference telemetry now records `generation_budget` and `context_budget` for each task.

The router decides reasoning depth. Colibrì remains a transport/provider and does not acquire
additional governance authority.

## Copilot live fix restored

The live Ollama compatibility normalization is present in `copilot._json_from_text()`:

- a single `requirement_context` object is normalized to a one-item list;
- list input is unchanged;
- string/number inputs remain rejected;
- prohibited reviewer judgement fields remain rejected;
- unknown fields remain rejected.

## Streamlit / UI

- Added a read-only **Operations** tab covering:
  - Governance Result counts and lifecycle states;
  - reassessment/change activity;
  - inference completion and escalation;
  - provider routing mix;
  - P50/P95 latency;
  - observed generation-token budgets;
  - durable ledger integrity;
  - recent inference tasks;
  - on-demand Ollama/Colibrì health checks.
- Metrics are projections of durable ledgers; the Operations page does not recompute governance outcomes.
- Navigation is reordered around the operating flow: Scan → Review → Outcomes → Change → Audit → Engine → Operations.
- Outcome cards now respect light/dark theme instead of forcing a dark card background.
- Product framing in the UI is updated to GaaR governance-state language.
- Added `start_ui.sh` for a fast UI start without running the entire repository test suite first.

## Validation

Focused validation after the change: 90 tests passed across policy complexity, inference routing,
Colibrì integration, Copilot, D live integration, dashboard/history regression coverage and the
new Operations projection.

A full-suite run was also started and progressed without failures before the execution time limit
of the build environment. The build environment has no outbound package network, so a browser-level
Streamlit render could not be launched there; `requirements.txt` pins Streamlit and the final render
smoke test should be run on the live Mac.
