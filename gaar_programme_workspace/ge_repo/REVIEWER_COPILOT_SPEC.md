# Reviewer Copilot — Build Specification

## Purpose

Reviewer Copilot is constrained assistance available **after** an immutable initial reviewer reading has been recorded. It does not become an alternative source of authority and it does not make governance decisions.

```text
Reviewer initial reading
        ↓
immutable event snapshot
        ↓
Reviewer Copilot
        ↓
optional assistance
        ↓
reviewer may revise any reading field
        ↓
final reviewer decision
```

## Enforcement invariants

1. Copilot cannot be requested until a reviewer `read` event exists.
2. The first `read` event is the immutable initial baseline. Later reads are revisions; history is never overwritten.
3. The Copilot model is **not given the reviewer's reading**. It receives the governed control contract and evidence only.
4. The Copilot response schema has no fields for sufficiency, maturity, element verdicts, final decisions, approvals, dispositions, or an authoritative deciding rule.
5. Unknown fields and prohibited judgement fields are rejected and logged. They are never silently filtered.
6. Suggestions are rendered separately from authoritative reviewer fields and are never auto-inserted.
7. `used as reference` is reviewer-declared only. The system does not infer reliance from dwell time, scrolling, focus, keystrokes, or other behavioural telemetry.
8. Rating/rationale/element changes after Copilot exposure are recorded as `copilot_influence`; this does not claim Copilot caused the change.
9. The existing `revised` field remains separate: it describes whether the final decision differs from the current reviewer reading.
10. AI Assessor and Copilot are independent inference tasks with separate task IDs, provider/model metadata, and outputs.

## Response schema

```json
{
  "relevant_evidence": [{"locator": "", "excerpt": "", "relevance": ""}],
  "requirement_context": [{"element_id": "", "text": "", "note": ""}],
  "evidence_gaps": [""],
  "questions": [""],
  "rationale_draft": ""
}
```

## Telemetry

Each Copilot lifecycle is append-only in `governance/events.jsonl` using:

```text
copilot_requested
copilot_presented
copilot_rejected
copilot_reference
copilot_revision
```

The presented event records provider/model, control complexity band, aggregate task band, task id, response schema, and inference telemetry.

The decision payload also carries `copilot_influence` so an incident review can determine whether structured judgement, rationale, or element judgements changed after Copilot exposure.

## Element judgement change

A governed element judgement is the entire authoritative structured record for one element, excluding its identifier. A change is recorded if any element is added, removed, or any authoritative field under that element differs.

Presentation-only UI state is not an element judgement change.

## Interpretation limits

```text
Copilot exposure ≠ Copilot reliance
Similarity ≠ copying
Post-Copilot change ≠ AI-caused change
```

Telemetry records observable sequence and state changes. It does not infer human cognition, reliance, intent, or causality.

## Live verification

For a live run, inspect `LIVE-PROBE-*` or normal cycle entries for:

- `control_complexity_band`
- `task_complexity_band`
- `provider`
- `model`
- `copilot_influence`
- explicit fallback/escalation metadata

M1.2 should remain routine and use Ollama under the default Colibrì-enabled policy. M3.6 on the workbook `playbook.Control` path is expected to be critical and use Colibrì when enabled.
