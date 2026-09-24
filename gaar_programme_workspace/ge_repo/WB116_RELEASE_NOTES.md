# WB-116 — Governance Result Quality Gate

## Status

**Build-green / live-Mac-pending.** Built directly on WB-115. The gate is opt-in with
`WB_GAAR_QUALITY_GATE=1` and is disabled by default for backward compatibility.

## What changed

- Added `governance/quality_gate.py` with an append-only, hash-chained gate ledger.
- Gate output is `FINALIZABLE` or `BLOCKED`; it does **not** create a new control verdict.
- Four dimensions are checked before a sealed, human-decided GovernanceResult may become `CURRENT`:
  - Evidence integrity — evidence bound, deterministic sufficiency threshold, configurable source floor.
  - Reasoning integrity — assessment, rationale, maturity, sufficiency and comparison are present.
  - Governance integrity — human decision present; no blocked challenge run; no unresolved strong challenge.
  - Provenance integrity — Ed25519 seal/hash/Merkle validation and required lineage links.
- A blocked result remains immutable and sealed in the result store but receives **no** `FINALIZED -> CURRENT`
  state transition. The gate result records the exact blockers.
- Added ledger/UI projection so Living Results can show `FINALIZABLE`, `BLOCKED`, or `NOT_RUN`.
- Added `tools/live_wb116_probe.py` for read-only/dry-run live gate inspection.
- Repaired a WB-113 backward-compatibility regression in `_validate_claim_rebuttal` so legacy
  `factual_pointer=` callers normalize into the new multi-anchor contract.
- Repaired `tools/live_wb115_probe.py` so it can be executed directly from the repo root.

## Validation performed

- `tests/test_wb116_quality_gate.py`: 5 passed.
- Combined WB-116/WB-115/WB-113/Copilot/D/Colibri/result/dashboard regression: 75 passed.
- `python -m compileall -q .`: passed.
- Broad `pytest -q -x` reached beyond 30% without a failure before the execution-time ceiling.
  This is **not** claimed as a complete full-suite pass.

## Live acceptance required

A real Mac run is still required for local Ollama/Colibri and Streamlit/browser behavior.
Use `WB116_LIVE_VALIDATION.md` and keep durable ledgers; use fresh request/cycle IDs.
