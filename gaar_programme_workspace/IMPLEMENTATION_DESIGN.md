# WB143–WB149 implementation design

## Architecture and authority

The existing eight-stage signed InvestigationRecord remains the assessment contract. New operational sidecars bind checkpoint intentions, dependency treatments, collection receipts, local actions and lifecycle events. The orchestration is a bounded local state machine; it is not eight independent autonomous agents.

`governance/production/orchestrator.py` coordinates signed context/expectations → collection → examination → explanation/retrieval → planning → allowlisted execution → dependency treatment → full-record challenge → authorized conclusion → integrated gate → optional human-approved sealing. No proposed test is converted into an executed result by a model.

The core legacy gate returns `integrated_gate_required` for programme policies. Only the integrated gate can discharge that marker after checking sidecars and qualification. Existing assessments without the signed contract do not acquire programme approval automatically.

## Code map

| Module | Responsibility |
|---|---|
| production/orchestrator.py | Single run/resume, stage intentions, recovery, initial binding, integrated gate |
| production/journal.py | Signed append-only events, local head anchor, atomic writes, per-investigation lock |
| production/requests.py | EvidenceRequest, AuthorizationRequest, ServiceRequest, IntegrityRequest |
| production/dependencies.py | Exactly one treatment per retrieved candidate; material risk and executed-test references |
| production/precedents.py | Scoped governance-approved precedent snapshot, including authenticated empty search |
| production/collectors.py | Approved local exports and bounded HTTPS GET collectors |
| production/procedures.py | Change authorization/2 and independent population comparison/1 |
| production/evaluation.py | Frozen independently approved corpus, real response schemas, hidden labels, live receipts |
| production/qualification.py | Human qualification, fingerprints, thresholds, signed receipts/artifact hashes |
| production/lifecycle.py | Human-approved GovernanceResult sealing, CURRENT → REVIEW_REQUIRED, preserved history |
| production/actions.py | Governed local assignment, notification drafts, verified closure guards |
| production/assurance.py | Readiness report, signed backup and isolated restore verification |
| tools/gaar_console.py | Outer launcher menu and saved configuration selection |
| tools/gaar_run_app.py | Local system/assessment selector and Run / resume page |
| app_gaar.py | Default reviewer front door with resolved evidence/reasoning trace |
| governance/trace.py | Read-only stage, journal and receipt verification plus reference resolution |
| tools/gaar_provision.py | Evaluation-only keys, fixture source, whole-file segment and initial signed stages |
| tools/gaar_pilot.py | Pilot on-ramp: accepts supplied human keys, mints service keys, governance-signed internal source and precedent corpus, non-synthetic initial stages |
| governance/decisions.py | Human decision step: preflight, sign and seal in production; pilot attestation in pilot profile; never mints keys |
| conftest.py | Restores shipped governance ledgers after a test session and names every ledger a test wrote |
| tools/gaar_programme.py | Noninteractive run, evaluate, check, backup, restore, change check and closure |

## Recovery design

A signed stage intention contains the full validated proposal, previous head, and proposal hash. It is durably written before the investigation stage. A separate commit records the resulting stage head. Recovery either replays the recorded proposal or recognizes an already written matching stage. It does not ask the model to replace a persisted answer. Inference can be repeated if interruption occurs before a validated intention exists; live inference itself is not deterministic.

A per-investigation OS lock rejects concurrent runs. SQLite serializes writes. Event signatures and hash chains detect mutation. A separately fsynced local anchor detects journal rollback relative to that retained anchor. It cannot detect coordinated rollback of the journal and anchor, deletion of both, or compromised OS/key custody. An independently retained anchor and governed production backups remain required.

Initial owner/expectation head is approved once. Later stage heads are tracked automatically. Changed code, models, knowledge, trust, source/collector scope or relevant policy require a new approved revision. Changed bound local evidence preserves the original record and requests reassessment.

## Dependency knowledge

The bundled WB142 catalogue contains 29 proposed relationships. Bounded traversal retrieves the candidates relevant to the assessment; the engine does not force all 29 onto every control or claim the catalogue is exhaustive.

Each retrieved edge receives exactly one treatment: INVESTIGATED, NOT_APPLICABLE, UNRESOLVED or UNAVAILABLE. Investigation requires admitted evidence plus actual executed-test references. Material treatment requires a material risk reference and explicit disposition. The challenge receives the signed treatment record; the gate binds the exact reviewed sidecar to the signed challenge.

Rules verify reference/coverage integrity. They cannot determine that a plausible rationale is true, that all real-world dependencies are catalogued, or that the chosen test actually resolves every question. Independent judgment evaluation and catalogue governance remain essential. New material explanations discovered after the explanation stage require a new investigation revision.

For change management, start from observed production changes and compare to authorized scope, actor/credential privileges, approval timing, freeze exceptions, implementation content, incident/emergency context and failed-change recovery. Reconcile a second collection population. Ticket counts alone cannot prove absence of unauthorized change.

## Evidence and test semantics

Admission verifies scope, provenance and integrity. Negative evidence is admissible. Design evidence does not silently satisfy an operating obligation. Missing approval/ticket/privilege/recovery records remain assurance gaps; supported mismatches are recorded separately. Supplied exports do not themselves establish complete discovery, authentic origin or independent collection.

Change policies must require `change_authorization/2` and `change_population/1`. M3.6 policies must require model evaluation, representativeness, independent validation and residual-risk procedures, all version 1. These procedures are implemented; real M3.6 effectiveness and source authority remain unverified.

HTTPS collectors use operator-approved URLs and host lists, GET only, no redirects, bounded responses and explicit scope checks. The model cannot select network endpoints. Collected JSON is retained by content hash. A normalized collector is an integration adapter, not a completed connector for every enterprise product.

## Decisions, results and actions

Automatic conclusion is limited to a preauthorized deployment hold. Passing conclusions require a human decision identity and supporting gate evidence. Production result sealing requires current qualified judgment, real scoped context and a signed independent human result decision. A finalizable FAIL can be CURRENT as an assessment while deployment remains blocked. An inconclusive assessment needs explicit assurance-only FAIL mapping; this does not establish operational breach.

Result signatures, human approval, dependency review and investigation head are retained. Changes append a REVIEW_REQUIRED transition and reassessment job; history is preserved. This candidate checks configured local inputs/configuration when run or explicitly polled. It does not install a continuous scheduler, automatically supersede old results with a successor, or monitor every regulator/system source.

Material findings create local actions. Assignment requires trusted owner and policy permission. Notifications are drafts only. Closure requires assigned-owner signature, a fresh real investigation, scoped independent executed verification, approved closure procedures and no remaining findings/gaps. Enterprise ticket delivery, recipient resolution, closure semantic sufficiency and service-level acceptance are outstanding production work.

## Security boundary

This is a local trusted-OS application. The page binds to localhost. There is no new multi-user authentication/tenant isolation layer, hardware key custody, automated revocation service, external anchor service or penetration-test certification. Private keys belong outside this package. Receipt/journal contents may include confidential evidence; apply governed storage and retention controls.

The result gate, replay tests and signature checks are engineering safeguards. They do not make an assessor infallible or demonstrate superiority over experienced auditors.

The reviewer trace checks the signed stage chain against the externally supplied trust policy, checks the operational journal and retained local anchor read-only, verifies inference receipt signatures and hashes, and flags unresolved references. `VALID` means those recorded bytes and identities verify; it does not mean their claims are true. `NOT_CHECKED`, `UNAVAILABLE`, `PARTIAL` and `INVALID` remain distinct.

The old workbench remains legacy option 7. The reviewer app is option 9 and the programme front door; it does not import `data/assessments.json` into the signed contract. Human decision signing inside the app is not yet implemented.
