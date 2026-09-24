# WB107 Build Validation

Baseline: `ge_reviewer_copilot_v1_A_result_contract_integrated.zip`

## Implemented

- `governance/change_intelligence.py`
- `tests/test_governance_change_intelligence_wb107.py`
- `docs/WB107_GOVERNANCE_CHANGE_INTELLIGENCE.md`

## Focused validation

- WB107 Governance Change Intelligence: **21 passed**
- Existing Result Contract: included in focused validation
- Existing Result Pipeline Integration: included in focused validation
- Existing temporal regulatory-change tests: included in focused validation
- Existing triangulation tests: included in focused validation

Combined focused run: **21 passed**.

## Broader validation

`python -m compileall -q governance core tests` completed successfully.

The broader `pytest -q tests` run was started with a 180-second execution window and timed out at approximately 18% without reporting a test failure before the timeout. This is an execution-duration limitation, not evidence of a green full-suite result.

## Design guardrails

- Authority is metadata-first; prose/semantic similarity does not establish legal force.
- Consultation, industry, voluntary and background sources do not automatically affect governance state.
- Binding effective applicable sources may create governance-impact candidates; supervisory sources may trigger review but do not become binding requirements here.
- GovernanceChange never produces PASS/FAIL decisions.
- ImpactAssessment outputs only `NO_MATERIAL_IMPACT` or `REVIEW_REQUIRED`.
- `CURRENT -> REVIEW_REQUIRED` uses a SYSTEM event with `trigger_id=GovernanceChange.change_id` and no human `decision_id`.
- Historical/non-current results are not reopened when current result IDs are supplied to the event builder.
