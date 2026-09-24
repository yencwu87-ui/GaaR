# WB-137 GaaR/RaaS maturity checkpoint

## Executive result

M3.6 is **1 of 11 milestones proven (9%)** from durable artifacts in this checkpoint. This is not a software score. It is the current governed evidence state. The only qualifying M3.6 artifact is a historical Colibri routing record. No code or configuration setting is allowed to promote a milestone to green.

The supplied evidence list contains M3.5 and other MAS controls, but no M3.6 evidence file. Therefore an admission-ready M3.6 dossier, human approval, signed CURRENT result, and replay proof cannot honestly be manufactured from this checkpoint.

Run the read-only board at any time:

```bash
python tools/maturity_status.py --control M3.6 --framework MAS
```

## Acceptance milestones

| # | Milestone | Current | Completion proof |
|---:|---|---|---|
| 1 | Control-aware evidence acquisition | Not proven | M3.6 acquisition with `EVALUATED`, no gaps, exact-control-first receipt |
| 2 | Admission-ready dossier | Not proven | `PROPOSED_ONLY` dossier with every governed element anchored |
| 3 | Governed evidence admission | Not proven | Evidence-set ID plus explicit admission into a fresh cycle |
| 4 | Assessment execution | Not proven | Assessment/proposal event for the admitted cycle |
| 5 | Independent challenge | Not proven | Challenge ID, findings, and resolutions |
| 6 | Colibri routing proof | Proven | Existing M3.6 routing record `ASSESS-M3.6` |
| 7 | Final Quality Gate | Not proven | `FINALIZABLE` gate record |
| 8 | Human governance decision | Not proven | Named human decision ID and rationale |
| 9 | Signed CURRENT GovernanceResult | Not proven | Valid Ed25519 seal and FINALIZED → CURRENT event |
| 10 | Deterministic replay | Not proven | `gaar.replay-proof.v1` PASS record |
| 11 | Regression release gate | Not proven | Machine-readable full release PASS |

## What changed

- Empty governed-element evaluations now return `NOT_EVALUATED`, `sufficiency_score: null`, and `COLLECT_MORE`; 0/0 can no longer become a perfect score.
- Retrieval now tiers exact framework + control evidence before same-framework and cross-control supplements. A semantic reranker cannot silently place M2.4 ahead of M3.6.
- The Quality Gate explicitly checks that governed elements were evaluated.
- The maturity board derives status from ledgers and cryptographic artifacts, not feature flags.
- A deterministic replay verifier recomputes result identity, payload hash, Merkle root, and Ed25519 signature without private-key access.
- The Watcher home view uses plain language: Working, Review needed, Attention, Blocked, Ready to test, or Not configured.
- Publication intake now has one guided path and one final human checkpoint: prepare review, inspect diff, then approve/sign/send in one click.
- CISA KEV, HKMA BRDR, and NFRA official publication sources are enabled only after successful read-only live probes in this validation environment. MAS and FCA remain disabled because they were not verified here.
- Double-click `Start_GaaR.command` on macOS for first-run setup and launch.

## Minimal-touch path to 100%

1. Add authoritative M3.6 evidence under the approved evidence root. It must cover the actual governed M3.6 elements; an M3.5 or M2.4 document is supplemental only.
2. Run Scout against that directory with the exact M3.6 governed requirement and elements. Resolve gaps until the receipt says `EVALUATED` and `REVIEW_CANDIDATES`.
3. In the application, use the guided admission path. One human confirms the dossier; the system creates the cycle and binds the evidence.
4. Use **Run AI audit to next safe outcome**. Machine-owned stages advance automatically and stop at policy or human boundaries.
5. Resolve independent-challenge findings. Record Colibri escalation or governed not-required proof.
6. Require `FINALIZABLE`, then have one named human approve, investigate, or reject.
7. With the deployment Ed25519 key configured, seal the GovernanceResult and confirm its CURRENT transition.
8. Run `tools/result_replay_verify.py` for the result ID. It writes a PASS proof only when all deterministic checks pass.
9. Run the release suite and record a full PASS in `WB137_VALIDATION.json`; the maturity board then reaches 100% only if all prior artifacts also exist.

## Human touchpoints retained by design

The workflow minimizes interaction but does not automate away governance authority. Evidence admission, publication approval, challenge resolution where judgment is required, and the final governance decision remain named human acts. The system may prepare, rank, diff, test, sign after authorization, and advance safe machine stages.

## Synthetic experimental path

The included `synthetic_evidence_v6` pack reuses the four prior M3.6 cases and adds an explicit
lifecycle/re-validation standard. Run `Run_Synthetic_M36.command` to rebuild the acquisition and
dossier in one step. This path is labelled `SYNTHETIC_DEMO_ONLY` and must never be combined with
the production proof percentage.
