# WB-116 Live Validation

## 1. Start from the WB-116 build

```bash
export WB_GAAR_RESULT_ENABLE=1
export WB_GAAR_AI_AUDITOR=1
export WB_GAAR_QUALITY_GATE=1
export LIVE_WB116_REQUEST_ID="$(uuidgen)"
./start_ui.sh
```

Optional gate policy overrides:

```bash
export WB_GAAR_QUALITY_EVIDENCE_THRESHOLD=0.70
export WB_GAAR_QUALITY_MIN_SOURCES=1
```

## 2. Positive path

Run a governed control through evidence -> assessor -> review/challenge -> human decision.
Expected after the human decision:

- sealed GovernanceResult exists;
- quality gate record is `FINALIZABLE`;
- state event is `FINALIZED -> CURRENT`;
- Living Results displays `quality FINALIZABLE`.

Inspect safely:

```bash
python tools/live_wb116_probe.py --evaluate
```

## 3. Blocked path

Use a test cycle with one deliberate gate failure, for example unresolved strong challenge or missing
assessor rationale. Record the human decision but do not alter the evidence to hide the failure.
Expected:

- GovernanceResult is still sealed and immutable;
- gate record is `BLOCKED` with an explicit blocker;
- **no** `FINALIZED -> CURRENT` event is emitted;
- Living Results shows human attention required and the blocker list.

## 4. Authority boundary

Confirm that Quality Gate:

- never changes maturity/sufficiency/control verdict;
- never creates a human decision;
- never marks a blocked result CURRENT;
- never mutates a sealed GovernanceResult;
- only gates the validity transition.

## 5. Regression

```bash
pytest -q tests/test_wb116_quality_gate.py
pytest -q tests/test_wb115_ai_auditor.py
pytest -q tests/test_wb113_disagreement_anchor_copilot.py
pytest -q tests/test_reviewer_copilot.py tests/test_copilot_review_correlation.py
pytest -q tests/test_reassessment_workflow_wb109.py tests/test_reassessment_live_integration_wb110.py
pytest -q tests/test_colibri_integration.py tests/test_result_contract.py tests/test_result_pipeline_integration.py
```

WB-116 is live-green only after one FINALIZABLE path and one deliberately BLOCKED path are both observed.
