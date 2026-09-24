# Local LLM service runbook — Ollama + Colibri

This workbench now has two governed local inference transports:

- **Ollama** — normal/default local path for routine assessment work and routine challenge work.
- **Colibri** — optional deeper challenge provider. When enabled, disagreement/high-risk/critical challenge tasks route to Colibri; the inference plan records the provider and model.

The governance engine, not the UI, chooses the route. A provider failure is a transport failure; it never becomes a governance verdict.

## 1. Start Ollama

Open Terminal A and start the Ollama service:

```bash
ollama serve
```

If the Ollama desktop application is already running, `ollama serve` may report that the port is already in use; that is normally fine.

In Terminal A or another shell, make sure the required models exist:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
ollama list
```

The workbench defaults to `llama3.1:8b` and `nomic-embed-text`.

## 2. Start Colibri

Colibri exposes an OpenAI-compatible API through `coli serve`. The documented local API base is `http://127.0.0.1:8000/v1`, with `POST /v1/chat/completions` and `GET /health`. The exact model directory depends on the Colibri installation and model you downloaded.

Open Terminal B in the Colibri `c/` directory and run:

```bash
export COLI_MODEL=/path/to/your/colibri-model
export COLI_API_KEY=local-secret
./coli serve \
  --host 127.0.0.1 \
  --port 8000 \
  --model-id glm-5.2-colibri
```

Leave Terminal B running. The `COLI_API_KEY` line is optional for a purely local server, but setting it makes the local boundary explicit.

Verify Colibri before connecting the workbench:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"glm-5.2-colibri","messages":[{"role":"user","content":"Reply with OK"}],"stream":false}'
```

## 3. Configure the governance engine

Open Terminal C in the governance workbench directory:

```bash
export OLLAMA_MODEL=llama3.1:8b
export WB_COLIBRI_ENABLED=1
export COLIBRI_BASE_URL=http://127.0.0.1:8000/v1
export COLIBRI_MODEL=glm-5.2-colibri
export COLIBRI_API_KEY=local-secret
```

For the normal governed policy, this means:

```text
routine assessment              → Ollama
routine challenge               → Ollama
reviewer/assessor disagreement  → Colibri
high-risk challenge             → Colibri
critical challenge              → Colibri
```

The route is still explicit and overridable. For example, to force the disagreement challenger back to Ollama for a diagnostic run:

```bash
export WB_PROVIDER_CHALLENGE_DISAGREEMENT=ollama
```

## 4. Configure transport fallback

The stronger path can also fail safely to the other provider without changing the decision logic.

For Colibri primary → Ollama fallback:

```bash
export WB_CHALLENGE_FALLBACK_PROVIDER=ollama
```

For Ollama primary → Colibri fallback:

```bash
unset WB_COLIBRI_ENABLED
export WB_CHALLENGE_FALLBACK_PROVIDER=colibri
```

A fallback is recorded as an escalated inference task with the actual provider/model. It does not alter the human decision or make a failed transport look successful.

## 5. Check both services

Before starting the UI:

```bash
python tools/check_llm_services.py
```

You want both service health checks and the configured model names to report ready.

## 6. Start the workbench

```bash
streamlit run app.py
```

Then exercise the workflow in this order:

```text
Evidence
  ↓
Reviewer blind read
  ↓
AI assessment released
  ↓
Compare
  ↓
Challenge
  ↓
Disagreement challenge
  ↓
Human decision
```

For a control with an actual reviewer/AI disagreement, the disagreement challenge should show Colibri as the selected provider when `WB_COLIBRI_ENABLED=1`.

## 7. Operational evidence

The inference task ledger is written to:

```text
governance/inference_tasks.jsonl
```

Look for records such as:

```json
{"role":"challenge_disagreement","provider":"colibri","model":"glm-5.2-colibri","escalated":false}
```

or a fallback sequence where the final task record shows `provider: "ollama"` with `escalated: true`.

LLM call timing and failure telemetry is also written to:

```text
governance/llm_metrics.jsonl
```

## 8. Stop the services

When finished:

```text
Terminal C: Ctrl+C          # Streamlit
Terminal B: Ctrl+C          # Colibri
Terminal A: Ctrl+C          # Ollama, only if you started ollama serve manually
```

Do not expose either service beyond localhost unless you have deliberately configured authentication and network controls.

## Reviewer Copilot

Copilot runs through the same governed inference policy as the assessor/challenger. It has its own role and may be configured independently:

```bash
export WB_MODEL_COPILOT=llama3.2
```

When `WB_COLIBRI_ENABLED=1`, structural/runtime complexity may route Copilot to Colibrì. Provider/model selection is recorded in the Copilot event ledger.

Copilot is only available after the reviewer has saved an initial reading. Its response cannot contain sufficiency, maturity, element verdicts, or final decision fields; rejected overreach is logged rather than silently filtered.
