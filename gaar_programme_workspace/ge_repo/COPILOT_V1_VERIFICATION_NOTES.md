# Reviewer Copilot V1 — Verification Run Update

This build incorporates the pre-live acceptance refinements:

- Scenario A: reference-only live Copilot interaction.
- Scenario B: rating/change-after-Copilot live interaction.
- Scenario C: deliberately provoked live schema-overreach response, validated by the production Copilot schema and logged as `copilot_rejected` when the live model actually emits the prohibited field. If the model refuses the adversarial prompt instead, classify Scenario C as **untested**, not PASS.
- Scenario D: deterministic unavailable-Ollama model failure. No `copilot_presented` event or authoritative reviewer mutation is acceptable.
- Explicit `LIVE-COP-*` task IDs now flow into the governed Copilot request and inference-task ledger so the raw records can be correlated without ambiguity.
- Assessor and Copilot are accepted as independent tasks when task IDs and task records are distinct. Matching bands/providers are not treated as a failure by themselves.
- The semantic `baseline_hard_gate` OPEN item remains independent of Copilot and is not closed or substituted by Copilot output.

## Focused verification

`87 passed` across the Copilot/live-probe contract, assessor, cycle, challenge/UI boundary, complexity, and Colibrì integration surface.

This is **not** a claim of a completed real-service Mac run. The real Ollama/Colibrì proof remains external to this environment.


## Verification harness amendment

The live probe was strengthened after review to:

- distinguish primary routing from fallback success in Scenario D;
- capture and print the raw model response in Scenario C;
- report exact LIVE-COP-* task counts before and after each scenario;
- run the real Assessor and Copilot on the same review cycle for Scenario B;
- carry `review_id` onto both Assessor and Copilot inference-task records;
- preserve separate task IDs and separate routing fields for the two inference tasks.

Final focused regression result after these changes: 138 passed, 1 skipped.
The skip is the existing environment-dependent Streamlit test. No live Ollama/Colibri HTTP execution was
performed in this container.

Scenario C remains an evidence test: if the model refuses the adversarial request, classify it as UNTESTED;
only an actual prohibited response rejected by the production validator is a schema-rejection PASS.

Scenario D returns exit code 2 when a missing Ollama model nevertheless produces a Copilot response, so
operator automation cannot silently count fallback-as-success as a failure-path pass.
