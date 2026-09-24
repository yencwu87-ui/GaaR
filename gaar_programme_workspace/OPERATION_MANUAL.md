# Integrated programme operation manual

## 1. Install and launch

Extract this complete ZIP into a new folder. Do not copy it blindly into WB136 or overwrite old evidence and ledgers. Open the outer `Start_GaaR.command`. In Terminal you can type `bash ` and drag the launcher into the window, then press Enter. From the extracted folder, the equivalent command is:

```bash
bash ./Start_GaaR.command
```

The launcher creates `ge_repo/.venv` and installs core requirements if missing. Python 3 must already exist and first installation needs internet access. The single-run page installs Streamlit when selected. Model installation/startup is an administrator prerequisite; it is not silently downloaded.

## 2. Normal operation after setup

| Menu | Action |
|---|---|
| 1 | Check actual model, identity, source and knowledge readiness |
| 2 | Save configuration path/assessment ID and select models reported by local services |
| 3 | Run/resume the saved assessment |
| 4 | Explore change-control dependency questions and alternatives |
| 5 | Run the independently approved full-contract held-out evaluation |
| 6 | Open this manual |
| 7 | Start the historical workbench; programme approval cannot bypass its gates |
| 8 | Report production-assurance prerequisites and limitations |
| 9 | Open the reviewer front door: result, resolved trace, selected Run / resume and the human decision panel |
| P | Show the pilot on-ramp (bring your own keys) |
| 0 | Exit |

The reviewer app uses localhost port 8502. Select system, select assessment, click Run. It executes approved machine stages and shows a result or precise boundary. No interstage file copying or manual head updates are required. It joins the signed stages, operational journal, dependency treatments, evidence references, test outputs, challenge and inference receipts into one reviewer trace. Reopening the console remembers setup in `ge_repo/config/programme_console.json`.

Raw evidence and model prompts/responses are hidden until the reviewer presses **Open evidence and reasoning**. That reveal lasts for the session and the selected assessment only, and is appended to `reviewer_access.jsonl` in the case directory with time, OS user and whether the session was token-authenticated. The access log is local and unsigned: it evidences use, not identity. `reviewer_ui.reveal_on_request: false` removes the button; `show_sensitive_evidence` and `show_raw_model_io` open them by default under approved information-handling policy. Trace download stays governed by `allow_trace_download`. Production mode and pilot configurations require `reviewer_ui.access_token_env`; this local shared secret is not a substitute for enterprise authentication or tenant isolation.

Each obligation shows how its source was approved. An evaluation-fixture source is labelled as not governance-approved so it never reads like an approved one.

The new page is the programme workflow. The older Watcher and broader Streamlit workbench retain their prior configuration. No new regulator feeds or autonomous remediation deployment are enabled by this package.

## 3. What statuses mean

| Status | Meaning and next action |
|---|---|
| ACTION_REQUIRED / EvidenceRequest | Supply the exact scoped records described; missing data is not a proven breach |
| ACTION_REQUIRED / AuthorizationRequest | An existing trusted person/policy must authorize the stated boundary |
| ACTION_REQUIRED / ServiceRequest | Inspect model/service or schema failure and its retained receipt |
| ACTION_REQUIRED / IntegrityRequest | Stop and investigate signatures, anchors, tampering or concurrent execution; do not delete ledgers to clear the error |
| QUALITY_GATE_BLOCKED | Stages may be present but a material investigation/quality requirement remains unsatisfied |
| EVALUATION_COMPLETE | Evaluation-mode software workflow complete; production qualification remains blocked |
| COMPLETE | Integrated investigation finalizable; inspect verdict and explicit result-decision request |
| CURRENT GovernanceResult | Human-approved signed assessment result is current; this does not grant deployment |
| REVIEW_REQUIRED | Bound input/configuration changed; preserve old result and create an authorized successor investigation |

Authorization/Integrity requests mark `retry_safe: false`; resolve and review the boundary first. Recovery never changes the meaning of an already signed stage. The download button exports the status report; signed records remain in the governed store.

## 4. One-time administrator configuration

Start from `ge_repo/config/programme_operations.json`. Paths are relative to the directory containing that configuration, unless absolute. Default mode is evaluation; empty identities/sources and placeholder model names intentionally block operation.

An authorized administrator supplies:

- `models`: examine, explain, plan, challenge transport/provider/base_url/model, immutable `model_revision` or `model_sha256`, and budgets. Local Ollama/OpenAI-compatible services are supported. Remote transfer requires explicit HTTPS approval; credentials use environment variables. Production qualification requires the challenger and examiner to have different provider/base/model/revision identities. Different names alone do not prove genuinely independent training or correlated-error control.
- `trusted_keys`: real actor, actor_type, public_key and approved roles. No fixture identities may represent a real person. Challenger actor/key must be separate from assessor.
- `signers`: key_id and `private_key_env` or `private_key_file` for approved roles. Key files must belong to the operator and be mode 600, not symlinks. Do not include private seeds in the distribution.
- `store`, `programme_dir`, `receipt_dir`: governed local storage locations.
- `sources`: verified exact snapshots and signed authority decisions. Consultation/internal adoption remains distinct from binding regulatory force.
- `collectors`: exact root/path/hash, source identity, system/version/period, authority, provenance and evidence segments. Negative evidence may be admitted.
- Optional `http_collectors`: normalized JSON export URL, allowed_hosts, source_id, evidence_id, element_ids, optional expected_sha256 and bearer_token_env. Executor policy `allow_readonly_collectors` is required. Read-only GET, no redirects, 20 MB limit. Configure only authorized endpoints.
- `precedent_snapshot`: `{path, sha256}` of a governance-approved corpus for the current framework/control. Its signed payload includes `status: APPROVED`, framework, control_id, and `records`. Each record needs precedent_id, source_ref, system_id, period, lesson, limitations. An approved empty records list means the defined corpus was searched and had no entries; no configured source means NOT_EVALUATED.
- Assessor policy: `require_dependency_review: true` and `require_integrated_gate: true` before creating the investigation.
- Planner policy `required_tools_by_control`: CHANGE.MGMT or M3.12 requires `["change_authorization","2"]` and `["change_population","1"]`; M3.6 requires the four m36_* version-1 procedures listed in the implementation design.
- Decision policy: `allow_auto_block: true` only if an authorized automatic deployment hold is intended. It cannot accept risk or authorize deployment.
- Optional action assignment: trusted `action_owner`, executor `allow_action_assignment`, `action_owners[control_id]`, and `closure_tools_by_control[control_id]`.
- Production qualification: independently signed qualification_report and approved quality_policy. See EVALUATION_DESIGN.md. Production remains blocked without this.

Change trust after signed records exist → explicit migration/new revision is required. Preserve the old trust policy with its records. Do not change a source or model under an existing qualification and expect it to remain valid.

## 5. Approve source and initialize scope once

`tools/gaar_authorize.py` uses existing trusted HUMAN owner/governance keys. It neither generates human approvals nor substitutes service identities. Its help shows exact parameters:

```bash
cd ge_repo
.venv/bin/python tools/gaar_authorize.py --help
```

For official sources, configure the snapshot, retrieval receipt, source hash/version/authority, approved_by and authority_decision_ref first. Use the `approve-source` action with the exact source ID in `--confirm` and `--source-id`.

Internal policy sources use `issuer: INTERNAL`, `authority: internal`, exact snapshot/hash/version and signed governance approval. They cannot be promoted to binding regulation. No fabricated MAS URL is needed for an internal change policy.

Prepare an owner-reviewed bundle containing `context` and `expectations`, using the schemas in SCHEMAS. Use `start --bundle` with the exact investigation ID in `--confirm`. This validates the pair, appends the first two signed stages, and saves the initial head. It currently initializes real investigations only; offline tests create their own explicitly labeled fixtures. Subsequent Run handles the machine stages automatically.

Initial source/owner authorization is an intentional human boundary, not a recurring interstage transfer. Production still requires enterprise identity provisioning.

### Evaluation-only quick provisioner

For a demonstration without fabricating people or regulatory authority, `tools/gaar_provision.py` creates a new configuration, eight distinct service keypairs, an internal fixture requirement, one whole-file UTF-8 evidence segment, a scoped empty precedent search and the signed owner/expectations stages. It never overwrites an existing output, refuses production mode, marks all identities as services and marks the context synthetic.

```bash
cd ge_repo
.venv/bin/python tools/gaar_provision.py \
  --output-config config/my_evaluation.json \
  --evidence /absolute/path/change_export.json \
  --investigation-id EVAL-CHANGE-001 \
  --system-id credit-platform --version v1 \
  --period 2026-09-20T00:00:00+08:00 \
  --framework INTERNAL --control CHANGE.MGMT \
  --requirement-version internal-v1 \
  --requirement "Internal change authorization requirement" \
  --element-id e1 \
  --element "Observed changes must match prior authorization" \
  --confirm-evaluation-only
```

Then launch, choose option 2, select `config/my_evaluation.json`, choose actual running models and save `EVAL-CHANGE-001`. The provisioner accepts only UTF-8 text/JSON/CSV and admits the whole file. It intentionally refuses PDF extraction: proposed PDF slices still require a separate reviewed segmenter before WB146 can be claimed.

### Pilot on-ramp: bring your own keys

`tools/gaar_pilot.py` is for real exports reviewed by real people. It differs from the evaluation provisioner in where human identities come from: it never creates one.

```bash
cd ge_repo
.venv/bin/python tools/gaar_pilot.py keygen --out ~/.gaar/owner.key
.venv/bin/python tools/gaar_pilot.py keygen --out ~/.gaar/reviewer.key
.venv/bin/python tools/gaar_pilot.py provision \
  --output-config ~/gaar-pilot/operations.json \
  --investigation-id CHG-2026-09-001 --confirm CHG-2026-09-001 \
  --system-id credit-platform --version 2.3 --period 2026-09-20T00:00:00+08:00 \
  --framework INTERNAL --control CHANGE.MGMT \
  --requirement-version change-policy-v4 --policy /path/change_policy.md --policy-version v4 \
  --element "chg.1=Every production change is authorised before execution" \
  --element "chg.2=The change population reconciles to an independent source" \
  --evidence CHANGES=/path/change_export.json --evidence POPULATION=/path/population_export.json \
  --owner-key ~/.gaar/owner.key --owner-name "Owner Name" \
  --governance-key ~/.gaar/owner.key --governance-name "Owner Name" \
  --approver-key ~/.gaar/reviewer.key --approver-name "Reviewer Name" \
  --examine-model <model> --explain-model <model> --plan-model <model> --challenge-model <different model>
.venv/bin/python tools/gaar_pilot.py verify --config ~/gaar-pilot/operations.json
```

Human key files must already exist, be owner-only (chmod 600), and sit outside both the pilot configuration directory and this package. The owner key signs scope; the governance key signs the internal source, the obligations and the precedent corpus (an empty approved corpus is an attestation that there are no precedents to consult). Service keys for assessor, planner, executor, challenger, decision and sealer are generated inside the pilot workspace. `separation_of_duties` records whether owner, governance and approver are distinct people; `SINGLE_REVIEWER_PILOT` is shown as a warning in the app.

A pilot runs in evaluation mode, so the integrated gate always carries `production_judgment_not_qualified` and sealing is impossible. The reviewer app therefore offers **Attest this pilot result**: the same preflight as sealing with that one blocker tolerated, the same head binding and verdict-to-decision mapping, signed by the human approver, recorded as a `pilot_attestation` journal event with `reliance: PILOT_DECISION_SUPPORT` and `governance_result: false` inside the signed payload. Result sealing refuses any approval carrying those markers, so an attestation cannot be promoted into a governance result.

## 6. Evidence needed for change management

Use actual observed execution/audit events, approved request scope and timestamps, implementer identity, privileged credential grants, target systems, implementation content fingerprints, freeze windows/timezones and approved exceptions, emergency/incident references, failure outcomes and recovery records. Reconcile observed event IDs against a separately collected population. Logs must be scoped to the same system and time period.

Two different source names do not prove independent collection. A self-asserted complete flag does not prove collector completeness. Validate collector boundaries and clocks separately. Missing ticket/approval/log records cause assurance gaps; do not reinterpret them as proof that no authorization existed.

M3.6 requires model-specific validation and operating evidence. Asset/change checks do not establish M3.6 compliance. No regulatory authority determination is supplied here.

## 7. Human conclusion and signed result

If automatic hold is not authorized, the runner requests a decision. Optional `conclusion_decisions[investigation_id]` points to a human `decision` envelope binding investigation_id, input_head (current challenge head), and the complete `conclusion` schema. Its signer must match the configured human decision identity. Deployment requests are rejected by this programme.

A qualified finalizable real investigation then requests a separate signed result approval. `result_decisions[investigation_id]` points to an envelope signed by an independent human `result_approver`. Payload: investigation_id, investigation_head, decision, decision_id, at (timezone-aware timestamp), rationale. ADVERSE requires FAIL. INCONCLUSIVE additionally requires `assurance_only_fail: true` and FAIL. A configured `result_sealer` signs the resulting GovernanceResult. In production the reviewer app's **Sign and seal** panel (`governance/decisions.py`) runs every precondition first, signs with the approver key through the existing secrets boundary, writes the envelope without overwriting, registers it and seals. Run again also seals a pre-registered decision without redoing machine stages.

Every envelope is `{payload, key_id, signature}` over the canonical JSON payload using the existing CanonicalSigner. These are integration contracts for your authorized approval mechanism, not blank signatures supplied by this package.

Passing conclusions are not generated automatically. Human approval does not override contradictory operating evidence or incomplete gates. Result sealing does not authorize deployment.

## 8. Terminal administration

From `ge_repo`, show all actions:

```bash
.venv/bin/python tools/gaar_programme.py --help
.venv/bin/python tools/gaar_programme.py check
.venv/bin/python tools/gaar_programme.py evaluate
```

`run` needs `--investigation-id` (your existing authorized ID); `--config` selects another approved configuration. Prefer the saved console or page for daily operation.

`check-changes` takes the investigation ID and compares configured local bound files/configuration. It can append REVIEW_REQUIRED and a reassessment request. This is also checked on resume. It is not an installed background scheduler or general live Watcher poll.

`backup` needs investigation ID and a new `--destination` ZIP. It takes the run lock and writes signed hashes of the core journal, operational journal/anchor, available results/state log, receipts, retained HTTP evidence blobs and report. Original source archives, credentials, model files and external anchors need separate governed backup.

`restore-verify` takes `--archive` and a new empty `--destination`. It checks archive paths, member budget, manifest signature, exact hashes and retained journal heads before reporting VERIFIED_IN_NEW_DIRECTORY. It does not replace production files or prove service failover.

`close-action` needs investigation ID, `--action-id` and `--approval`. Approval must be signed by the assigned human owner and bind action_id, action_event_hash, verification_investigation_id, verification_head and test_ids. The new verification must match the real system/control/framework and required closure procedures. Selected executed tests must have no findings/gaps and an executor independent of the owner. This does not send an external notification.

## 9. Test and recovery operations

Install development test requirements in your isolated environment when needed, then use the existing offline regression runner. The delivered verification logs record the environment used for this build; they are not your Mac acceptance results.

```bash
.venv/bin/python -m pip install pytest pytest-timeout
WB_WEB_KNOWLEDGE=off .venv/bin/python tools/wb141_offline_regression.py -q --timeout=20 tests/test_wb143_149_programme.py
```

The complete suite also needs the full historical requirements.txt. Core installation alone does not install every optional app/test dependency. Tests use isolated synthetic fixtures and do not prove a live assessor's judgment.

After interruption, use Run on the SAME assessment/configuration. For altered evidence, policy or knowledge, create a new authorized revision. For integrity errors, preserve files and investigate; never delete the anchor or rewrite the database to force success.

## 10. What remains before production assurance

Provide real authorized identities and source decisions, scoped real exports/connectors, a live model service, independent held-out corpus and quality approval, target macOS operation, complete source/collection validation, external rollback anchors, enterprise action delivery, scheduled reassessment/supersession, security/key-revocation/failover exercises and the release authority's acceptance.

The programme is intentionally unable to certify itself. Engineering checks can proceed automatically; missing institutional authority and independent evidence cannot be manufactured.
