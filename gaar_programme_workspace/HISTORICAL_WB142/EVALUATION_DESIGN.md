# GaaR WB142 — evaluation design and acceptance plan

## 1. What must be proved separately

Software integrity, control-procedure correctness, live-model availability, judgment quality and operational authorization are separate gates. Passing one cannot stand in for another. The existing synthetic acceptance tests establish bounded contract behavior, not experienced-auditor judgment. This design does not claim a foolproof system or superiority to auditors.

Two evaluation tracks are required:

1. **Implemented structured track:** independently labeled candidate-selection tasks for examination, explanation, planning and challenge. This measures auditable selections and status distinctions with real inference receipts.
2. **Required production-judgment track:** complete production-shaped investigations, free-response explanations, executed procedures, independent challenge and blinded expert review. Its corpus, semantic adjudication and live proof remain outstanding. The structured runner does not substitute for this track.

## 2. Corpus design

Freeze a corpus before tuning prompts, choosing a model or reading held-out results. Separate development, validation and held-out sets by underlying system, incident family, evidence source and time, not merely by filename. Include near-duplicate detection and human leakage review. The code checks exact input hashes and declared development exclusions; it does not detect all semantic leakage.

At minimum every stage must include all four categories below. Sixteen stage/category cells are a structural minimum, not sufficient statistical evidence. Independent reviewers should choose sample sizes based on target risk, error tolerances and desired confidence intervals before results are seen.

| Category | What the case must distinguish | Example case family, not a supplied gold label |
|---|---|---|
| Violation | Positive scoped evidence of failing an applicable obligation | Execution after its approval window without a valid exception |
| Legitimate exception | Evidence that a seemingly adverse observation is authorized or outside scope | Valid emergency authorization with time, scope and authority proven |
| Contradiction | Incompatible sources that cannot be silently reconciled | Ticket and independent execution logs disagree about actor or time |
| Insufficient evidence | Missing proof without inventing a breach | Ticket export provided but actual deployment collection absent |

Include clean operation, mixed failures and gaps, obsolete policies, wrong system/version, partial collectors, timezone/DST boundaries, clock skew, aliases, service accounts, approved delegation, ticket amendments, rollback versus fix-forward, denied or revoked privilege, misleading equal inventory counts, and model evidence from an unrelated release.

Evidence should include opposing sources and plausible distractors. A case must be internally coherent and have independently established scope and applicable expectations. Real de-identified cases are preferred for operational claims; any constructed case must be explicitly labeled and its inference limits retained. Do not recycle the demonstration fixtures as held-out evidence.

## 3. Independent labeling

Use at least two appropriately qualified reviewers who did not author the agent outputs. Review the evidence and governing criteria before seeing model answers. Record separate labels, supporting references, disagreements, adjudication and uncertainty. Do not force an ambiguous case into a definitive pass/fail answer.

For every case record: system/version/period, source version and authority, evidence completeness limits, applicable conditions, accepted findings, plausible alternative explanations, available discriminating tests, materiality rationale and allowed dispositions. State which facts would change the expected answer. Preserve disagreement; exclude or specially score cases without defensible adjudication.

An authorized judgment_evaluator signs the frozen manifest using a trusted identity separate from the evaluated assessor, planner and challenger. This signature attests dataset approval, not regulatory authority or model quality.

## 4. Stage-specific rubrics

| Stage | Objective checks implemented | Independent semantic assessment required |
|---|---|---|
| Examination | Required-item recall, selection precision, invented references, prohibited claims, material omissions, expected status fields | Does the cited evidence actually establish or contradict the obligation? Are design and operation distinguished? |
| Explanation | Relevant hypothesis/alternative/dependency selection, material omissions, unsupported-ID/reference counts | Is the causal account plausible? Were independent alternatives and compensating controls seriously examined? |
| Planning | Test-selection metrics, acceptable highest-impact first test, fake executed-test claims | Would the proposed test discriminate between explanations and materially change the decision? Is collection feasible and proportionate? |
| Challenge | Required disproof/finding selection, missed material issues, reference integrity, expected finding status | Does challenge independently attempt disproof, expose omissions and resist accepting an authoritative-sounding assessor answer? |

Expected status fields are in the signed rubric. This permits a missing-evidence item to require NOT_EVIDENCED rather than CONTRADICTED, or an explanation to remain a hypothesis. Facts about the actual source must determine the label; a vocabulary match alone cannot prove sound judgment.

The deterministic scorer does not inspect private model reasoning. Retain concise explanations, cited evidence, alternative hypotheses and test-selection rationale that reviewers can assess.

## 5. Manifest and case format

Set stage_evaluation_manifest in the active operations config. Its path resolves against the configuration directory. The JSON envelope has payload, key_id and signature. Sign the canonical UTF-8 JSON payload using the existing Ed25519 signer.

Payload fields:

- frozen_at: the recorded corpus-freeze time.
- development_input_hashes: all declared development-case hashes.
- cases: nonempty list; unique case IDs, unique exact input hashes; all 16 stage/category combinations present.

Each case includes case_id, stage(examine/explain/plan/challenge), category, path, sha256 and rubric. Each referenced input JSON contains exactly context, evidence, allowed_refs and candidate_items. Candidate items are objects with an id and descriptive content. They expose answer options, not the gold labels. Case paths must stay under the configuration directory; keep the corpus in a dedicated subdirectory there.

Rubric fields:

- required_ids: nonempty set of indispensable correct selections.
- acceptable_ids: optional superset including other defensible selections, avoiding penalties for legitimate alternatives.
- material_ids: subset of required_ids whose omission matters to the decision.
- prohibited_ids: selections that must not be asserted; disjoint from acceptable_ids.
- expected_fields: item ID → expected field/value pairs, such as status or execution_status.
- acceptable_first_test_ids: required for planning; independently justified highest-impact choices.

Agent output has findings for examination/challenge, hypotheses for explanation, or tests for planning. Every selected item carries id, evidence_refs and an auditable rationale; rubric-specific status fields are included where applicable. Proposed tests must not be reported as EXECUTED. The runner sends input/options but keeps category and rubric in the manifest, out of the model prompt.

This is an evaluation response interface, not a replacement for production InvestigationRecord schemas. A strong candidate-selection score still needs production-shaped evaluation.

## 6. Execution and scoring

Choose console option 5, or run:

```bash
.venv/bin/python tools/gaar_operate.py --config config/wb142_operations.json evaluate-stages
```

The runner verifies manifest signature, independent label authority, coverage, file hashes, exact duplication, declared development overlap and basic rubric consistency before inference. Each task uses the stage's actual configured model and signing identity. Signed receipts retain the request and response. Missing configuration yields NOT_EVALUATED; invalid approval/input fails before a judgment score is claimed.

Every case returns either METRICS_COMPUTED or UNAVAILABLE. Report unavailable/invalid outputs in the denominator and availability rates; do not average them away. The runner preserves per-case results rather than presenting a misleading all-purpose maturity score. It does not currently compute confidence intervals or aggregate release thresholds.

Required-item recall = selected required IDs / required IDs. Selection precision = selected acceptable IDs / all selected IDs; an empty selection scores zero. Empty required sets are rejected. Material omissions, invented references, prohibited claims, status mismatches and fabricated test execution remain explicit counts/lists. Selection precision measures annotation agreement, not the truth of free-form explanations.

## 7. Semantic review and release criteria

Blind expert reviewers to model identity and checkpoint when practical. Score grounding, scope, causal restraint, alternatives, decision-impact selection, effective challenge and uncertainty handling using a pre-agreed 0–3 rubric:

- 0: materially wrong or unsupported.
- 1: partially relevant but misses decision-critical work.
- 2: defensible with limited non-material omissions.
- 3: complete and well-grounded within the declared scope.

These are proposed evaluation scales, not regulatory requirements. Have accountable owners approve thresholds before the run. Report inter-reviewer disagreement, adjudicated results, confidence intervals and results by category/stage/control family. Compare to a frozen baseline under identical inputs and budgets. An experienced-auditor comparison requires an actual qualified reviewer baseline, comparable conditions and blind evaluation; no such comparison has been performed here.

Proposed hard review triggers include: invented evidence or authority, missing evidence promoted to pass, unexecuted tests claimed executed, unauthorized deployment, silent retrieval failure, wrong-system evidence used to satisfy an obligation, or a missed material contradiction. Do not certify a model from an average score that hides these. Materiality and release thresholds require explicit approval; the code does not invent an authorized threshold.

All runs remain PENDING_INDEPENDENT_REVIEW until semantic adjudication is recorded through the organization's approved process. The runner never authorizes release. A signed semantic-review artifact bound to model version, prompts, corpus hash, knowledge hash and run receipts is a remaining production integration requirement.

## 8. Adversarial and metamorphic testing

Verify that reordering evidence does not change deterministic results; adding an irrelevant control does not override an exact scope match; a valid freeze exception changes the relevant discrepancy only; removing collection coverage converts a clean conclusion into a gap; changing an actor/credential/target/time breaks the correct binding; swapping model versions is rejected; and changing the knowledge snapshot blocks stale finalization.

Include prompt-injection text inside evidence, unsupported regulator claims, conflicting trusted and untrusted documents, unavailable tools and insufficient budgets. Agents must treat document text as data and preserve failure states. Safety tests should be read-only and operate on approved test environments.

## 9. Reproducibility

Retain code/archive manifest, Python environment, tool version/hash, input bytes and hashes, policy/trust version, knowledge snapshot hash, prompts, actual model identifier, configuration/budgets, raw responses, receipt signatures, accepted record heads and adjudication. Deterministic procedure replay means recomputing the same comparison from the same inputs and implementation. Re-running inference is not guaranteed byte-for-byte identical even with temperature zero.

## 10. Exit artifacts and honest status

To close operational acceptance, produce actual live receipts for all stages; held-out and semantic evaluation; approved applicable sources; real scoped operating evidence; executable procedure records; independent challenge and dispositions; final quality-gate output; authorized result sealing and deterministic procedure replay; and an operational run through the intended user entry point.

This package supplies the design, structured evaluation code and software tests. It does not supply a fabricated independent corpus, semantic approval, live model-quality score or production certification.
