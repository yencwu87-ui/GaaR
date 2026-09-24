# Deep inspection — live governance hardening + Colibri integration

## Scope

This pass inspected the production Python tree, the P0/P1 governance path, the existing P2 retrieval/capability measurement surfaces, the Streamlit challenge integration, the inference policy, provider telemetry, and the Colibri transport boundary.

## What is now wired

```text
app.py
  ├─ Challenge my reading ───────────────→ core.cycle.challenge_read()
  └─ Challenge the disagreement ─────────→ core.cycle.challenge()
                                             ↓
                                      challenge.py
                                             ↓
                                      inference.policy
                                             ↓
                         ┌───────────────────┴──────────────────┐
                         │                                      │
                      Ollama                                  Colibri
                  routine/default                    difficult challenge work
                         │                                      │
                         └───────────────────┬──────────────────┘
                                             ↓
                                  deterministic validators
                                             ↓
                                  governed challenge envelope
                                             ↓
                                      human decision
```

Provider/model selection is now part of the inference plan and is recorded in `governance/inference_tasks.jsonl`.

## P0 / P1 closures

- Live `cycle.challenge()` is the only production disagreement-challenge entrypoint.
- The UI no longer directly constructs the disagreement challenge.
- The first challenge button is also routed through `core.cycle.challenge_read()` rather than bypassing the cycle service.
- Decision-time freshness is enforced in `core.cycle.decide()`.
- Challenge transport retry/fallback planning is now actually visible when the fallback flag is enabled; the old ordering built the second plan before the fallback flag was set.
- The cycle layer no longer wraps challenge calls in a second legacy Ollama context, preventing Colibri executions from being mislabeled as Ollama and preventing duplicate transport telemetry.

## Colibri policy

When `WB_COLIBRI_ENABLED=1`:

- routine challenge work stays on Ollama;
- reviewer/assessor disagreement, high-risk challenge, and critical challenge work route to Colibri;
- `WB_CHALLENGE_FALLBACK_PROVIDER` can route a failed challenge to the other provider;
- deterministic output validation remains unchanged after transport selection;
- provider/model are recorded with the inference task.

The default Colibri endpoint is `http://127.0.0.1:8000/v1` and the default model id is `glm-5.2-colibri`.

## Verification

### Passed in this deep-inspection pass

- 156 governance-critical/regression tests across the focused suites.
- `python -m compileall -q .` — PASS.
- Governance stress harness — `13 PASS / 0 FAIL / 1 OPEN / 0 UNKNOWN`.
- Colibri route tests cover:
  - policy routing,
  - explicit provider override,
  - Ollama → Colibri fallback,
  - Colibri → Ollama fallback,
  - OpenAI-compatible response parsing,
  - malformed-response rejection,
  - provider/model telemetry.

### The remaining OPEN

`baseline_hard_gate` remains OPEN because the existing stress harness expects a named baseline-gate implementation and the repository does not yet contain one. This is separate from the P0/P1 live governance path and Colibri integration.

### What could not be fully certified in this container

The container has no running Ollama or Colibri service, so real-model HTTP execution was not performed here. The new `tools/check_llm_services.py` provides the readiness check to perform on the machine where the two services are running.

The repository contains 828 collected tests. The entire suite was not completed in this environment because the container lacks the pinned Streamlit runtime and cannot reach the package index to install it, and some legacy test batches exceeded the execution window. The governance-critical surface above was run directly and passed.

## Release readiness statement

The **live governance path is hardened and Colibri is genuinely wired as a provider**, not as a second UI shortcut. The remaining uncertainty is environmental (real service reachability) plus the pre-existing named baseline-gate OPEN; those should not be represented as passed in the evidence record.
