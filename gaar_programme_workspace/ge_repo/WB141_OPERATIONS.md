# WB141 operational candidate — verification boundaries

WB140's bounded investigation contract passed synthetic acceptance tests. This checkpoint adds production-facing code, but does not establish live judgment quality, M3.6 compliance, or production readiness. No new synthetic demonstration is included.

## Start

Extract this checkpoint into its own folder. Do not overwrite your current workspace, trust policy, evidence, or ledgers. The ZIP contains `gaar_wb141_workspace/ge_repo` and a `Run_WB141.command` launcher.

The launcher creates a project virtual environment and installs missing dependencies automatically; initial setup needs access to the Python package index. It never installs into the system Python.

For manual setup, in Terminal enter the extracted `ge_repo` directory, then run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-wb141.txt
.venv/bin/python tools/gaar_operate.py --config config/wb141_operations.json doctor
```

The included configuration is intentionally unconfigured. A blocked diagnostic is expected. Existing full-app users should retain their broader dependencies from `requirements.txt`; the small manifest supports this operational entry point.

After an operator configures actual prerequisites, the normal execution command is:

```bash
.venv/bin/python tools/gaar_operate.py --config config/wb141_operations.json --investigation-id YOUR_EXISTING_INVESTIGATION_ID run
```

Alternatively set `WB141_CONFIG` and `WB141_INVESTIGATION_ID` in your Terminal environment and run `bash ../Run_WB141.command`. Without an investigation ID the launcher checks configuration. It does not silently generate identities, approvals or operating evidence.

## Configuration contract

All relative paths resolve against the configuration directory. Preserve the externally trusted WB140 policy and ledger together: policy hashes are pinned into existing signed records, so changing policy requires an explicit migration or new investigation.

- `store`: investigation SQLite journal.
- `trusted_keys`: existing WB140 public-key policy: key ID → actor, actor_type, public_key, roles, optional allow_auto_block. A challenger needs a different actor and public key from the assessor. Do not put private keys here.
- `signers`: assessor, test_planner, executor, challenger, decision → key_id and private_key_env. Environment variables supply base64 Ed25519 private seeds from operator-controlled secret storage. No keys are generated for production.
- `models`: examine, explain, plan, challenge → provider (`ollama` or `openai_compatible`), base_url, model, optional api_key_env, timeout_seconds, max_tokens. OpenAI-compatible URLs include `/v1`. Remote evidence transfer requires HTTPS and explicit `allow_remote_evidence_transfer: true`. Endpoint health is not proof of successful inference.
- `sources`: source_id → source_id, issuer, url, sha256, version, authority, snapshot_path, retrieval_receipt, approved_by, authority_decision_ref. A trusted governance signer must sign the exact approval payload containing source_id, sha256, authority, version, url. Decision files contain payload, key_id, signature, using the existing canonical JSON/Ed25519 format. Internal adoption never turns a consultation into binding regulation. This entry point currently validates official MAS/FCA/HKMA/NFRA origins only.
- `collectors`: approved root and relative path, source_id, sha256, exact scope (system_id/version/period), authority, provenance, segments. Segments use existing WB140 fields: start/end Unicode character offsets, evidence_id, element_ids, purposes, finding_status. Sources are UTF-8 exports; binary documents require separately governed extraction. Hashes prove byte identity, not truth or original-source authenticity. File symlinks resolving outside the approved root are rejected.
- `expected_heads`: investigation ID → externally retained current journal hash. Existing owner-signed context and governance-signed expectations are prerequisites. The command does not manufacture these authorizations. Retain returned heads externally after a run; do not automatically accept a changed database head.
- `receipt_dir`: restricted local directory for signed live request/response receipts. Receipts contain evidence-bearing prompts and responses; apply organizational retention/access controls. They are individually signed but not an externally anchored append-only log.

For M3.6, the trusted test-planner policy must explicitly include all four registered tool/version pairs under `required_tools_by_control.M3.6`. Define that policy before creating the investigation, because its hash is bound into the journal. Mandatory-tool enforcement blocks a plan that omits required tests. These four procedures do not cover every governed M3.6 element.

The existing source-authority, ownership and decision signing APIs remain the authorization boundary. This release does not add an approval UI or automatically migrate unsigned legacy cycles. It does not establish production precedent retrieval; unconfigured retrieval remains visibly unattempted.

## Execution and conclusions

The command collects approved files, admits exact slices, invokes live examination/explanation/planning, executes allowlisted read-only procedures, and invokes an independent signed challenge. Model proposals pass the existing contract validators. There is no scripted production fallback. Automatic conclusions require an existing authorized deployment-hold policy; otherwise execution stops for authorized disposition.

Missing evidence produces an assurance gap, not an invented operational breach. Positive observed failures and missing assurance may coexist. A blocked deployment can accompany a finalizable adverse or inconclusive report. This command never manufactures deployment authorization or a CURRENT GovernanceResult. Existing result sealing still requires its governance workflow.

Live receipt status RESPONSE_RECEIVED means a transport returned text, not that the text was valid, accurate or accepted. Stage validation failures remain visible and do not advance the journal. Bitwise replay of stored deterministic procedures is separate from regenerating nondeterministic model responses.

## Four executable procedures

Each accepts a JSON operating export with scope (system ID), model_version, as_of (timezone-aware and identical to investigation period), source_refs and criteria_ref. Criteria are supplied records; this release does not independently prove that each threshold was substantively approved. Source_refs must be examined against supporting evidence. No regulatory numeric thresholds are invented.

| Procedure / version | Inputs and implemented check | Limit |
|---|---|---|
| m36_model_evaluation / 1 | prediction_records (sample_id, model_version, actual_label, predicted_label), approved_thresholds (accuracy/error_rate with operator and value), threshold_agreements (role/actor_id/record_ref), training_sample_ids. Recomputes accuracy/error; checks threshold and ID overlap. | Does not execute the model, establish label truth or exclude all data leakage. Agreement records need not be signatures. |
| m36_representativeness / 1 | dimensions: name, population_counts, test_counts, max_share_difference, min_test_count. Compares group distributions to supplied criteria. | Aggregate comparisons cannot establish completeness, omitted groups or future-context adequacy. |
| m36_independent_validation / 1 | validation_record: model_version, reviewer_ids, completed_at, kind, area_evidence_refs, challenge_records; developer_ids, deployer_ids, competency_evidence, deployment_at, risk_tier, required_review_areas. Checks scope, role overlap, timing and referenced coverage. | References and roles do not prove actual competence, effective challenge or validation quality. |
| m36_residual_risk / 1 | risks: risk_id, owner_id, assessment_ref, residual_score, appetite_limit, scale_id, acceptance(actor_id, record_ref, at); authorized_acceptors, deployment_at, validation_findings. Compares supplied same-scale risk/appetite and checks disposition records. | Requires credible risk measurement, authority and evidence of completed remediation; an absent disposition is an assurance gap. |

Results preserve findings, assurance_gaps, metrics, input hash and scope. Zero denominators cannot become pass. Cross-model predictions and mismatched model/system/period are rejected. Reproducible supplied-record comparison is not proof of substantive audit quality.

## Official source retrieval

```bash
.venv/bin/python tools/gaar_operate.py --config config/wb141_operations.json fetch-sources
```

Candidate URLs are discovery starting points, including indexes and a consultation; they are not approved requirements. Successful raw downloads are QUARANTINED, never automatically approved. Failures are UNABLE_TO_CHECK. A regulator landing page is not a control-specific authority snapshot. Verify the exact publication and applicability before signing a source decision. Current attempt receipts are in `verification/wb141/source_checks.json`.

## Held-out judgment evaluation

```bash
.venv/bin/python tools/gaar_operate.py --config config/wb141_operations.json benchmark
```

No independently labeled held-out corpus was supplied, so the included run is NOT_EVALUATED. Unit-test fixtures are not judgment proof.

Configure held_out_manifest as a signed JSON envelope (payload/key_id/signature). Payload contains frozen_at, development_input_hashes, cases. Each case has case_id, category, path, sha256. Required categories: violation, legitimate_exception, contradiction, insufficient_evidence. Each input JSON contains only context, evidence, allowed_refs. Labels stay in the manifest and are not sent to the model. A trusted judgment_evaluator distinct from the assessor signs the manifest. Duplicate cases, changed inputs, declared development overlap and invented reference IDs are rejected. Unavailable/invalid model answers count against all-case accuracy and mark the run PARTIAL.

This initial harness measures classification and referenced-evidence validity. It does not yet independently score examination depth, explanation quality, test selection or challenge effectiveness. Those remain WB141 completion work, together with a governed real corpus and live runs.

## Remaining completion gates

1. Configure operator-owned identities, frozen authority-approved source snapshots, collectors and policies.
2. Supply real scoped operating evidence and owner/governance-signed investigation stages.
3. Execute all four live agent stages; inspect signed receipts and accepted stage records.
4. Independently evaluate held-out judgment across all agent tasks, not only classification.
5. Bind completed real investigations into normal review cycles and run real sealing/replay with authorized decisions.
6. Verify deployment configuration and production retrieval, including dependency/precedent quality.

These are not replaced by a clean software regression run. No 100% maturity claim is justified by this checkpoint.
