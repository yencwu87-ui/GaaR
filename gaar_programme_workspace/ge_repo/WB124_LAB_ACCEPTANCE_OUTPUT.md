# WB-124 isolated laboratory acceptance (synthetic evidence)

The following commands were executed in a separate temporary lab ledger + CAS location, NOT the user's Mac and NOT against production evidence. The reported IDs are real for this one isolated run; they are not user identities or claims about control effectiveness.

```text
DRY RUN: exit=0
status: PREFLIGHT_PASSED
cycle_id: S2-2-5f671bee76
dossier_id: ED-f55e8ef2e1405f2fa587513a67075c82
anchors: 2
Evidence Examiner deterministic lexical preflight score: 1.0
open_evidence_gaps: []

APPLIED ADMISSION: exit=0
status: ADMITTED_AND_BOUND
evidence_set_id: EVID-0cf1e4fb5d6933726406d60b005d4d83

READ-ONLY PROBE: exit=0
status: PASS
prepared: 1
committed: 1
event_chain: true
cycle_evidence_bound: true
signature: OK
blobs_verified: 2
binding: AUTHORITATIVE_CYCLE_EVIDENCE
results_created: 0
```

`python -m compileall -q .`: exit 0.
Final selected A→RaaS regression: `97 passed in 5.55s`.

This demonstrates usable evidence was bound to an actual `core.cycle.start` review cycle, **not** a human review, result seal, CURRENT state, authenticated external connector, or live validation on the user's Mac.
