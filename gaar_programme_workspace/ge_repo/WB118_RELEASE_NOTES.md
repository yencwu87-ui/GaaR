# WB-118 — Continuous Governance Autopilot

WB-118 turns the governed review/result loop into a continuously orchestrated control plane without granting AI governance authority.

## Added
- `governance/autopilot/policy.py`: declarative autopilot policy and environment overrides.
- `governance/autopilot/monitor.py`: typed triggers, deterministic deduplication, append-only/hash-chained trigger store.
- `governance/autopilot/scheduler.py`: append-only job history, concurrency-limited queue, projected job status.
- `governance/autopilot/loop.py`: C → D → Review Conductor orchestration for typed GovernanceChange triggers.
- `tools/autopilot_trigger.py`, `tools/autopilot_status.py`, `tools/autopilot_run.py`, `tools/live_g_autopilot_probe.py`.
- Streamlit **Autopilot** tab showing trigger/job projections, human-attention queue and active policy.

## Authority boundary
Autopilot may detect/deduplicate/queue changes, invoke C/D, and advance machine-owned Review Conductor nodes. It cannot synthesize a human read, call the final human decision on the user's behalf, or force a GovernanceResult to `CURRENT`.

## Lab validation
- New G suites: 10/10 passed.
- Critical A–G regression bundle after UI integration: 73/73 passed.
- `python -m compileall -q .`: passed.
- Broader suite progressed past the earlier critical region without a failure before the execution timeout; this is not claimed as a complete full-suite pass.

## Operational state
This is **lab-green / live-Mac validation pending**. Local validation should run the same CLI probes and then exercise one real GovernanceChange against a live CURRENT result.
