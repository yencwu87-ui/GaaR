# WB145 judgment evaluation and qualification

## Separate the three questions

1. Does the software enforce the investigation contract? Offline integration, signature, replay, scope, recovery and negative tests answer this.
2. Does a live model produce correct, useful, appropriately uncertain judgments? Independently labeled held-out cases and semantic review answer this.
3. Can intended users safely operate the complete service in the target environment? Production acceptance exercises answer this.

Software tests in this package establish only the first. Scripted fixtures are labeled as such. No live model quality score or auditor baseline was measured.

## Full-contract runner

`governance.production.evaluation.evaluate` uses the same EvidenceExamination, ExplanationSet, TestPlan and ChallengeRecord schemas as production. Each case contains a frozen `production_prompt`. The evaluator adds the actual response schema, calls the configured live transport, retains signed receipts and validates the response. Expected labels and assertions remain outside the model prompt.

A human `judgment_evaluator` signs a manifest containing `frozen_at`, `development_input_hashes`, and cases. All 16 stage/category cells must exist: examine/explain/plan/challenge × violation/legitimate_exception/contradiction/insufficient_evidence. Case IDs and file hashes must be unique; development overlap and changed files are rejected.

Each case entry has `case_id`, `stage`, `category`, `path`, `sha256`, nonempty `assertions`, and `independent_expected_judgment`. Each assertion has a unique `id`, a JSON-path component list `path`, `operator` (`equals`, `contains`, `absent`), optional `value`, and `critical` boolean. Case file format is exactly `{"production_prompt": {...}}`.

Predicates measure structural facts such as correct missing-evidence status or absence of an unsupported assertion. They are not claim-level precision/recall and do not establish semantic correctness. The runner reports semantic review PENDING and release authorization false. Reviewers must assess whether the frozen prompts represent actual runtime context.

## Independent labels and auditor comparison

Keep the corpus outside development prompts and test fixtures. Independent experts label facts, warranted conclusions, legitimate exceptions, unresolved uncertainty, material dependencies, best next tests and invalid conclusions. Record disagreements and adjudication. Use equivalent information and time budgets for a qualified human auditor baseline. Include blinded cases, adversarial evidence, prompt injection, contradictory timestamps, emergency changes, wrong-scope approvals, absent logs, misleading equal counts, and evidence that refutes the initial hypothesis.

Measure per stage and risk category: material finding recall, warranted-claim precision, unsupported conclusion rate, evidence attribution correctness, uncertainty calibration, useful alternative explanations, decision-impact test choice, challenge discovery rate, unavailable/abstention rate, cost and latency. Report denominators, confidence intervals and failures. Do not pool rare catastrophic errors into an attractive average.

Critical failures include fabricated authority/approval/execution, cross-system satisfaction, invented citations, unsupported operational breach, material risk suppressed, proposed test claimed executed, and deployment authorization outside mandate.

## Qualification artifact

Production mode requires an independent human `quality_approver` envelope: `payload`, `key_id`, `signature` over canonical payload. It binds the current code/knowledge/model/trust/operating-scope/policy fingerprint; `valid_until`; `decision: APPROVED`; `semantic_review: APPROVED`; `semantic_review_ref`; and the hashed `held_out_manifest`, `evaluation_results`, `semantic_review_artifact` files (`path`, `sha256`). Include signed live receipt file references for all four stages.

`metrics[stage][category]` contains integer `case_count`, `unavailable_count`, `critical_failures`, and finite `precision`, `recall`. Values are independently approved semantic measurements; the application validates their signature and limits, not the truth of the human labels. The runner does not manufacture this approval or calculate semantic precision from lexical checks.

The supplied template suggests at least 10 cases per cell and precision/recall thresholds of 0.95. These are editable proposed release settings, not scientifically established sufficiency or regulatory requirements. The responsible authority must approve a risk-based sample design, critical-failure policy and thresholds. Zero observed errors does not prove zero future errors. Model aliases also require operational version pinning outside this configuration hash.

Change code, prompts, knowledge, models, trust or relevant scope/policy → qualification no longer matches → production stops until requalified. A new evidence configuration may consequently require new qualification in this deliberately strict candidate.

Production qualification also requires immutable revision/hash fields for examination and challenge and rejects an identical provider/base/model/revision identity for both roles. This reduces direct self-challenge but does not prove independence of training data, model family or failure modes; the independent evaluation corpus must measure correlated errors.

## Required production proof not supplied

Independent corpus and labels; live full-contract outputs; independent semantic scoring and signed approval; auditor baseline; robustness and privacy evaluation; target-environment user acceptance. These remain blocking tasks rather than simulated successes.
