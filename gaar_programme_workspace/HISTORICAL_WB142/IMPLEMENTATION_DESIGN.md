# WB142 implementation design

## Objective and invariants

Make the existing investigation engine investigate dependencies and counterexamples, preserve uncertainty, and give operators one repeatable entry point. Keep the eight-stage InvestigationRecord unchanged. Never infer a downstream breach from an edge, a missing document or a model assertion.

The uploaded specification is treated as user requirements and historical narrative, not evidence that earlier assertions were verified. This implementation follows its distinction between observation, explanation, executed test, consequence and disposition.

## Implemented components

| Component | Implementation | Behavior |
|---|---|---|
| Dependency knowledge | governance/investigation/dependency_knowledge.json | 29 versioned proposed relationships: 17 inherited MAS candidate mappings enriched with audit guidance, 12 explicit INTERNAL relationships |
| Bounded retrieval | governance/investigation/dependencies.py | Exact framework, incoming/outgoing traversal, depth 1–3, edge budget, duplicate validation, content hash and truncation indicators |
| Resolver integration | governance/knowledge_resolver.py | Structured candidates and version receipt alongside expectations, evidence, counterevidence, procedures and precedent status |
| Agent integration | governance/investigation/agents.py | Explanation and independent challenge receive the dependency review context |
| Engine gate | governance/investigation/service.py | Enforces policy-required dependency review and detects changed catalogue hash; retains evidence/test/disposition gates |
| Production route | governance/operations/runtime.py | Requires an approved assessor policy containing require_dependency_review before WB142 production progression |
| Operator console | tools/gaar_console.py and Start_GaaR.command | Saved settings, actual local model discovery, one-run machine progression, plain checkpoints, reports and manual |
| Persistent credentials | governance/operations/secrets.py | Operator-provided environment or owner-only credential file; no key generation |
| Explicit authorization tools | tools/gaar_authorize.py | Trusted human source approval and initial context/expectations signing; refuses overwrite or self-declared trust |
| Evaluation runner | governance/operations/stage_evaluation.py | Four-stage structured metrics with independently signed manifests and live receipts |

## Knowledge contract

Every edge has an identity/version; upstream/downstream topics; framework; relation; provenance; proposed authority/review state; applicability; evidence requirements; alternatives; disproof question; corroboration rule; proposed procedure/version and execution status; escalation condition; non-inference limit.

This is an engineering-maintained internal investigation catalogue. It does not cite invented legal sources, infer that MAS control mappings are approved, or call an engineering author an independent auditor. Registry approvals and source requirements remain separate.

Example path: inventory identity coverage → configuration coverage → reliability of configuration conclusions. The first relationship prompts reconciliation; it does not prove an insecure configuration. A second independent test must inspect actual configuration state. Similarly, missing vulnerability records do not establish unpatched vulnerabilities.

For changes, reconcile actual events to tickets, not tickets only. Verify ticket scope, actual credential, grant scope and timestamps; normalize freeze windows and exceptions; distinguish incident correlation from causal attribution; verify rollback or authorized fix-forward. An approved implementer using the wrong credential is a different question from an unapproved implementer.

## Traversal and provenance

Search includes upstream assumptions and downstream consequences. It uses no semantic similarity to invent edges. Results are deterministic for the same catalogue/framework/control/budgets. Cycles are bounded and edges are returned once. Unknown framework/topic combinations produce completed-empty search; missing/corrupt catalogues produce errors which the resolver records as UNAVAILABLE. Depth/edge boundaries are visible.

Each explanation receives a content-hash reference. The gate detects a different current catalogue and blocks finalization. Preserving the exact old catalogue supports historical replay; approved knowledge updates should create new investigation versions. The catalogue itself is not yet a separately signed steward-approval ledger.

## Judgment controls and limitations

Agents see the dependency candidates plus admitted facts and gaps. Existing schema validators require applied dependencies and explanations to reference admitted evidence/gaps; generated test proposals cannot claim execution. Independent challenge receives the complete investigation and refreshed dependency context. Material hypotheses/findings require disposition and escalation decisions before finalization.

The engine enforces these contracts. It does not prove that every relevant alternative was considered, that every catalogue edge was correctly applied, or that an apparently reasonable explanation is true. Current integration does not require a per-candidate-edge coverage matrix. Those omissions belong in expert evaluation, not in a fabricated completeness percentage.

A registered procedure is not automatically suitable for every edge. It is a proposed comparison; the plan must bind the correct scoped input. None of the four M3.6 procedures proves full M3.6 compliance. Some catalogue relationships have no registered comparison and remain visibly unavailable.

## Automation boundaries

Routine setup: private project environment, software installation, local-service discovery, stored model selection, diagnostics and report writing.

Routine machine work: scoped collection → admission → live examination → explanations → approved test plan → allowlisted execution → independent challenge → authorized automatic deployment hold where policy permits.

Authorization boundaries: source applicability/authority, trusted identities, owner scope, policy approval, risk acceptance, release authorization and external journal anchoring. These cannot be fabricated to reduce clicks. Existing Watcher feed activation and legacy-cycle bindings are not silently modified by the console.

## Remaining implementation milestones

1. Govern and independently approve the catalogue mappings; add signed steward change/review records and historical snapshot selection.
2. Add a per-candidate dependency disposition contract if evaluation shows silent omissions; do not weaken the existing schema without a migration design.
3. Implement missing substantive tests, such as actual configuration state, patch installation evidence and model-context fitness, with scoped read-only collectors.
4. Add an external anchor service for automatic journal-head retention under approved policy.
5. Integrate the console's real completed investigations into every intended legacy UI/cycle entry path; preserve human decision and result-sealing contracts.
6. Extend objective evaluation from candidate selection to production-shaped free-response agents; retain independent semantic adjudication.

These are open milestones, not claims of completed functionality. No test count substitutes for them.
