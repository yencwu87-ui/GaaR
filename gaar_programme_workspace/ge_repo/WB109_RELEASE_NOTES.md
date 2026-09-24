# WB109 Release Notes — Governed Reassessment Workflow

## Baseline

Built cumulatively on `ge_reviewer_copilot_v1_C_governance_change_intelligence.zip`.

## Added

- Explicit `REASSESSING` validity state.
- Deterministic state transition rules for `REVIEW_REQUIRED -> REASSESSING` (SYSTEM) and `REASSESSING -> CURRENT/SUPERSEDED` (HUMAN).
- `governance/change_runtime.py` to connect GovernanceChange + ImpactAssessment to the immutable ResultStore/StateLog.
- `governance/reassessment.py` for append-only reassessment cases and governed completion.
- WB109 regression tests covering same-result reconfirmation and replacement-result supersession.
- `WB109_REASSESSMENT_WORKFLOW.md` runbook.

## Guardrails

- System events never carry a human decision id.
- Only currently projected results are opened for review.
- SUPERSEDED/EXPIRED results are never reopened by change runtime.
- New replacement results must reference their parent result.
- Existing assessor/challenger paths remain untouched.
- Bi-encoder/Cross-encoder remain opt-in; Colibri is not required for this workflow.

## Validation

Focused cumulative suite: **26 passed**.

The broader repository has previously shown one unrelated fixture failure involving a missing M3.6 event ledger and has exceeded the execution window on full-suite runs; no new failure was observed in this WB109-focused validation.
