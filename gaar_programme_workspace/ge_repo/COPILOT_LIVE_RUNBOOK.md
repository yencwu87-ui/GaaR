# Reviewer Copilot V1 — Mac live verification

This runbook is intentionally falsifiable. Do not accept a scenario because the UI looks normal; inspect the raw event sequence and `governance/inference_tasks.jsonl`.

## 0. Clean probe namespace

```bash
grep -c 'LIVE-COP-' governance/inference_tasks.jsonl || true
grep -c 'LIVE-COP-' governance/llm_metrics.jsonl || true
```

For a clean run, the first command should be `0` (or the file should not exist yet).

## 1. Start the real providers

Ollama:

```bash
ollama serve
```

Colibrì in another terminal, using the local configuration you already validated:

```bash
cd /path/to/colibri/c
./coli serve --host 127.0.0.1 --port 8000 --model-id glm-5.2-colibri
```

Verify:

```bash
curl http://127.0.0.1:11434/api/tags
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/models
```

## 2. Set Copilot routing

```bash
export WB_MODEL_COPILOT=llama3.2
export WB_COLIBRI_ENABLED=1
export COLIBRI_BASE_URL=http://127.0.0.1:8000/v1
export COLIBRI_MODEL=glm-5.2-colibri
```

The normal Copilot role must be allowed to select its own plan. Do not infer provider choice from `WB_MODEL_COPILOT` alone; the ledger plan fields are authoritative for the executed task.

## 3. Scenario A — reference only

```bash
python tools/live_copilot_probe.py --control M1.2 --scenario reference
```

Expected:

```text
copilot_requested
copilot_presented
copilot_reference
```

No reviewer rating changes.

Inspect the raw task record for the request ID and verify:

```text
provider
model
control_complexity_band
task_complexity_band
task_id
completed=true
```

Also verify the response keys are exactly the frozen schema:

```text
relevant_evidence
requirement_context
evidence_gaps
questions
rationale_draft
```

No `sufficiency`, `maturity`, `verdict`, or final-decision field may appear.

## 4. Scenario B — rating change after Copilot

```bash
python tools/live_copilot_probe.py --control M3.6 --scenario revise
```

Expected:

```text
copilot_requested
copilot_presented
copilot_revision

decided.copilot_influence.rating_changed_after_copilot = true
```

The `decided` event MUST contain before/after evidence of the review revision but MUST NOT state that Copilot caused the change.

## 5. Scenario C — live schema rejection

This deliberately asks the real model to emit a prohibited field. It is an isolated probe and is not allowed to mutate the authoritative reviewer reading.

```bash
python tools/live_copilot_probe.py --control M1.2 --scenario malformed
```

Expected:

```text
copilot_rejected
no copilot_presented
reviewer read unchanged
```

The rejection payload should contain the prohibited-field reason, for example:

```text
prohibited_judgement_field:maturity
```

If the real model refuses the adversarial request instead of emitting the field, classify this scenario as **untested**, not as a schema-rejection PASS. The normal transport still succeeded, but the specific rejection branch did not execute.

## 6. Scenario D — degraded Ollama

Use the simple/routine M1.2 control and deliberately point Copilot at a model that is not installed:

```bash
export WB_MODEL_COPILOT=__definitely_missing__
python tools/live_copilot_probe.py --control M1.2 --scenario fail
```

Expected:

```text
copilot_requested
copilot_rejected
no copilot_presented
reviewer_read_unchanged = true
```

An error event is correct. A half-populated Copilot presentation or reviewer-state mutation is not.

Restore:

```bash
export WB_MODEL_COPILOT=llama3.2
```

## 7. Assessor vs Copilot provenance

For the same control, do not require different bands or providers. Those may legitimately match.

Require instead:

```text
assessor task_id != copilot task_id
```

and verify both tasks have independently recorded:

```text
control_complexity_band
task_complexity_band
provider
model
```

The acceptance criterion is two independently identifiable inference tasks, not different outcomes.

## 8. After-run extraction

Paste the raw JSON objects for:

```bash
grep 'LIVE-COP-' governance/inference_tasks.jsonl
grep 'LIVE-COP-' governance/llm_metrics.jsonl
```

and the complete cycle event sequence printed by the probe. For the revise scenario, also paste the `decided` event's full `copilot_influence` object.

Do not paraphrase absent fields as `false`. An absent field is a different finding.

## 9. Semantic baseline warning

Copilot output, even if fluent and useful, does not close or substitute for the existing semantic `baseline_hard_gate` OPEN item. A successful Copilot run therefore does not change the baseline-gate status.


## Verification semantics added for the final V1 probe

- `review_id` is the cycle ID. The same ID is emitted on the Copilot inference task and the
  Assessor/LLM telemetry when Scenario B runs the real Assessor first.
- Scenario D distinguishes a blocked primary request from `fallback_succeeded`. A successful
  Copilot response after the intentionally missing Ollama model is NOT a Scenario-D pass; the
  probe returns exit code 2 and prints the provider/model actually used.
- Scenario C prints the raw model response when available. A clean model refusal is `UNTESTED`; a
  schema rejection must identify the production validator reason. Free-text rating/maturity text in
  an otherwise allowed field is separately visible in the raw response and is not silently upgraded
  to a schema-field rejection.
- Every scenario prints `LIVE_COP_TASK_COUNT` with before/after counts for its exact task ID.


### Provider-isolation precondition for Scenario D

Before Scenario D, clear any direct Copilot provider override so the missing Ollama model really tests
the intended primary route:

```bash
unset WB_PROVIDER_COPILOT
unset WB_CHALLENGE_PROVIDER
export WB_DEFAULT_PROVIDER=ollama
export WB_MODEL_COPILOT=__definitely_missing__
```

The probe reports the computed primary provider/model. If it reports anything other than `ollama` before
the missing-model request, Scenario D is an environment/configuration issue, not a transport result.

### Scenario B correlation

Scenario B runs the real Assessor and Copilot on one review cycle. The cycle ID is emitted as `review_id`
on both inference-task records. The Assessor and Copilot task IDs must differ; matching control/task bands
or even matching provider/model are allowed when independently computed.
