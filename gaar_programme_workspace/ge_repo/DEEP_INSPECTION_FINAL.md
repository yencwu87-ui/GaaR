# Final Deep Inspection — Governance Complexity + Colibri Routing

## Scope

This round independently pressure-tested the structural complexity classifier, boundary thresholds, provider routing semantics, canonical workbook controls, decision/freshness hardening, challenge integration, and telemetry projection.

## Findings resolved in this round

### 1. Complexity thresholds are now explicitly tested

The classifier is tested at the exact signal boundaries:

- 7 / 8 / 11 / 12 control elements
- 4 / 5 declared artefacts
- 899 / 900 requirement characters
- score 0 / 1 / 2 / 3 / 4 band boundaries

The current score maximum is **4**, not 5, with the present weights:

- many control elements = +2
- many expected artefacts = +1
- long governed requirement = +1

Therefore:

- 0 → routine
- 1 → complex
- 2 → complex
- 3 → critical
- 4 → critical

These are tested mechanics, not evidence that the thresholds are empirically calibrated. Threshold calibration remains a policy/data exercise and should be revisited once live routing telemetry exists.

### 2. Control complexity is separated from overall task complexity

The implementation now distinguishes:

- `control_complexity_score/band/reasons`: deterministic structural complexity of the governed control
- `complexity_score/band/reasons`: aggregate task complexity after runtime signals such as ambiguity, disagreement, prior failures, evidence volume and risk are added

Provider routing uses the canonical control band derived from the control score, rather than a second raw `score > 0` test. Runtime difficulty can still escalate a routine control independently.

This prevents the structural control decision and the aggregate inference tier from being conflated.

### 3. The actual production control objects are tested

The test loads the real workbook through `playbook.load_controls()` rather than using only a synthetic stand-in.

For MAS:

- **M3.6**: 14 governed elements and 14 derived artefacts → score 3 → `critical` → Colibri when enabled
- **M1.2**: 0 governed elements and 1 artefact → score 0 → `routine` → Ollama

The classifier also accepts canonical dict-shaped contracts defensively, while the live assessor/challenger path uses the workbook `Control` object that carries the overlay elements.

### 4. Challenge/assessor telemetry now records both dimensions

The inference record and challenge projection include both:

- aggregate task complexity
- structural control complexity

This makes a later audit able to answer both:

> Why was this task expensive?

and:

> Was the control itself classified as complex/critical?

## Verification

Focused governance-critical regression surface:

**123 passed**

Static governance stress gate:

**13 PASS / 0 FAIL / 1 OPEN / 0 UNKNOWN**

The single OPEN is `baseline_hard_gate`. A semantic baseline manifest exists, but the repository does not yet contain the named hard-fail baseline gate implementation expected by the stress harness.

The separate full stress runner was not used as a release gate because its optional external hotspots require unavailable dependencies (`garak` and `promptfoo`) and hotspot execution can exceed the local execution window. That is an environment limitation, not a reported failure in the governance routing changes.

## Remaining risks

1. **Baseline hard gate** — the manifest exists, but there is no named hard-fail implementation. This means semantic drift can be detected/recorded by existing tooling, but there is not yet a repository-level hard stop that prevents release after an unapproved baseline change.

2. **Live provider HTTP** — Ollama and Colibri transport behavior still requires one live run on the user's Mac. Controlled transport tests cover selection, parsing, fallback and telemetry, but cannot prove a real server response without the user's services running.

3. **Threshold calibration** — the boundary tests prevent accidental changes to the current policy, but they do not prove that `8/12/5/900` are the optimal governance thresholds. Those should be calibrated from observed workload telemetry rather than changed speculatively.

## Release conclusion

The specific gap raised in this review — deterministic control-complexity classification and provider routing — is implemented with explicit boundary tests, exercised against the real workbook controls, separated from aggregate runtime difficulty, and represented in telemetry.

The bundle is ready for the **live Ollama + Colibri integration test on the user's Mac**, with the baseline hard gate still explicitly open rather than represented as passed.
