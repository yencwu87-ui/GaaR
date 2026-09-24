#!/usr/bin/env python3
"""Gate-status report — generated, never hand-edited, verifiable (quality policy §2).

    python tools/gaar_gate_status.py generate [--config ~/gaar-recurring-demo/operations.json] [--as-of 2026-10-01T09:00:00+08:00]
    python tools/gaar_gate_status.py verify --report reports/gate_status-<time>.json

`generate` writes a JSON report (the record) and a Markdown rendering of it, both under reports/. `verify` checks
the report's own content hash, then regenerates it from the inputs its derivation receipt names, as of the
report's moment, and says whether the result is identical.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.production import gate_status  # noqa: E402


def generate(args):
    report = gate_status.generate(args.config, args.as_of)
    out = Path(args.out).expanduser() if args.out else ROOT / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = report["derivation_receipt"]["generated_at"].replace(":", "").replace("+", "_")
    target = out / f"gate_status-{stamp}.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    target.with_suffix(".md").write_text(gate_status.render_markdown(report))
    return {"status": "GATE_STATUS_GENERATED", "report": str(target), "rendering": str(target.with_suffix(".md")),
            "as_of": report["as_of"], "gates": {g["gate"]: g["state"] for g in report["gates"]}}


def verify(args):
    report = json.loads(Path(args.report).expanduser().read_text())
    return gate_status.verify(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--config", help="a series workspace, for the per-series gates")
    g.add_argument("--as-of", help="status at a past moment, derived from what had happened by then")
    g.add_argument("--out", help="output folder (default: reports/)")
    g.set_defaults(func=generate)
    v = sub.add_parser("verify")
    v.add_argument("--report", required=True)
    v.set_defaults(func=verify)
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))
    if args.command == "verify" and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
