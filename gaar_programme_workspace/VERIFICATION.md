# Verification and acceptance record

## 2026-09-21 — pilot MVP revision

**1,248 passed, 11 skipped, 0 failed, no warnings (245.66 seconds). 30 focused checks passed. `pip check` clean. The package tree was byte-identical after the full run.**

What changed and is covered by tests:

- `governance/decisions.py`, the supplied human-decision contract, is unchanged in behaviour; its test passes as supplied. A shared `_preflight` core now also serves a pilot path that tolerates exactly one gate blocker, `production_judgment_not_qualified`.
- Pilot attestation: human-signed, head-bound, verdict-mapped, one per investigation, journalled as `pilot_attestation` with `reliance: PILOT_DECISION_SUPPORT` and `governance_result: false` inside the signed payload. `lifecycle.seal` refuses such an approval even under a forged-qualified production configuration (tested).
- `tools/gaar_pilot.py`: keygen outside the package; provision accepts supplied human keys, refuses group-readable keys, keys inside the pilot directory or package, and unconfirmed scope; mints six service keys; signs the internal source and precedent corpus with the governance person's key; creates non-synthetic signed initial stages. Supplied key files are unchanged by provisioning (tested).
- Reviewer app: token lock, evidence hidden until **Open evidence and reasoning**, reveal logged to `reviewer_access.jsonl`, source-approval column, attestation through the UI (tested end to end with Streamlit AppTest).
- Qualification rejects identical examine/challenge revisions served from different endpoints.
- PDF tests skip cleanly when optional PyMuPDF is absent instead of failing on import.
- Root `conftest.py` restores six legacy governance ledgers that existing tests write into, and names them in the terminal summary. The legacy tests that write them are not changed.

Still not established by this revision: a live pilot run, live model judgment, independent evaluation, real evidence, enterprise identity, macOS acceptance, WB149 security approval. The access log is unsigned.

Logs: `ge_repo/verification/wb143_149/full_regression_pilot.log`, `focused_pilot.log`, `pip_check_pilot.log`.

## 2026-09-20 — reviewer/on-ramp revision (retained)

**2026-09-20: 1,249 passed, 3 skipped, 0 failed, no warnings in the final offline suite (198.35 seconds).** The 23 focused programme checks passed. `pip check` reports no broken requirements. Shell syntax and Python compilation checks passed.

These results verify software behavior on Linux with scripted model responses and isolated identities. They do not establish live model judgment, production evidence quality, independent human approval, macOS usability or production assurance. Tests that exercise a production-shaped result deliberately mock qualification and use synthetic keys; those results are not deployment artifacts.

| Gate | Implemented/proved here | Still required for acceptance |
|---|---|---|
| WB143: Integrated investigation | Implemented; offline protocol tests passed | Live end-to-end investigation, trusted setup and target-user acceptance not verified |
| WB144: Dependency review | Exactly-one treatment, executed-test references and challenge binding implemented | Catalogue completeness, applicability and treatment semantics need independent expert validation |
| WB145: Judgment evaluation | Full-contract live runner and signed qualification gate implemented | No independent corpus, live responses, semantic measurements or auditor baseline supplied |
| WB146: Evidence and verification | Scoped collection adapters, change checks and inherited M3.6 procedures implemented | Enterprise connectors, collection authenticity/completeness and real control coverage unverified |
| WB147: Results and reassessment | Signed seal, adverse CURRENT, change invalidation and local reassessment requests tested | Real result, external anchoring, scheduled continuous reassessment and successor/supersession workflow outstanding |
| WB148: Actions and reporting | Local actions, optional policy assignment, draft notifications and closure guards implemented | Authorized external delivery, full closure acceptance and operational ownership unverified |
| WB149: Production assurance | Local security/recovery checks, signed backup/isolated restore and environment report implemented | Independent security review, revocation/failover drills, macOS acceptance and release approval outstanding |

## New checks

Integrated change run/idempotent resume; missing production qualification; missing evidence; crash before/after stage append; changed evidence requires revision; journal role abuse/rollback; signed backup/tamper/restore; missing record versus contradiction; concurrent-run lock; missing precedent visibility; dependency omission and unexecuted-test rejection; unapproved collector endpoint; full-schema evaluation prerequisites; signed result sealing/idempotence and changed-evidence non-repromotion; internal policy authority/human approval; invalid qualification signature; legacy single-run and reviewer-app missing-setup behavior; stage/operational trace integrity; receipt signature/hash tamper detection; evaluation-only provisioner identities, offsets and signed initial stages; invalid remediation closure.

## Reproducible evidence

`ge_repo/verification/wb143_149/full_regression_reviewer.log` is the final full run. `focused_reviewer.log` is the focused run. `environment_check.json` records actual missing service/identity/source/qualification configuration and Linux rather than macOS. `pip_check_reviewer.log` records software dependency consistency, not vulnerability scanning. `runtime_versions.json` records the runtime. Earlier failed collection and pre-final logs are retained for transparency; an import cycle and a repeat-sealing idempotency defect were corrected.

## Explicit limitations

- No running live model was available; endpoint health returned connection refused.
- No real production evidence, trusted identities, approved source snapshots or independent evaluation corpus was provided.
- No actual human authorization, notification delivery or production deployment occurred.
- Local signatures and anchors do not replace external immutable retention, encryption/key management or host security.
- Restore verifies a new directory and retained cryptographic heads; it does not prove disaster-recovery service failover.
- Adversarial audit, key compromise/revocation, multi-user access control, enterprise integrations and Mac target acceptance remain release gates.
- The 29 dependency relationships remain proposed internal knowledge; no blanket regulatory mapping or completeness claim is made.
- No percentage of overall production maturity is inferred from passing tests.

The eight-agent picture remains a capability map. This package does not certify that every box is a deployed production service.
