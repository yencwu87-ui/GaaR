# WB-113 — Disagreement Challenge Admission + Challenge Copilot

## Why this checkpoint exists
Live review of MAS 2.2 and SAFR 2.1 exposed a mismatch between the disagreement challenger prompt and its validator. The validator already knew three governed anchor types, but the disagreement prompt demanded a verbatim evidence quote for every challenge. Evidence-absence and reviewer-reasoning challenges were therefore frequently generated in prose and then rejected at admission.

## Fixes

### 1. Three first-class disagreement anchors
The disagreement pass now explicitly supports exactly one anchor per challenge:

- `factual_pointer`: a verbatim supplied-evidence quote. This is the only anchor that may support a `strong` rebuttal when it positively contradicts the attacked verdict.
- `absence_pointer`: a deterministically verified absence of a control-declared artefact. It is always `weak/refining`, never strong.
- `reviewer_pointer`: a verbatim quote from the reviewer's recorded reading when the problem is reasoning/overreach. It is always `weak/refining`, never strong by itself.

This means:
- SAFR-style positive evidence contradictions can be admitted as factual rebuttals.
- MAS-style "the evidence does not demonstrate the required design/operating evidence" arguments can be expressed as verified absence or reviewer-reasoning challenges instead of being forced into a fake quote.

### 2. Anchor-preserving validator output
Validated challenge rows now preserve `anchor_kind` and the corresponding pointer object. The runtime no longer rewrites every verified anchor into `factual_pointer`.

### 3. Disagreement challenge is visible in Streamlit
An admitted disagreement challenge is rendered with:
- element id
- which side it supports (`reviewer`, `assessor`, `neither`)
- challenge strength
- grounding anchor type
- verified evidence/reviewer/absence anchor
- inference and resolution pointer

A blocked pass now displays the actual validation/admission error instead of only a generic retry message.

### 4. Challenge Copilot
A bounded Challenge Copilot is available only after an admitted challenge exists. It may:
- explain the admitted challenge
- surface verifiable evidence to inspect
- propose questions for the reviewer
- draft an optional response note

It may NOT:
- alter `supports` or `challenge_strength`
- issue sufficiency or maturity
- approve/reject the challenge
- make a governance decision

Challenge Copilot requests/presentations/rejections are append-only cycle events and use the existing governed inference router.

### 5. Dossier lineage
Challenge dossiers preserve `anchor_kind`, `factual_pointer`, `absence_pointer`, and `reviewer_pointer` instead of retaining only factual pointers.

## Validation

Focused regression suite:

```text
214 passed in 28.76s
```

Coverage includes assessor contract, challenge reasoning/runtime/hardening, disagreement pass, Reviewer Copilot, Colibri integration/routing, WB-109/WB-110 reassessment, Governance Result contract, Operations dashboard/UI, event-kind boundary checks, and WB-113 anchor/Copilot tests.

`python -m compileall -q .` also passed.

## Retest expectations

### SAFR 2.1
If the supplied evidence contains a verbatim statement that materially contradicts a lower reviewer verdict (for example governance-set thresholds reviewed before deployment), the disagreement pass can admit a `factual_pointer` challenge. It may be strong only when that fact actually contradicts the attacked verdict.

### MAS 2.2
If the issue is that supplied evidence does not demonstrate required design/operating evidence, the challenger should use `absence_pointer` when a declared artefact is deterministically absent, or `reviewer_pointer` when the reviewer's conclusion exceeds what the evidence establishes. These are weak/refining challenges rather than false strong rebuttals.
