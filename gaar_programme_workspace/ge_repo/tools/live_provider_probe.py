#!/usr/bin/env python3
"""Live provider-routing probe for the governance engine.

This intentionally exercises the real inference transports, not test doubles.
It loads canonical workbook Control objects so the structural-complexity decision is the same
shape used by the assessor. Each probe is recorded with a unique LIVE-PROBE-* task id.

Example:
    WB_COLIBRI_ENABLED=1 \
    COLIBRI_BASE_URL=http://127.0.0.1:8000/v1 \
    COLIBRI_MODEL=glm-5.2-colibri \
    python tools/live_provider_probe.py --controls M1.2 M3.6
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inference import run_with_escalation, signals_for_control  # noqa: E402
from inference.policy import control_complexity  # noqa: E402
from playbook import load_controls  # noqa: E402

WORKBOOK = ROOT / "AI_Governance_Playbook_MGF_SAFR_v0.5.2_requirement_elements_audited.xlsx"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--controls", nargs="+", default=["M1.2", "M3.6"])
    args = ap.parse_args()

    controls = {c.id: c for c in load_controls(WORKBOOK)["MAS"]}
    missing = [cid for cid in args.controls if cid not in controls]
    if missing:
        print(f"missing controls: {', '.join(missing)}", file=sys.stderr)
        return 2

    print("LIVE PROVIDER ROUTING PROBE")
    print("=" * 72)
    print(f"Ollama model: {os.environ.get('OLLAMA_MODEL', '<assessor default>')}")
    print(f"Colibri enabled: {os.environ.get('WB_COLIBRI_ENABLED', '0')}")
    print(f"Colibri model: {os.environ.get('COLIBRI_MODEL', 'glm-5.2-colibri')}")
    print()

    failures = 0
    for cid in args.controls:
        control = controls[cid]
        profile = control_complexity(control)
        signals = signals_for_control(control, role="assess", evidence_chars=120)
        task_id = f"LIVE-PROBE-{cid}"
        print(f"{cid}: control_band={profile['band']} score={profile['score']} -> invoking real provider")
        try:
            raw, plan, rec = run_with_escalation(
                role="assess",
                system="You are a connectivity probe. Reply with exactly: OK",
                user=f"Live provider probe for governed control {cid}.",
                signals=signals,
                control_id=cid,
                task_id=task_id,
            )
        except Exception as exc:
            failures += 1
            print(f"  FAIL provider call: {type(exc).__name__}: {exc}")
            continue

        print(f"  provider={plan.provider}")
        print(f"  model={plan.model}")
        print(f"  control_complexity_band={plan.control_complexity_band}")
        print(f"  task_tier={plan.tier}")
        print(f"  task_complexity_band={plan.complexity_band}")
        print(f"  calls={rec['calls']} escalated={rec['escalated']} completed={rec['completed']}")
        print(f"  control_reasons={rec['control_complexity_reasons']}")
        print(f"  task_reasons={rec['complexity_reasons']}")
        print(f"  response={raw.strip()[:120]!r}")
        print("  ledger_task_id=", rec["task_id"])
        print()

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
