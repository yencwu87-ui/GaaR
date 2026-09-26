#!/usr/bin/env python3
"""Field agents (GaaR Part 2): evidence collected from the systems under an approved collection mandate.

    python tools/gaar_field.py status   --config ~/gaar-field-demo/operations.json
    python tools/gaar_field.py approve  --config ... --by "Your Name"      approve the mandate as it stands (pins its hash)
    python tools/gaar_field.py collect  --config ... [--as-of ISO]         collect now (the scheduler does this every tick)
    python tools/gaar_field.py demo-env --config ...                       constructed bank systems for a demo series

The mandate is <series root>/field/mandate.yaml. The agents read only what it names, never write to a source, never
replace delivered evidence, and deliver nothing partial: a source they cannot read is an evidence gap in the inbox.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.field import builder, demo, mandate  # noqa: E402
from governance.operations.runtime import load  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "approve", "collect", "demo-env"):
        s = sub.add_parser(name)
        s.add_argument("--config", required=True)
        if name == "approve":
            s.add_argument("--by", required=True)
            s.add_argument("--note", default="")
        if name == "collect":
            s.add_argument("--as-of", help="simulated clock, for a constructed demonstration series only")
    args = parser.parse_args()
    config, root = load(Path(args.config).expanduser())
    if args.command == "approve":
        out = mandate.approve(root, args.by, args.note)
    elif args.command == "demo-env":
        out = demo.build_environment(config, root)
    elif args.command == "collect":
        now = datetime.fromisoformat(args.as_of) if args.as_of else None
        from governance.production import recurring
        if now and not recurring.verify(config, root).get("constructed_demo"):
            raise ValueError("a simulated clock is for constructed demonstrations only")
        out = builder.run(config, root, now=now)
    else:
        try:
            m, approval = mandate.load_approved(root)
            state = {"mandate": m["mandate_id"], "owner": m["owner"], "approved_by": approval["approved_by"],
                     "approved_at": approval["at"], "sources": [f"{s['source_id']} ({s['connector']}, {s['role']})"
                                                               for s in m["sources"]]}
        except ValueError as exc:
            state = {"mandate": "NOT_READY", "reason": str(exc)}
        rows = [r for r in builder.ledger(root).read()]
        state["deliveries"] = [r["payload"]["period"] for r in rows if r["record_type"] == "FieldDelivery"]
        state["open_gaps"] = [g for r in rows[-5:] if r["record_type"] == "FieldGap" for g in r["payload"]["gaps"]]
        out = state
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
