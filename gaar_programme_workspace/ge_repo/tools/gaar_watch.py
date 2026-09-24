#!/usr/bin/env python3
"""Regulatory watch: subscribed intel on regulator publications and exploited vulnerabilities.

    python tools/gaar_watch.py setup [--regions sg,us,uk,hk,cn,global]   subscribe and run the first check now
    python tools/gaar_watch.py status                     each source: OK / FAILING / OVERDUE / NEVER_CHECKED
    python tools/gaar_watch.py feed [--all]               what's new (untriaged P1/P2 by default)
    python tools/gaar_watch.py outlook                    labelled forecast: trends, controls likely to need reassessment
    python tools/gaar_watch.py run [--force]              check every subscribed source that is due
    python tools/gaar_watch.py subscribe --source mas-circulars-index      (unsubscribe likewise)
    python tools/gaar_watch.py triage --item <id> --decision RELEVANT --by "Your Name"
    python tools/gaar_watch.py capture --source mas-circulars-index --file ~/Downloads/Circulars.html --by "Your Name"
                                                          a page you saved from your own browser, read as that scan

The scheduler (tools/gaar_scheduler.py) runs `run` on every tick; each source is checked every 8 hours by default
(interval_minutes in ~/gaar-watch/subscriptions.yaml). State lives in ~/gaar-watch (or GAAR_WATCH_HOME).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.watcher import intel  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    su = sub.add_parser("setup")
    su.add_argument("--regions", default="sg,global", help="comma-separated: sg, us, uk, hk, cn, global")
    sub.add_parser("status")
    sub.add_parser("outlook")
    f = sub.add_parser("feed")
    f.add_argument("--all", action="store_true", help="every item, including triaged and P3")
    r = sub.add_parser("run")
    r.add_argument("--force", action="store_true", help="check every subscribed source now, due or not")
    for name in ("subscribe", "unsubscribe"):
        s = sub.add_parser(name)
        s.add_argument("--source", required=True)
        s.add_argument("--by", default="")
    ca = sub.add_parser("capture", help="read a page you saved from your own browser as that index's scan")
    ca.add_argument("--source", required=True)
    ca.add_argument("--file", required=True)
    ca.add_argument("--by", required=True)
    pr = sub.add_parser("propose", help="draft a new control from a watch item (never live until promoted)")
    pr.add_argument("--item", required=True)
    pr.add_argument("--by", required=True)
    t = sub.add_parser("triage")
    t.add_argument("--item", required=True)
    t.add_argument("--decision", required=True, choices=intel.TRIAGE)
    t.add_argument("--by", required=True)
    t.add_argument("--note", default="")
    args = parser.parse_args()

    if args.command == "setup":
        intel.subscriptions()
        subs = intel.subscribe_regions([r.strip() for r in args.regions.split(",") if r.strip()], by="setup")
        result = intel.run_due(force=True)
        out = {"status": "WATCH_READY", "home": str(intel.home_path()), "interval_hours": subs["interval_minutes"] / 60,
               "subscribed": subs["sources"], "first_check": result["scanned"],
               "next": "the scheduler checks each source when due; see `status` and the inbox"}
    elif args.command == "status":
        out = intel.health()
    elif args.command == "outlook":
        out = intel.outlook()
    elif args.command == "feed":
        found = intel.items() if args.all else intel.needs_triage()
        out = [{k: i.get(k) for k in ("item_id", "priority", "kind", "title", "url", "first_seen", "matched_controls",
                                      "forecast", "triage", "members") if i.get(k) is not None} for i in found]
    elif args.command == "run":
        out = intel.run_due(force=args.force)
    elif args.command == "capture":
        out = intel.capture(args.source, args.file, args.by)
        out = {k: out[k] for k in ("source_id", "status", "coverage", "captured_by", "captured_file")} | {
            "links": len(out["inventory"]), "new": len(out["new"])}
    elif args.command == "propose":
        out = intel.propose_control(args.item, args.by)
    elif args.command in ("subscribe", "unsubscribe"):
        out = intel.set_subscribed(args.source, args.command == "subscribe", by=args.by)
    else:
        if args.item.startswith("digest:"):
            out = {"triaged": intel.triage_digest(args.item.split(":", 1)[1], args.decision, args.by, args.note)}
        else:
            out = intel.triage(args.item, args.decision, args.by, args.note)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
