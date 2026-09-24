# GaaR WB142 — full operation manual

## 1. Start here: one launcher

Extract the ZIP into a new folder. Open **Start_GaaR.command**. On first use it creates a private project Python environment and installs the three core software packages. It then opens a numbered console. Python 3 must already be installed; first installation needs internet access. The launcher does not start or download a model.

If macOS does not open the file, open Terminal, type `bash ` (including the space), drag `Start_GaaR.command` from Finder into Terminal, then press Enter. This avoids guessing a directory or typing a filename as an installed command. Do not disable macOS security checks or run it with sudo.

Keep your previous installation separate. This is a complete checkpoint, not a folder to copy blindly over WB136. Existing trust policies, evidence and ledgers need deliberate migration.

| Console option | What it does | Human touchpoint |
|---|---|---|
| 1 Check readiness | Checks actual configured model endpoints, identities, sources and dependency catalogue; saves a report | None |
| 2 One-time setup / model selection | Remembers config path and investigation ID; discovers running local Ollama/OpenAI-compatible services and lets you select models | Confirm intended routing |
| 3 Run investigation | Advances machine stages using the selected configuration and signed investigation | Stops at evidence, trust, source, policy or decision boundaries |
| 4 Explore change-control dependencies | Shows what to examine, evidence needed and alternatives | None; informational |
| 5 Evaluate four agent stages | Runs the approved held-out evaluation manifest and retains results | Independent labels and later semantic review required |
| 6 Open full operation manual | Opens MANUAL.html in your browser | None |
| 7 Start existing workbench UI | Installs the full app requirements, then starts Streamlit on localhost:8501 | Existing application gates remain active |
| 0 Exit | Leaves stored preferences and records intact | None |

The console is the WB142 investigation entry point. The existing Streamlit assessment interface is retained; it does not automatically import every investigation. Starting its server does not turn every optional Watcher or autonomous feature on. Those features keep their own approved configuration. This package does not bypass their approvals or add new Watcher feeds.

## 2. First-run outcomes

The packaged configuration is deliberately unconfigured. A normal first check says BLOCKED, lists missing identities and source approvals, and may say the model service is unavailable. It does not generate a successful assessment from demo data.

Software libraries are different from control dependencies. The launcher installs pydantic (record validation), cryptography (signatures) and PyYAML (configuration). The dependency catalogue is already bundled and automatically used by investigation explanation and challenge. It contains proposed internal knowledge, not approved regulatory interpretations.

A machine-stage failure is saved as a checkpoint, not hidden behind a green completion badge. Read its report before retrying.

## 3. One-time setup: routing and credentials

Start your already installed model service. Option 2 probes localhost ports 11434 and 8000. It lists the actual reported models; you select routing separately for examination, explanation, planning and challenge. Press Enter to preserve an existing selection. If no service responds, nothing is invented or silently selected.

The model name is not a trust identity. The challenger must have a different trusted actor and signing key from the assessor. Using a different model alone does not establish independence. Using one base model for both roles also requires explicit consideration of correlated errors in evaluation.

Setup stores the config path and investigation ID in `ge_repo/config/wb142_console.json`. Model choices are saved in the chosen configuration with a one-time backup. It does not change source authority, trust roles, signed policy or deployment permissions. Readiness checks are not inference-quality tests.

Signing keys can be supplied by existing environment variables or owner-only files. This avoids repeating shell exports when double-clicking the launcher. For each configured signer use `key_id` with either `private_key_env` or `private_key_file`. Relative key-file paths resolve against the configuration directory. File contents are a base64 Ed25519 private seed supplied by your authorized credential administrator. A private-key file must belong to your OS user, have no group/other access (normally chmod 600), and must not be a final symlink. Do not put private keys into the checkpoint or knowledge catalogue.

The environment-variable value takes priority when present. Private-key files provide local persistence, not hardware-backed key management. Remote API authentication currently uses the configured api_key_env; remote evidence transfer still needs explicit HTTPS approval.

## 4. Administrator setup: what cannot be guessed

An authorized administrator supplies the following once per approved assessment configuration. These are decisions and evidence inputs, not toggle switches.

| Configuration | Required content |
|---|---|
| store | Path to the investigation journal |
| trusted_keys | Key ID, actor, actor_type, public_key and authorized roles; preserve the exact signed-policy version |
| signers | owner, governance, assessor, test_planner, executor, challenger, decision: trusted key ID and credential location |
| assessor policy | require_dependency_review: true for the WB142 production route |
| test-planner policy | Explicit required_tools_by_control; M3.6 must include all four registered M3.6 tool/version pairs |
| decision policy | allow_auto_block only when genuinely authorized; this permits a deployment hold, not risk acceptance |
| sources | Exact official snapshots, retrieval receipts, source version and signed authority decisions |
| collectors | Approved directories/files, byte hashes, system/version/period scope, provenance and exact source slices |
| expected_heads | Externally retained current hash for each signed investigation |
| models | Actual provider, endpoint, model, budgets and any authorized remote-transfer settings |
| receipt_dir | Restricted storage for prompts/responses and signatures |
| stage_evaluation_manifest | Independently approved held-out corpus for all four agent stages |

Use the concrete configuration-field reference in `ge_repo/WB141_OPERATIONS.md` alongside these WB142 additions. Do not alter a trust policy already hashed into a journal. Introduce a reviewed policy revision and new investigation or explicit migration. A missing policy is not fixed by setting an environment variable to disable the gate.

## 5. Regulatory snapshots and authority

From Terminal inside ge_repo, the existing source-fetch command is:

```bash
.venv/bin/python tools/gaar_operate.py --config config/wb142_operations.json fetch-sources
```

It fetches configured candidates into quarantine and records failures. The packaged candidate URLs include indexes and a consultation; they are not automatically applicable requirements. A maintenance page or JavaScript shell is not a regulatory publication, even when HTTP returns success. Replace candidates with actual applicable publications and inspect content before approval.

Populate a registry entry with source_id, issuer, url, sha256, version, authority, snapshot_path, retrieval_receipt, approved_by and authority_decision_ref. Authority is explicit: binding, guidance, consultation or internal. Internal adoption does not turn a consultation into binding law.

After an authorized human has reviewed the exact version and configured their trusted governance signer, this command signs that source decision. Replace the example IDs with your actual reviewed source ID:

```bash
.venv/bin/python tools/gaar_authorize.py --config config/wb142_operations.json --confirm YOUR_SOURCE_ID approve-source --source-id YOUR_SOURCE_ID
```

This is an authorization action, not routine setup. It validates bytes and the retrieval receipt, requires the configured human signer to match approved_by, and refuses to overwrite an existing decision file. No production source approval was created while preparing this package.

## 6. Scope and initial investigation authorization

Prepare a JSON bundle with two keys: context and expectations. They use the unchanged WB140 InvestigationContext and ApplicableExpectations models in `governance/investigation/contracts.py`.

Context requires investigation_id, framework, control_id, requirement_version, scope(system_id, version, period), boundary, owner, criticality and synthetic=false. Expectations require requirement_version and a nonempty elements list. Each expectation carries element_id, text, exact source ID/hash/version, authority, purpose(design/operating/outcome), applies and applicability_reason.

The scope must describe one system/version and a defined assessment period. Do not mix evidence across systems to complete a checklist. Source and owner decisions must already be reviewed. Then authorize the initial pair:

```bash
.venv/bin/python tools/gaar_authorize.py --config config/wb142_operations.json --confirm YOUR_INVESTIGATION_ID start --bundle reviewed_investigation.json
```

The command uses the existing trusted human owner and governance keys. It validates the pair in a temporary journal before appending it, refuses an existing investigation ID, and stores the initial expected head. Retain a copy of that head and trust policy outside the mutable application data. A crash between journal writes can leave an incomplete initial record; do not bypass append-only controls to repair it. Review the partial state and create a new authorized investigation if needed.

## 7. Operating evidence and collectors

A collector reads a specific file within an approved root. It does not scan the entire laptop or guess which document proves an obligation. Configure root, path, source_id, sha256, scope, authority, provenance and segments. Segment offsets are Unicode character offsets in decoded UTF-8 text; hashes bind the original file bytes and extracted slice bytes. PDF/HTML extraction needs its own governed transformation receipt before supplying UTF-8 evidence.

A segment includes evidence_id, start, end, element_ids, purposes and finding_status. A policy and an approval log in one file may be admitted as different slices. Gap or adverse evidence is admissible when properly scoped and trustworthy. Admission does not mean the control passed.

For change management, supply observed changes as well as tickets. The comparison needs actual credential use, privilege grants, approvals, freeze windows/exceptions, incidents and recovery records. A ticket-only comparison cannot reveal changes that never had a ticket. Empty exports and unavailable collection are different conditions.

For M3.6, the four supplied-record JSON formats are documented in WB141_OPERATIONS.md. They recompute selected metrics and check records. They do not prove source authenticity, all model risks, validator competence, or all 14 governed elements. No blanket coverage claim is made.

## 8. Daily operation

After configuration and initial authorizations, choose **3 Run investigation**. There are no separate buttons for examine, explain, plan, execute or challenge. The bounded runner progresses through available machine stages and stops at the first genuine boundary.

| Checkpoint | Meaning and next action |
|---|---|
| PRODUCTION_CONFIGURATION_REQUIRED | Readiness checks failed; inspect model, identity and source reasons |
| OWNER_AND_EXPECTATIONS_REQUIRED | Initial signed context/expectations are absent; authorized owners must establish them |
| EXTERNAL_HEAD_REQUIRED | No retained journal head is configured |
| APPROVED_DEPENDENCY_REVIEW_POLICY_REQUIRED | Assessor policy does not require dependency review; a reviewed policy revision/new investigation is needed |
| APPROVED_M36_TEST_POLICY_REQUIRED | Required M3.6 procedures are not approved in the test-planner policy |
| INVESTIGATION_UNAVAILABLE | A machine stage failed; inspect the exception, signed inference receipt and last accepted stage |
| AUTHORIZED_DISPOSITION_REQUIRED | Machine stages completed but no authorized disposition is available |
| QUALITY_GATE_BLOCKED | Record exists but finalization requirements remain unsatisfied |
| COMPLETE | Investigation stages completed and gate is finalizable; read verdict and deployment flag separately |

Signed receipts contain evidence-bearing prompts and responses. RESPONSE_RECEIVED means text was returned, not that its reasoning was correct or accepted. A schema error does not become a stage success.

The console prints and saves the new journal head. An authorized operator must retain it externally and update expected_heads before a later resume; the console does not silently trust whichever head it finds on disk. This remains a manual integrity touchpoint. Future automatic anchoring requires a separately approved external anchor service.

A finalizable adverse or inconclusive report can still block deployment. Automatic hold policies do not accept risk. Positive deployment authorization and CURRENT GovernanceResult sealing still use the existing authorized governance workflow; the console does not manufacture these decisions or automatically bind every legacy review cycle.

## 9. Dependency knowledge operation

The catalogue is always retrieved during explanation and independent challenge. Search is exact-framework, bounded, upstream and downstream; it does not silently map generic controls into MAS. The INTERNAL control IDs are investigative topics, not regulatory control identifiers. MAS edges remain proposed interpretations pending expert mapping review.

Each relationship specifies scope conditions, evidence needed, plausible alternatives, a disproof question, proposed executable comparisons where available, escalation conditions and what cannot be inferred. The agent receives these as hypotheses. It must ground its applied dependencies in admitted evidence or explicit gaps.

The explanation retrieval record retains the catalogue content hash. If knowledge changes before finalization, the gate blocks until reviewed re-investigation. Preserve the original knowledge snapshot with historical records. A graph search finding nothing does not establish comprehensive coverage. The current implementation does not force a separate disposition for every suggested catalogue edge; that remains a judgment-evaluation question.

Do not edit catalogue JSON merely to make a result green. Proposed changes require provenance, expert review, versioning, a new content hash and regression checks. The implementation does not auto-promote PROPOSED edges to approved legal obligations.

## 10. Evaluation

Option 5 runs the four-stage evaluation runner when stage_evaluation_manifest is configured. Without one, it returns NOT_EVALUATED. It does not substitute unit tests or demo fixtures for independent audit judgments.

Read EVALUATION_DESIGN.md for corpus construction, labels, stage rubrics, semantic review, failure rules and release evidence. The runner uses actual configured models and saves signed responses. Objective metrics do not issue production authorization.

## 11. Troubleshooting

| Symptom | Action |
|---|---|
| command not found: Start_GaaR.command | Use bash followed by the file's path, or open the file from Finder |
| No such file: /absolute/... | Replace placeholder paths with real files; Setup accepts your actual config path |
| ModuleNotFoundError | Use the launcher/project .venv; do not run the script in an unrelated conda environment |
| Connection refused | Start the local inference service; this does not indicate a model-quality failure |
| Model not loaded | Use Setup to select a model actually reported by the service |
| Source unavailable | Preserve the failed check; fetch the exact publication later or use an approved alternate acquisition path |
| Untrusted signer / missing private credential | Have the authorized administrator configure matching public keys/roles and the approved credential location |
| Key file permissions rejected | Set owner-only permissions and use a regular file; do not print secrets into logs |
| Source authority mismatch | Correct the reviewed version/authority binding; never relabel a draft as binding to bypass the gate |
| Head mismatch | Stop and investigate state rollback, a different journal, or an unretained legitimate append |
| Empty evidence / incomplete collection | Supply the missing scoped export or conclude an assurance gap; do not fabricate a passing record |
| First installation fails | Keep the error; verify Python and network/package availability; no completed run is claimed |

## 12. Backup and rollback

Back up config, trust-policy versions, approved source snapshots, authority decisions, journals, external heads, evidence exports and signed receipts. Keep private keys in your approved credential store rather than the shareable archive. Stop the application before copying SQLite state, or use SQLite's backup API. Validate copied hashes and signatures before using a backup.

This ZIP does not migrate your Mac's live ledgers. To return to the prior checkpoint, launch that separate installation with its own data and trust configuration. Do not splice new ledger stages into an old database or change pinned policy hashes.

## 13. What this package does not prove

Live audit judgment, macOS execution, source applicability, independent validation quality, complete dependency coverage, production evidence collection and operational deployment readiness remain unverified here. The verification report records precisely which software tests were run. A one-launch interface reduces repetitive setup; it cannot replace legitimate governance decisions.
