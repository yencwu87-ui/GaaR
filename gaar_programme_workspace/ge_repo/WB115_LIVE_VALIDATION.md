# WB-115 Live Validation — AI Auditor / Agile Review / Living Results

WB-115 is **build-green, live-pending** until this protocol passes on the live Mac repository.
Do not delete durable ledgers. Use a fresh request/cycle and keep B/D evidence intact.

## 1. Install and launch

```bash
python3 -m pip install -r requirements.txt
export WB_GAAR_AI_AUDITOR=1
export WB_GAAR_RESULT_ENABLE=1
./start_ui.sh
```

In the sidebar choose **Supervised Autopilot**.

## 2. UI acceptance

Select MAS + MGF Agentic + SAFR simultaneously.

- Review / Focus must show sections for all three frameworks. SAFR must not disappear behind a global row cap.
- Review / Kanban must show governed cards across BACKLOG, AUTOMATION, HUMAN READ, VERIFY, EXCEPTION, DECISION, DONE.
- Review / Stand-up must show human-read, exception, strong-challenge and ready-for-decision counts.
- Record a SAFR decision and rerun the app. AI Auditor and Outcomes must increment the SAFR decision count from the append-only event ledger.
- AI Auditor / Governed processing must show the cycle event stream without hidden chain-of-thought.
- Living Results is read-only and projects immutable result history.

## 3. Safe live probe

```bash
export LIVE_WB115_REQUEST_ID="$(uuidgen)"
python tools/live_wb115_probe.py --control 2.1 --framework SAFR
```

To advance only machine-owned nodes:

```bash
python tools/live_wb115_probe.py --control 2.1 --framework SAFR --run --reviewer "$USER"
```

The probe is intentionally incapable of calling `cycle.decide()`.
Expected stop nodes are `EVIDENCE_REQUIRED`, `HUMAN_READ`, `HUMAN_EXCEPTION`, `HUMAN_DECISION`, or `COMPLETE`.

## 4. Skill/schema acceptance

```bash
pytest -q tests/test_wb115_ai_auditor.py
pytest -q tests/test_wb113_disagreement_anchor_copilot.py
pytest -q tests/test_reviewer_copilot.py tests/test_copilot_review_correlation.py
pytest -q tests/test_reassessment_workflow_wb109.py tests/test_reassessment_live_integration_wb110.py
```

Required invariants:

- Evidence Examiner input is typed; scalar `requirement_context` fails validation.
- Evidence score outside [0,1] fails validation.
- Control Narrative cannot emit maturity/sufficiency/decision/rating fields and every quote is verifiable.
- Challenge Copilot cannot alter challenge support/strength or governance state.
- All registered AI Auditor skills are state-free; only the Conductor may sequence calls.
- Conductor cannot synthesize a human read or final decision.

## 5. Authority boundary

For a cycle reaching decision:

```bash
python tools/live_wb115_probe.py --cycle-id <cycle-id> --run --reviewer "<named-human>"
```

It must stop at `HUMAN_DECISION`. The final `decided` event must still be created only by the named human through the existing UI/API decision boundary.

## 6. Living result

After a human decision with GaaR result sealing enabled:

```bash
python tools/live_wb115_probe.py --control 2.1 --framework SAFR --living
```

Expected: immutable current result, state, result version and R1→R2 history if reassessed. No write occurs from this endpoint/projection.

## WB-115 GREEN definition

WB-115 is green only after the live Mac confirms:
1. SAFR visibility with all frameworks selected.
2. SAFR dashboard update from ledger after a decision.
3. Conductor advances machine nodes and stops at human checkpoints.
4. MAS/SAFR WB-113 challenge grounding still works.
5. Control Narrative is evidence-anchored and limitation-aware.
6. Result/state provenance remains intact.
7. Living Results reads but never mutates history.
