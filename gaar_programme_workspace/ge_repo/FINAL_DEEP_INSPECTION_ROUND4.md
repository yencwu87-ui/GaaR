# Final Deep Inspection — Round 4

## Changes in this round

- Added direct coverage of `governance.control_contract.get_control_contract()` dictionary output.
- Hardened `control_complexity()` against missing, `None`, scalar, and unsupported field shapes; malformed fields now degrade to zero contribution instead of becoming synthetic element/evidence counts.
- Fixed `signals_for_control()` so canonical dict contracts carry `control_id` from `control_id`/`id` instead of losing it through object-only attribute access.
- Added a real-service `tools/live_provider_probe.py` that loads workbook `Control` objects and performs actual inference calls with unique `LIVE-PROBE-*` task IDs.
- Verified telemetry separately records structural control complexity and aggregate task complexity/tier/provider/model.

## Tests

- Complexity/provider/live-path focused suite: **40 passed**.
- Broader governance/runtime suite: **83 passed, 1 skipped**.
- Governance stress gate: **13 PASS / 0 FAIL / 1 OPEN / 0 UNKNOWN**.
- Repository compile checks passed.
- Full repository `pytest -q` was started but exceeded the available execution window; it reached 25% without a failure before timeout. This is not reported as a full-suite pass.

## Remaining OPEN

`baseline_hard_gate` remains OPEN because the repository contains `governance/SEMANTIC_BASELINE.json` but no named hard-fail baseline gate was found by the harness. The concrete exposure is that baseline drift is not automatically release-blocking through that specific gate.

## Live proof

Container-side execution cannot reach the user's Mac-local Ollama/Colibri processes. The release therefore includes a real-service probe for the user's Mac:

```bash
WB_COLIBRI_ENABLED=1 \
COLIBRI_BASE_URL=http://127.0.0.1:8000/v1 \
COLIBRI_MODEL=glm-5.2-colibri \
python tools/live_provider_probe.py --controls M1.2 M3.6
```

Expected routing:

- **M1.2**: structural band `routine` → Ollama.
- **M3.6**: workbook-derived structural band `critical` → Colibri when enabled.

Each probe writes a unique `LIVE-PROBE-*` inference ledger record containing provider, model, control complexity score/band/reasons, aggregate task tier/band/reasons, call count, escalation state, and completion state.

Synthetic inference/LLM telemetry files were removed from the release package before zipping; the application recreates them as needed.
