# WB-118 Live Validation — Mac

From repo root:

```bash
export WB_GAAR_RESULT_ENABLE=1
export WB_GAAR_AI_AUDITOR=1
export WB_GAAR_CHANGE_INTELLIGENCE=1
export WB_GAAR_REASSESSMENT_WORKFLOW=1
export WB_GAAR_QUALITY_GATE=1
export WB_COLIBRI_GOVERNED_ESCALATION=1
export WB_GAAR_AUTOPILOT=1
export WB_GAAR_AUTOPILOT_MAX_CONCURRENT=3
```

## Integrity and tests
```bash
python -m compileall -q .
python -m pytest -q \
  tests/test_g_autopilot.py \
  tests/test_g_integration.py \
  tests/test_wb117_governed_colibri_escalation.py \
  tests/test_wb116_quality_gate.py \
  tests/test_wb115_ai_auditor.py \
  tests/test_wb113_disagreement_anchor_copilot.py
python tools/live_g_autopilot_probe.py
```

## Operator checks
```bash
python tools/autopilot_status.py
python tools/autopilot_trigger.py --control SAFR-2.1 --framework SAFR --reason manual_validation
python tools/autopilot_run.py --claim
python tools/autopilot_status.py
```

A manual trigger is intentionally not converted into a regulatory GovernanceChange. The execution adapter fails closed rather than inventing authority/change context.

## Full live change scenario
Use the existing C change workflow to create a real `GovernanceChange` + `ImpactAssessment` against a CURRENT result. Then verify:
1. one material change is deduplicated into one trigger;
2. C emits `CURRENT -> REVIEW_REQUIRED` only for impacted CURRENT results;
3. D emits `REVIEW_REQUIRED -> REASSESSING` and starts a new cycle with the old evidence set;
4. the Review Conductor advances machine-owned nodes and stops at a governed checkpoint;
5. job status becomes `WAITING_HUMAN` when judgment is required;
6. after the real human decision, WB-116 runs and only FINALIZABLE results become CURRENT;
7. Living Results and Autopilot UI show the same state as the append-only ledgers.

WB-118 is live-green only when these outputs agree across CLI, UI and ledgers.
