#!/usr/bin/env python3
"""The one scheduler for a workspace: all machine work, each job isolated, each outcome signed.

    python tools/gaar_scheduler.py tick    --config ~/gaar-recurring-demo/operations.json [--as-of <time>]
    python tools/gaar_scheduler.py status  --config ...
    python tools/gaar_scheduler.py inbox   --config ...
    python tools/gaar_scheduler.py install --config ... [--every-minutes 60]

`tick` runs every job once. `inbox` prints what needs a person, derived from the journals. `install` writes the
launchd job com.gaar.scheduler, which replaces com.gaar.recurring: one scheduler per workspace, never two.
`--as-of` is a simulated clock for a signed constructed demonstration only, and is recorded in what it produces.
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.production import inbox, scheduler  # noqa: E402

LABEL = "com.gaar.scheduler"


def _loaded(label):
    return bool(shutil.which("launchctl")) and subprocess.run(["launchctl", "list", label],
                                                              capture_output=True).returncode == 0


def tick(args):
    when = None
    if args.as_of:
        when = datetime.fromisoformat(args.as_of)
        if when.tzinfo is None:
            raise ValueError("--as-of needs a time zone, for example 2026-10-01T09:00:00+08:00")
    try:
        result = scheduler.tick(args.config, now=when, interval_seconds=args.every_minutes * 60)
    except scheduler.SchedulerBusy as exc:
        return {"status": "SKIPPED", "reason": str(exc)}
    return {"status": result["status"], "tick": result["tick"],
            "jobs": {name: {k: v for k, v in r.items() if k in ("status", "error", "stopped_at_gate", "gates")}
                     for name, r in result["jobs"].items()}}


def status(args):
    from governance.operations.runtime import load
    config, root = load(Path(args.config).expanduser())
    health = scheduler.status(config, root)
    line = inbox.status_line(args.config)
    return {"scheduler": health["state"], "last_tick": health.get("last_tick"), "status_line": line["text"]}


def show_inbox(args):
    found = inbox.items(args.config)
    line = inbox.status_line(args.config, found=found)
    print(line["text"])
    if not found:
        print("Nothing needs you.")
    for item in found:
        flag = " OVERDUE" if item.get("overdue") else ""
        print(f"- [{item['who']}{flag}] {item['title']}")
        print(f"    {item['why']}")
        print(f"    next: {item['action']}")
        if item.get("due"):
            print(f"    due {item['due'][:16]} ({item['due_rule']})")
    return None


def install(args):
    if _loaded("com.gaar.recurring"):
        raise ValueError("com.gaar.recurring is loaded; one scheduler per workspace. Unload it first: "
                         "launchctl unload -w ~/Library/LaunchAgents/com.gaar.recurring.plist")
    config_path = Path(args.config).expanduser().resolve()
    plist = Path(args.plist_dir).expanduser() / f"{LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    log = config_path.parent / "scheduler" / "scheduler.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{sys.executable}</string><string>{Path(__file__).resolve()}</string>
    <string>tick</string><string>--config</string><string>{config_path}</string>
    <string>--every-minutes</string><string>{args.every_minutes}</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>StartInterval</key><integer>{args.every_minutes * 60}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
    return {"status": "SCHEDULE_WRITTEN", "plist": str(plist), "start": f"launchctl load -w {plist}",
            "stop": f"launchctl unload -w {plist}", "log": str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("tick", tick), ("status", status), ("inbox", show_inbox), ("install", install)):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--every-minutes", type=int, default=60)
        p.set_defaults(func=func)
        if name == "tick":
            p.add_argument("--as-of")
        if name == "install":
            p.add_argument("--plist-dir", default="~/Library/LaunchAgents")
    args = parser.parse_args()
    result = args.func(args)
    if result is not None:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
