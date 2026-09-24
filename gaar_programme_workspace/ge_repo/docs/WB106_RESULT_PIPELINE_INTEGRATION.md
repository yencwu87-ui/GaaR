# WB-106 — GovernanceResult Pipeline Integration

## Purpose

WB-106 wires the Workstream A `GovernanceResult` contract into the existing assessment cycle without
changing assessor, challenger, retrieval, or UI decision semantics.

The integration boundary is `core.cycle.decide()`, because that is the code-enforced human decision
boundary. `pipeline.py` produces assessment inputs, but it does not own the final human decision.

## Runtime behaviour

The feature is disabled by default:

```bash
export WB_GAAR_RESULT_ENABLE=0
```

When enabled, the existing human decision path compiles a sealed `GovernanceResult`, records the
stable `human_decision_id` / `governance_result_id` on the existing `decided` event, persists the
immutable result to an append-only result store, and records `FINALIZED -> CURRENT` as a separate
`StateTransitionEvent`.

Required local/dev configuration:

```bash
export WB_GAAR_RESULT_ENABLE=1
export WB_GAAR_RESULT_KEY_ID="gaar-dev-key"
export WB_GAAR_RESULT_SIGNING_KEY_B64="<32-byte-ed25519-seed-base64>"
```

Production signing should be supplied through an HSM/KMS/Vault adapter rather than environment
variables. The current environment adapter exists only to make the integration boundary explicit
and testable.

## Artifact references

The integration derives temporary local references for the current repository:

- `REQ-*`: hash of framework, control id, current control requirement and mappings. This is not yet a
  claim of an external regulatory `RequirementVersion` registry; Workstream C will introduce the
  canonical requirement/source model.
- `EVID-*`: hash of the evidence bundle, including the retrieval receipt.
- assessment id: existing `assessment_identity.assessment_id` where available.
- `CHALL-*`: hash of the challenge records and their source event ids.
- human decision id: the id of the `decided` event itself.

## State model

`GovernanceResult` is immutable. It contains no mutable validity state.

```text
GovernanceResult
      |
      v
ResultStateEvent
      |
      +-- FINALIZED -> CURRENT   (human decision)
      +-- CURRENT -> REVIEW_REQUIRED (future GovernanceChange signal)
      +-- CURRENT -> SUPERSEDED    (future reassessment approval)
```

## Safety properties

- Disabled by default; existing behaviour is unchanged when the flag is off.
- The compiler runs before the decision event is committed when enabled, so a missing signer or
  failed result construction blocks the governed decision rather than silently creating an
  unsealed decision.
- The existing append-only assessment event log remains the lifecycle source of truth.
- The immutable result is stored separately to avoid duplicating the full signed artifact inside the
  assessment event stream.
