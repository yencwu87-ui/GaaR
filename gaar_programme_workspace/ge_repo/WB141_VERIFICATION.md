# WB141 verification record

Status: implementation candidate. WB141's operational completion contract remains open.

## Implemented

- One production command for diagnostics, execution, official-source quarantine and held-out evaluation; macOS launcher bootstraps the isolated project environment.
- Real Ollama and OpenAI-compatible inference adapters for examination, explanation, planning and independent challenge; signed request/response receipts and no scripted fallback.
- Operator-scoped read-only UTF-8 collectors, hash checks and existing typed admission.
- Official-origin source fetching, maintenance/empty-shell detection, exact snapshot hashes and signed authority decisions.
- Four M3.6 supplied-record procedures for performance, representativeness, validation records and residual risk. Required test selection is enforced when approved policy names these procedures; the production M3.6 route requires that policy.
- Existing signed investigation contract and quality gate retained. Missing proof remains an assurance gap. An executed M3.6 finding or gap prevents a PASS investigation.
- Held-out evaluation harness with signed independent labels, frozen hashes, declared development exclusions, category coverage and signed live receipts. No corpus or judgment score fabricated.

## Fresh regression and fixes

Baseline: 1,183 passed, 11 failed, 3 skipped. This was a fresh run; the historical 1,151/17 figures were not reused.

The failures comprised:

1. A real autopilot bug: INVESTIGATION_REQUIRED incorrectly became COMPLETE without attention. Fixed to WAITING_HUMAN and tested against the exact checkpoint.
2. Missing ticket-register references for newer work. Added WB139–141 with NOT_RECORDED approvers and implementation-pending-approval status; no approval invented.
3. Nine legacy expectations that assumed unsigned cycles could reach later gates. The affected historical contract tests explicitly select the existing legacy compatibility mode. Production defaults remain enforced; tests separately prove default mandatory investigation and no downgrade for bound records. No blanket test-suite gate bypass was added.

The first post-fix run reported 1,207 passed, 3 skipped and one warning. A 12-second timeout was swallowed in a ZipFile destructor during full Streamlit-app import. That is not a clean verification result. The shared display projection was extracted into `ui/review_projection.py`; the app and tests use the same implementation without tests starting the whole UI.

The final clean run is recorded below and in `verification/wb141/final_clean.xml`. Earlier logs are retained so the sequence is auditable. New operation tests are software/protocol tests, not evidence of auditor judgment.

## Live verification

- Local configured inference endpoint: connection refused. Four live agent stages NOT_EVALUATED. These checks concern this execution environment, not the user's Mac.
- MAS candidate: HTTP response contained a maintenance page, including more than 800 KB of HTML. Rejected after visible-content validation.
- FCA candidate: HTTP 403.
- HKMA candidate: HTTP 404. This URL must be replaced with an actual applicable publication.
- NFRA candidate: HTML shell without usable publication text. Rejected.

Downloaded response bodies and initial quarantine receipts remain available under config/source_quarantine. `verification/wb141/source_checks.json` adds content-validation outcomes; successful HTTP transport was not promoted to approved source authority. All four candidate checks end UNABLE_TO_CHECK. They establish neither current law nor control applicability.

No trusted production identities, source approvals, real scoped operating evidence or independently labeled held-out corpus were supplied. `doctor.json` records BLOCKED; `judgment.json` records NOT_EVALUATED with zero executed cases.

## Boundaries still open

- No actual live inference receipt from a configured assessment model, accepted production investigation, human risk acceptance, production seal or CURRENT result was produced.
- The benchmark currently evaluates category classification and reference validity, not all four agent tasks' reasoning quality. A governed corpus, task-specific rubrics and live evaluation remain required.
- The new entry point advances the existing investigation service; it does not migrate every legacy UI assessment or automatically populate missing owner/authority decisions. Production precedent retrieval remains unverified/unconfigured.
- Four supplied-record comparisons do not establish all 14 M3.6 elements. Threshold authority, label truth, population completeness, validator competence and substantive risk judgments require their own corroboration.
- Signed receipts prove their bytes and signer, not judgment correctness. External anchoring and retention of live receipts remain operational requirements.
- macOS launcher syntax was checked here; execution on macOS and fresh dependency installation were not tested in this Linux environment.

No canonical M3.6 regulatory interpretation, human approval, synthetic demo or investigation-record schema was changed.

## Final recorded results

- Full offline regression: **1210 passed, 0 failed, 0 errors, 3 skipped**; 199.272 seconds.
- Final procedure/contract follow-up: **25 passed, 0 failed, 0 errors, 0 skipped**; 0.612 seconds.

The focused follow-up verifies the final null-label and source-reference guard after the full run. Missing ground-truth and predicted labels cannot be counted as a correct prediction. No runtime gate was disabled for this verification.

The three full-suite skips are: a permissions test whose premise does not apply when running as root, and two contract-refusal tests for which no currently invalid canonical contract exists. No live-model or judgment test is represented by these software results.

Reproduce the offline suite from ge_repo with the full development environment and pytest-timeout installed:

```bash
WB_WEB_KNOWLEDGE=off python3 tools/wb141_offline_regression.py -q --timeout=12 --timeout-method=signal
```

The distributable retains the original checkpoint data and ledgers unchanged; temporary regression-generated application data is excluded. Code, configuration templates, corrected launcher, tests and verification records are overlaid. The archive includes a content SHA-256 manifest.
