# WB140 — signed investigation contract

This checkpoint implements the eight-stage investigation contract in the existing engine, with adapters for assessment agents, admission, knowledge resolution, independent challenge, Colibri routing, the quality gate and GovernanceResult persistence. It extends WB139. No new review panel is added.

It is not a claim of a foolproof system, expert-level judgment, current regulatory compliance, or production readiness. Those claims require independent evaluation on held-out cases and live deployments. This checkpoint's model responses are scripted fixtures; deterministic checks, signatures, database operations and registered tests are real executions.

## Run the complete synthetic investigation

On macOS, open `Run_WB140_Synthetic.command` in the workspace root. It uses `ge_repo/.venv/bin/python` if available, otherwise `python3`. It needs the project's Python dependencies, including pydantic v2 and cryptography. macOS may require you to allow execution of a downloaded command file.

Or from `ge_repo`:

```bash
python tools/wb140_demo.py
```

The command runs offline, creates a new isolated signed journal each time, and prints the artifact directory. It does not change production ledgers, contact an LLM, alter assets, create a real human approval, or grant deployment permission. Fixture signing keys are ephemeral and are never included in the archive. Public verification keys are retained with the artifacts.

Expected result:

```json
{
  "assessment_finalizable": true,
  "deployment_authorized": false,
  "verdict": "ADVERSE",
  "synthetic": true
}
```

The included `eval/wb140_delivery/run-*/` directory contains completed asset and change investigations: `signed_investigation.json`, `signed_change_investigation.json`, `investigations.sqlite`, public verification configuration and result files. Paths in its configuration are portable relative paths.

## What is implemented

| Stage | Enforced contract |
|---|---|
| Understand | Signed owner context: system, version, period, boundary, criticality, control and requirement version |
| Expectations | Signed governance-stage expectations tied to exact configured source hash, version and authority |
| Examine | Every element gets an explicit status; every admitted slice is referenced; scope, hashes and evidence purpose are checked |
| Explain | Evidence/gap-grounded hypotheses, dependency references, alternatives, compensating-control review and six retrieval-lane statuses |
| Plan | Signed test plan with scoped input references, hypothesis links, decision-impact rationale, priority and required/optional status |
| Verify | Only registered read-only functions execute; input/output and implementation hashes are recorded; results are recomputed on validation |
| Challenge | Separate authorized principal and public key; challenge input contains the entire investigation through verification; required references and reviewed head are checked |
| Conclude | Signed verdict, material risk dispositions and explicit escalation decisions; adverse reporting is separate from deployment permission |

The journal uses Ed25519-signed hash-linked records and SQLite transactions. UPDATE/DELETE triggers enforce append-only use through ordinary database connections. External pinned heads detect stale/changed histories. An administrator controlling the files could replace or truncate storage: production needs separately retained checkpoints/backups, secured key custody and access control. No local file format can make a compromised host infallible.

Stage revisions start a new investigation. This avoids leaving an old challenge attached to changed evidence. The current implementation does not provide an in-place revision or automatic reassessment migration workflow.

## Evidence admission and source authority

The WB140 route is `GovernedAdmissionService.admit_investigation_source`. It verifies acquired source bytes against the supplied hash, preserves character-range slices with parent and slice hashes, and rejects cross-system/version/period scope. One document can produce separate design and operating slices. Negative evidence and gap reports remain admissible. Missing documents are represented as explicit examination gaps, not fabricated evidence records.

Purpose, authority, scope, provenance, byte integrity and finding sign are independent fields. `gap_identified` is a finding sign; it is not an integrity status. Byte integrity does not establish the source's authenticity or the truth of its contents. Classification remains an accountable assertion subject to examination and challenge.

The older `admit()` dossier adapter is preserved for migration and retains its historical lexical-completeness policy. New typed investigations use the new route. This is an explicit versioned migration, not a claim that every old caller was transparently rewritten.

No canonical M3.6 element decisions or source approvals were fabricated. The operator-provided source registry must accurately represent consultation/guidance/internal/binding authority. Adopting a draft internally does not change its external authority. The included experiment uses an explicitly internal synthetic standard.

## Resolver and dependency knowledge

`resolve_investigation` supplies expectations, facts, counterevidence, procedures and dependency candidates from the scoped record. A precedent provider can be supplied by the host; if absent, its lane remains NOT_EVALUATED and the required-lane gate blocks. A provider that completes with no hits differs from one that fails.

The dependency library includes seventeen initial MAS investigation relationships, such as inventory → materiality/security/monitoring, data suitability → evaluation, evaluation → release/monitoring, and change management → revalidation. Change management also links to privileged access, independent execution logs, release windows/freezes and incident recovery. These are explicitly internal hypotheses, not validated regulatory mappings. They require scoped evidence or a recorded gap before becoming investigation-specific dependencies. No downstream control automatically fails merely because an upstream control failed.

Traversal is bounded and cycle-safe. Agents receive both candidate relationships and the signed, scoped record. This is an initial dependency library, not an exhaustive graph for all frameworks or organizations.

The legacy resolver now exposes per-element external lookup errors. Source-registry failures become UNAVAILABLE rather than empty success; same-control precedents require matching frameworks; unrequested web retrieval is labeled NOT_EVALUATED. The WB140 investigation resolver itself does not send private evidence to web search.

## Agent and test execution

The shared service is exposed through `governance.engine`, the AI Auditor skill registry, and `governance.investigation.agents`:

- `examine`: proposes an examination while preserving admitted records byte-for-byte.
- `explain`: proposes hypotheses and dependencies; cannot overwrite resolver receipt statuses.
- `plan`: proposes a signed plan under the authorized planner identity.
- `execute_plan`: dispatches only registered implementations and records real results.
- `challenge`: receives the full record, including alternatives, plan and test results.
- `conclude_blocked_by_policy`: can automatically record a deployment hold if explicitly authorized by the trusted signing policy. It cannot automatically accept residual risk or authorize deployment.
- `run_to_checkpoint`: advances these machine stages with a bounded step count; missing approvals, provider failures and unsupported actions return an explicit checkpoint.

Configured live model calls use the existing bounded inference router. No new external service or model download is introduced. Two executable tests are registered: asset-export reconciliation and observed-change reconciliation. Unsupported tests remain UNAVAILABLE. The adapter is extensible, but other claimed tests have not been implemented.

The asset test verifies scope/time alignment, canonical identities, duplicate rows and coverage intersections. It proves facts about supplied exports, not the existence of live vulnerabilities. A verified coverage intersection can feed `broader_risk_corroborated` into the governed Colibri routing policy. Colibri is a reasoning route; escalation and risk disposition remain separate signed artifacts. The route's availability and live model quality are not established by the fixture.

The change-management test starts with actual observed change events rather than the ticket population. It reconciles ticket approval time, implementation window, approved targets/actions/content fingerprint, implementer, credential and scoped privilege grants; freeze windows and prior exceptions; incident proximity; and recovery after failure. UTC-offset-aware comparisons catch a change inside a freeze even when the records use different timezones. A ticket-free observed change is still examined. Missing or explicitly incomplete collection coverage cannot produce a comparable result.

The change fixture produces seven record discrepancies. Its corrective variant removes those discrepancies when matching records are supplied. Incident proximity remains an investigation lead. Rollback or an approved successful fix-forward can meet the fixture's recovery policy. Emergency-change authorization, timestamp accuracy, approver authority and source completeness require corroboration; a late approval is a record discrepancy to investigate, not an unconditional legal conclusion. The executable test takes supplied normalized records, not a live CMDB/PAM/SIEM connector or an automatic parser of arbitrary tickets. Claiming collection completeness in an export does not independently establish it.

## Quality and existing-cycle integration

WB140 investigation enforcement is **on by default**. Existing cycles without a signed investigation ID and pinned head will stop at INVESTIGATION_REQUIRED and cannot become CURRENT through the result-persistence path. This is an intentional compatibility change.

The quality gate uses the validated investigation's completeness and disposition result instead of a lexical coverage threshold for WB140 cases. The original reasoning, human-decision and provenance checks remain. The result compiler includes the investigation ID/head in signed provenance; persistence rejects a mismatched head or a favorable result that conflicts with an adverse/inconclusive investigation.

An adverse assessment can be finalizable. That does not grant deployment. `deployment_authorized` is a separate field. The implementation never grants deployment for synthetic, adverse or inconclusive investigations. A favorable deployment decision additionally requires an authorized human deployment role, an explicit request, and satisfactory dispositions. No deployment action is implemented.

The existing CURRENT label continues to mean the current governance assessment. It must not be consumed by downstream systems as permission to deploy. Consumers must inspect the separate deployment authorization field.

The compatibility setting `WB_INVESTIGATION_REQUIRED=0` permits unbound legacy cycles for migration/testing. It cannot disable checking for a cycle already bound to an investigation. Do not use compatibility mode to make WB140 assurance claims. The eight acceptance tests exercise enforcement enabled and the inability to downgrade bound records.

## Production configuration and migration

1. Configure trusted public keys with actor IDs, authorized roles and explicit automatic-hold policy. Keep private keys outside the repository; production key management is an operator responsibility.
2. Configure approved source IDs, hashes, versions and authority; do not reuse the synthetic source registry.
3. Set `WB_INVESTIGATION_CONFIG` to the operator-owned JSON configuration. It contains `store`, `trusted_keys` and `sources`; relative store paths resolve against the configuration's directory.
4. Obtain real signed owner context and approved expectation records. Production canonicalization and source-authority decisions remain required organizational actions.
5. Admit real scoped slices; run the shared agent service with the required read-only evidence/precedent providers and authorized signers.
6. Bind the completed record into a fresh existing review cycle using governance-context fields `investigation_id`, `investigation_head`, `requirement_version_id` and `assessment_scope` (`system_id`, `version`, `period`). Bind the same exact admitted evidence slices. The normal independent human review/decision boundaries remain.

There is no automatic backfill of old unsigned cycles. No operator keys or human approvals are generated for production. One-click synthetic operation is available; production migration is not claimed complete.

`tools/investigation_run.py --help` exposes append, execute, explain, plan, challenge, automatic hold, gate and record operations. Signing keys are read from an environment variable named by `--signing-key-env`; the CLI never takes private keys from model output or evidence. Live model actions require the configured inference service.

## Eight acceptance cases

| Case | Executed assertions |
|---|---|
| 1. Negative evidence admission | Integrity-verified negative evidence enters examination; mixed-source slices retain separate purposes; altered acquisition hashes fail |
| 2. Missing evidence cannot pass | Missing elements block a PASS conclusion; policy-only evidence cannot support an operating obligation |
| 3. Scope isolation | System, version and period mismatches are rejected |
| 4. Alternatives and dependencies | Alternatives/compensating-control review are mandatory; dependency traversal preserves hypothesis status; retrieval failure states differ; full bounded agent sequence executes with scripted model proposals |
| 5. Execution versus proposal | Proposed tests are not execution records; reconciliation actually executes; altered results fail replay; unauthorized stages and journal deletion are rejected |
| 6. Full challenge and disposition | Challenger receives all six preceding stages; omitted material evidence/tests are rejected; undispositioned material risk blocks finalization |
| 7. Adverse finalization | Signed adverse investigation finalizes with deployment false; wrong head/different evidence fails; the existing persistence gate blocks missing investigations even if the old optional gate is off; a real signed synthetic FAIL result passes through existing quality/persistence logic; corroborated coverage reaches Colibri policy signals |
| 8. Required failure visibility | Unavailable retrieval, unexamined elements and unsupported required tools each block finalization and deployment |

Run:

```bash
WB_WEB_KNOWLEDGE=off python -m pytest -q tests/test_wb140_acceptance.py
```

The included verification manifest records the actual focused test results. The full legacy suite was not run; historical pass/fail counts are not current validation. Browser verification, live model quality, real infrastructure tests, regulatory-currentness verification and independent expert benchmarking were not performed. Separate keys establish technical role separation, not proof of cognitive or organizational independence.

## Files to inspect first

- `governance/investigation/contracts.py`, `store.py`, `service.py`: types, signatures, immutable stage sequence and semantic guards.
- `governance/investigation/agents.py`, `bridge.py`: bounded agent sequence and existing-cycle enforcement.
- `governance/knowledge_resolver.py`, `retrieval_plane.py`: scoped retrieval and explicit degradation.
- `governance/quality_gate.py`, `result_integration.py`: finalization and signed investigation linkage.
- `tests/test_wb140_acceptance.py`: the eight acceptance cases.

The deliverable establishes an enforceable investigation workflow. Whether its models outperform an experienced audit lead remains an empirical question, not a property conferred by the architecture or a green fixture suite.
