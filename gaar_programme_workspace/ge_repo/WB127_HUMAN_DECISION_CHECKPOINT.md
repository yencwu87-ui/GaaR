# WB-127 — One-click / Batch Human Decision Checkpoint

## Purpose

WB-127 closes the local straight-through processing decision surface without adding a second governance decision engine.

Every successful approval uses the existing authoritative path:

`governance.audit_package.decision_service.approve_one()` → `core.cycle.decide()` → sealed `GovernanceResult` → WB-116 final Quality Gate → existing result state transition.

Batch approval is only a UI convenience. `approve_batch()` iterates eligible routine cycle IDs and calls `approve_one()` for each item. Each approved control therefore receives its own human decision ID, sealed result, Quality Gate outcome and result-state event.

## Safety boundaries

- The AI never invokes `core.cycle.decide()` itself.
- A named human reviewer attribution is mandatory; `SYSTEM` is rejected.
- Local reviewer names are **attribution only**, not authenticated IAM/RBAC identities.
- Decision-time preflight rechecks the core-cycle checkpoint, routine waiver, WB-126 challenge, result signing configuration and Quality Gate enablement.
- `core.cycle.decide()` performs its own WB-125/WB-126 revalidation again inside the authoritative decision boundary.
- A final Quality Gate `BLOCKED` outcome produces a sealed FINALIZED result but does **not** project it to CURRENT.
- `Investigate` and `Reject Proposal` write append-only human notes and create no GovernanceResult.
- A proposal rejection does not silently mean `FAIL`; an alternate human judgement is still required.
- Elevated/non-routine cycles are excluded from batch approval.

## Provenance correction

WB-126 `independent_challenged` events are now included in the sealed GovernanceResult challenge-set identity and workflow timestamps. This makes the independent challenge visible in result provenance rather than merely in the cycle ledger.

## Local UI

The Streamlit sidebar now contains **Human Decision Queue · WB-127**:

- Approve
- Investigate
- Reject Proposal
- Batch approval for decision-ready routine cycles

The UI explicitly states that reviewer identity is local attribution, not authenticated IAM/RBAC.

## CLI

Read-only preflight:

```bash
python tools/human_decision.py --cycle <cycle_id> --reviewer "Your Name" --action preflight
```

Individual approval:

```bash
python tools/human_decision.py --cycle <cycle_id> --reviewer "Your Name" --action approve
```

Request investigation:

```bash
python tools/human_decision.py --cycle <cycle_id> --reviewer "Your Name" \
  --action investigate --note "Explain the evidence or issue that requires investigation."
```

Reject the AI proposal without manufacturing a final FAIL decision:

```bash
python tools/human_decision.py --cycle <cycle_id> --reviewer "Your Name" \
  --action reject --note "Explain which evidence or proposed conclusion is disputed."
```

Batch approval (repeat `--cycle`):

```bash
python tools/batch_human_decision.py \
  --cycle <routine_cycle_1> \
  --cycle <routine_cycle_2> \
  --reviewer "Your Name"
```

## Required environment

```bash
source "$HOME/.config/gaar/result-signing.env"
export WB_GAAR_RESULT_ENABLE=1
export WB_GAAR_QUALITY_GATE=1
export WB_GAAR_ROUTINE_WAIVER_ENABLED=1
export WB_GAAR_INDEPENDENT_CHALLENGE_ENABLED=1
```

The routine waiver policy file and WB-124/WB-126 prerequisites must already be valid for routine batch eligibility.

## Lab validation performed

- `tests/test_wb127_human_decision.py`: 9 passed.
- WB-124 → WB-127 checkpoint tests: 44 passed when executed as their focused modules (WB-124 admission 11, WB-125 waiver/watcher 13, WB-126 11, WB-127 9).
- Earlier critical A→RaaS regression subset: 62 passed.
- Python `compileall`: PASS.

The combined single process run exceeded the execution environment time budget, so the checkpoint modules were executed in smaller batches. No claim is made that the repository's entire historical test suite was run in one invocation.

## Mac live acceptance

Use a real cycle that has:

1. WB-124 admitted evidence;
2. WB-125 active signed routine waiver (for routine path);
3. WB-126 admitted independent challenge with no unresolved strong finding;
4. result sealing key configured; and
5. final Quality Gate enabled.

Then:

```bash
python tools/human_decision.py --cycle <cycle_id> --reviewer "<human reviewer>" --action preflight
```

Expected for a routine-ready item:

- `single_eligible: true`
- `batch_eligible: true`
- `checkpoint: HUMAN_DECISION`
- no blockers

Approval:

```bash
python tools/human_decision.py --cycle <cycle_id> --reviewer "<human reviewer>" --action approve
```

Expected outcomes:

- `decision_path: core.cycle.decide`
- unique `human_decision_id`
- unique `governance_result_id`
- final gate `FINALIZABLE` → `status: CURRENT`
- final gate `BLOCKED` → `status: BLOCKED_FINALIZED`, never CURRENT

Do not use batch approval until individual approval has been validated against your live Mac state.

## Remaining production gates

WB-127 completes the **local governed human-on-exception path**, but it is not production identity assurance. Remaining production work includes authenticated user identity/RBAC, transaction/concurrency hardening for multi-user approvals, external authenticated evidence connectors, global regulatory Watcher source admission, deployment security, recovery/back-pressure and full Mac/live acceptance.
