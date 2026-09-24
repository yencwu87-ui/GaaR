# WB-115 Agent / Skill Role Map

## Agent now

**Review Conductor** is the only agentic role in WB-115. It needs persistent workflow state,
sequencing, retries and tool invocation. It may advance machine-owned nodes but it cannot synthesize
human reads or final governance decisions.

## Bounded skills (not agents)

- Evidence Examiner — deterministic evidence preflight.
- Assessor — existing governed assessment skill.
- Reviewer Copilot — bounded reviewer assistance.
- Challenger / Falsifier — existing governed adversarial skill.
- Challenge Copilot — bounded explanation after admitted challenge.
- Control Narrative Copilot — evidence-anchored narrative with explicit limitations.
- Provenance Auditor — deterministic result/seal/state verification.
- Quality Auditor — WB-115 preflight only; WB-116 will turn this into the full Governance Result Quality Gate.

## Candidate agents later

- **Regulatory Change Watcher** — persistent monitoring and iterative source/tool use.
- **Evidence Scout** — iterative evidence retrieval/freshness/tool use under source policy.

## Not an agent

**Colibrì** remains a deep-reasoning provider. The governed router selects when it is used and the
Review Conductor may invoke a skill that routes to it. Colibrì gains reasoning depth, not governance authority.
