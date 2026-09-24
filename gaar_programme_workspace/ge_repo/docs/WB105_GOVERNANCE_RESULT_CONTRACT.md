# WB-105 — GovernanceResult Contract

## Purpose

WB-105 adds the GaaR atomic result contract without changing the live assessor, challenger, reviewer, or retrieval pipeline.

`GovernanceResult` is an immutable, cryptographically sealed conclusion. Validity is not stored as a mutable field on the result. It is projected from an append-only `StateTransitionEvent` stream.

## Model

```text
Assessment / Evidence / Challenge / Human Decision
                     |
                     v
              GovernanceResult
                     |
             immutable + sealed
                     |
             StateTransitionEvent
                     |
            current governance state
```

## Important design rules

1. A result contains the decision and rationale plus stable references to requirement, evidence, assessment, challenge, and human-decision records.
2. `result_id` is deterministic from the semantic result identity and does not contain a timestamp.
3. `content_hash` covers the canonical immutable result payload.
4. The seal uses an Ed25519 signature over the content hash and Merkle root. Private-key custody remains outside the engine.
5. Validity is derived from state events. No code path mutates `GovernanceResult` to make it CURRENT, REVIEW_REQUIRED, or SUPERSEDED.
6. A governance-change detector may open `CURRENT -> REVIEW_REQUIRED` as a system-governed trigger, but system intelligence cannot finalize a result as CURRENT.
7. `FINALIZED -> CURRENT` and `CURRENT -> SUPERSEDED` require a human decision reference.
8. State events form their own append-only SHA-256 chain with locking and fsync.
9. The WB-104 retrieval receipt can be referenced through `retrieval_receipt_id` and `retrieval_pipeline_version` in provenance.

## Integration status

This build is library/test only. The production pipeline is intentionally not wired to emit GovernanceResults yet. That avoids changing the working live path until the result contract is verified against the real final review object and human-decision records.

## Next integration step

Map the existing final review state to:

- `assessment_id`
- `evidence_set_id`
- `challenge_set_id`
- `human_decision_id`
- `decision`
- `rationale`
- actual model/prompt/retrieval provenance

Then add a single result-compiler call at the governed completion boundary.
