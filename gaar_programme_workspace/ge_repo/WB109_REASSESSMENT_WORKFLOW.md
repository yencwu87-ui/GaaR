# WB-109 — Governed Reassessment Workflow

This build extends Workstream C with a deterministic reassessment orchestration layer. It does not replace the existing assessor, challenger, or human-review pipeline.

## State model

```text
CURRENT
  │
  │ GovernanceChange + material impact
  ▼
REVIEW_REQUIRED        (SYSTEM; trigger_id = change_id; decision_id = null)
  │
  │ reassessment case starts
  ▼
REASSESSING            (SYSTEM; trigger_id = case_id; decision_id = null)
  │
  ├── human confirms same immutable result ──► CURRENT
  │
  └── human approves replacement result ─────► SUPERSEDED
                                              │
                                  replacement result FINALIZED → CURRENT
```

## Guardrails

- A system event may trigger or advance workflow execution but cannot finalize governance state.
- `decision_id` is present only when a human-governed transition occurs.
- A replacement result must reference the old result through `parent_result_id` / `supersedes_result_id`.
- Historical `SUPERSEDED` and `EXPIRED` results are never reopened by the change runtime.
- The existing assessor/challenger stack remains the producer of reassessment evidence and conclusions. This module does not call an LLM.
- Change and reassessment case stores are append-only and hash-chained.

## Feature flags

```bash
export WB_GAAR_RESULT_ENABLE=1
export WB_GAAR_CHANGE_INTELLIGENCE=1
export WB_EVIDENCE_BI_ENCODER=0
export WB_EVIDENCE_CROSS_ENCODER=0
```

Keep Bi/Cross disabled until retrieval calibration is complete. Colibri is not required for this workflow stage.

## Runtime modules

- `governance/change_runtime.py` — persists GovernanceChange/ImpactAssessment and emits current-result review triggers.
- `governance/reassessment.py` — opens and advances reassessment cases and emits governed state events.
- `governance/result_contract.py` — owns the explicit `REASSESSING` state and transition rules.

## Human boundary

The reassessment engine may create a new assessment task, but only the existing human decision boundary may create the human `decision_id` that moves an immutable result to `CURRENT` or `SUPERSEDED`.
