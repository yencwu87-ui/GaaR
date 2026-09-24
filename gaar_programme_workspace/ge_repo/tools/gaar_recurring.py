#!/usr/bin/env python3
"""Recurring governance results.

    # sign once: a standing authorisation for a series of periods
    python tools/gaar_recurring.py authorise --constructed-demo --workspace ~/gaar-recurring-demo

    # results appear as evidence arrives
    python tools/gaar_recurring.py demo-inbox --config ~/gaar-recurring-demo/operations.json --week 1
    python tools/gaar_recurring.py tick --config ~/gaar-recurring-demo/operations.json
    python tools/gaar_recurring.py watch --config ~/gaar-recurring-demo/operations.json --every 20

    # let macOS run it for you
    python tools/gaar_recurring.py install-schedule --config ~/gaar-recurring-demo/operations.json --every-minutes 60

Humans sign the standing authorisation and attest each period's result. In
between, nothing needs a person: the scheduler runs each authorised period when
its exports land in the inbox, and records what changed since the last period.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from governance.production import recurring  # noqa: E402
from governance.investigation.store import canonical, digest  # noqa: E402

FIXTURES = {1: ROOT / "tests/fixtures/constructed_change_pack", 2: ROOT / "tests/fixtures/constructed_change_pack_week2",
            3: ROOT / "tests/fixtures/constructed_change_pack_week3"}


def _split(value, what):
    if "=" not in value:
        raise ValueError(f"{what} must be written ID=VALUE")
    key, rest = value.split("=", 1)
    return key.strip(), rest.strip()


def _load(path):
    from governance.operations.runtime import load
    return load(Path(path).expanduser())


# --------------------------------------------------------------------------
# authorise
# --------------------------------------------------------------------------

def _demo_defaults(args):
    import gaar_pilot
    from gaar_phase0 import ELEMENTS, RECONCILIATION_MAP
    keys = Path.home() / ".gaar-test-keys"
    for name in ("owner", "reviewer"):
        if not (keys / f"{name}.key").exists():
            gaar_pilot.keygen(SimpleNamespace(out=str(keys / f"{name}.key")))
    workspace = Path(args.workspace).expanduser()
    args.output_config = str(workspace / "operations.json")
    args.inbox = str(workspace / "inbox")
    args.id_prefix = args.confirm = "CHG-WEEKLY"
    args.system_id, args.version = "CONSTRUCTED-payments-api", "4.x"
    args.framework, args.control = "INTERNAL", "CHANGE.MGMT"
    args.requirement_version, args.policy_version = "constructed-cm-v1", "v1"
    args.policy = str(FIXTURES[1] / "change_policy.md")
    args.element = ELEMENTS
    args.reconcile = [f"{k}={','.join(v)}" for k, v in RECONCILIATION_MAP.items()]
    args.layout = ["CHANGES=changes.json", "POPULATION=population.json"]
    args.first_period_end, args.cadence_days, args.periods = "2026-09-15T00:00:00+08:00", 7, args.periods or 4
    args.owner_key = args.governance_key = str(keys / "owner.key")
    args.owner_name = args.governance_name = "Test Owner"
    args.approver_key, args.approver_name = str(keys / "reviewer.key"), "Test Reviewer"


def authorise(args):
    import gaar_pilot
    if args.constructed_demo:
        _demo_defaults(args)
    from governance.production import policy_approval as pa
    policy_document = None
    if args.policy_approval:
        policy_document = pa.load(args.policy_approval)
        pa.verify(policy_document)                     # genuine, and covers the policy text as it is now
    elif not args.constructed_demo:
        raise ValueError("a series on real evidence needs an approved governing policy: approve it with "
                         "tools/gaar_policy.py, then pass --policy-approval (quality policy §1, §2)")
    mapping_document = None
    if args.mapping:
        from gaar_mapping import _signed_document_path
        mapping_path = _signed_document_path(args.mapping).resolve()
        mapping_document = json.loads(mapping_path.read_text())
        if mapping_document["payload"]["control_id"] != args.control:
            raise ValueError(f"the signed mapping is for {mapping_document['payload']['control_id']}, not {args.control}")
        args.reconcile = [f"{k}={','.join(v)}" for k, v in mapping_document["payload"]["mapping"].items()]
    if args.confirm != args.id_prefix:
        raise ValueError("--confirm must repeat the exact --id-prefix you are authorising")
    periods = recurring.plan_periods(args.first_period_end, args.cadence_days, args.periods or 4, args.id_prefix)
    layout = [_split(v, "--layout") for v in args.layout or []]
    if not layout:
        raise ValueError("describe each periodic export with --layout EVIDENCE_ID=FILE_NAME")
    import hashlib as _hashlib
    mapping_for_id = {}
    for item in args.reconcile or []:
        element, codes = _split(item, "--reconcile")
        mapping_for_id[element] = [c.strip() for c in codes.split(",") if c.strip()]
    id_inputs = recurring.authorisation_id_inputs(
        prefix=args.id_prefix, control=args.control, framework=args.framework, system_id=args.system_id,
        version=args.version, requirement_version=args.requirement_version,
        periods=[p["as_of"] for p in periods], cadence_days=args.cadence_days,
        policy_sha256=_hashlib.sha256(Path(args.policy).expanduser().read_bytes()).hexdigest(),
        mapping_sha256=digest(mapping_for_id),
        mapping_document_sha256=digest(mapping_document) if mapping_document else None,
        evidence_layout=[list(_split(v, "--layout")) for v in args.layout or []],
        model_stages="disabled", nonce=os.urandom(16).hex(),
        governing_policy_sha256=policy_document["payload"]["policy_sha256"] if policy_document else None)
    authorisation_id = recurring.authorisation_id(id_inputs)
    provision_args = SimpleNamespace(
        output_config=args.output_config, template=str(ROOT / "config/programme_operations.json"),
        investigation_id=periods[0]["investigation_id"], confirm=periods[0]["investigation_id"],
        system_id=args.system_id, version=args.version, period=periods[0]["as_of"], framework=args.framework,
        control=args.control, criticality="high",
        boundary=f"Periodic exports for {args.system_id}, one period at a time, under standing authorisation {authorisation_id}",
        requirement_version=args.requirement_version, policy=args.policy, policy_version=args.policy_version,
        element=args.element, design_element=None, evidence=None, precedents=None,
        owner_key=args.owner_key, owner_name=args.owner_name, governance_key=args.governance_key,
        governance_name=args.governance_name, approver_key=args.approver_key, approver_name=args.approver_name,
        model="none", examine_model=None, explain_model=None, plan_model=None, challenge_model=None,
        reviewer_token_env=args.reviewer_token_env, reconcile=args.reconcile, no_model_stages=True,
        no_deterministic_completion=False, periodic=True)
    gaar_pilot.provision(provision_args)

    config_path = Path(args.output_config).expanduser().resolve()
    root = config_path.parent
    config = json.loads(config_path.read_text())
    from governance.investigation import InvestigationEngine, InvestigationStore
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    _, owner = gaar_pilot.load_human(args.owner_key, args.owner_name, "owner", root)
    _, governance = gaar_pilot.load_human(args.governance_key, args.governance_name, "governance", root)
    rows, values = engine.snapshot(periods[0]["investigation_id"])
    periods[0]["initial_head"] = rows[-1]["record_hash"]
    for period in periods[1:]:
        scope = values["understand"].scope.model_copy(update={"period": period["as_of"]})
        context = values["understand"].model_copy(update={"investigation_id": period["investigation_id"], "scope": scope})
        engine.append(period["investigation_id"], "understand", context, owner)
        engine.append(period["investigation_id"], "expectations", values["expectations"], governance)
        head = engine.snapshot(period["investigation_id"])[0][-1]["record_hash"]
        period["initial_head"] = head
        config["expected_heads"][period["investigation_id"]] = head

    if policy_document is not None:
        approver = config["trusted_keys"].get(policy_document["payload"]["approver_key_id"], {})
        if approver.get("actor_type") != "human" or "governance" not in approver.get("roles", []):
            raise ValueError("the policy was approved by someone who is not a governance owner of this series")
        config["governing_policy"] = {"approval_path": str(Path(args.policy_approval).expanduser().resolve()),
                                      "approval_sha256": pa.approval_sha256(policy_document),
                                      "policy_sha256": policy_document["payload"]["policy_sha256"]}
    if mapping_document is not None:
        from gaar_mapping import verify_document
        verified = verify_document(config, mapping_document)        # signed by this workspace's governance person
        config["reconciliation_mapping_document"] = {"path": str(mapping_path), "control_id": verified["control_id"],
                                                     "mapping_sha256": verified["mapping_sha256"],
                                                     "signed_by": verified["signed_by"]}
        if args.mapping_review:
            from governance.production.reconciliation import verify_mapping_review
            review_path = Path(args.mapping_review).expanduser().resolve()
            review_document = json.loads(review_path.read_text())
            reviewed = verify_mapping_review(review_document, mapping_document)
            config["reconciliation_mapping_document"]["review"] = {"path": str(review_path),
                                                                    "reviewer": reviewed["reviewer"],
                                                                    "outcome": reviewed["outcome"]}
    elif args.mapping_review:
        raise ValueError("--mapping-review needs the --mapping it reviews")
    inbox = Path(args.inbox).expanduser().resolve()
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    elements = [e.element_id for e in values["expectations"].elements]
    config["periodic_evidence"] = {
        "inbox": os.path.relpath(inbox, root), "authorisation_id": authorisation_id,
        "periods": {p["as_of"]: p["label"] for p in periods}, "grace_days": args.grace_days,
        "slack_minutes": args.slack_minutes,
        "evidence": [{"evidence_id": eid, "file": name, "element_ids": elements, "purposes": ["operating_record"]}
                     for eid, name in layout]}
    source = next(iter(config["sources"].values()))
    payload = {"authorisation_id": authorisation_id, "control_id": args.control, "framework": args.framework,
               "system_id": args.system_id, "version": args.version, "requirement_version": args.requirement_version,
               "source_id": source["source_id"], "source_sha256": source["sha256"],
               "mapping_sha256": digest(config["reconciliation_map"][args.control]),
               "mapping_document_sha256": digest(mapping_document) if mapping_document else None,
               "mapping_review_sha256": digest(review_document) if args.mapping and args.mapping_review else None,
               "governing_policy_sha256": policy_document["payload"]["policy_sha256"] if policy_document else None,
               "governing_policy_version": policy_document["payload"]["policy_version"] if policy_document else None,
               "governing_policy_approval_sha256": pa.approval_sha256(policy_document) if policy_document else None,
               "governing_policy_status": ("APPROVED" if policy_document else "NOT_APPROVED (constructed demonstration)"),
               "evidence_layout": [[eid, name] for eid, name in layout],
               "inbox": config["periodic_evidence"]["inbox"], "cadence_days": args.cadence_days,
               "periods": periods, "model_stages": "disabled", "grace_days": args.grace_days,
               "slack_minutes": args.slack_minutes, "constructed_demo": bool(args.constructed_demo),
               "overdue_rule": "runbook O1: OVERDUE once grace_days have passed after a period ends without its exports",
               "signed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "authorisation_id_inputs": id_inputs}
    signatures = [{"role": "owner", "key_id": owner.key_id, "signature": owner.sign(canonical(payload).encode())},
                  {"role": "governance", "key_id": governance.key_id,
                   "signature": governance.sign(canonical(payload).encode())}]
    document_path = root / "pilot" / "standing_authorisation.json"
    document_path.write_text(json.dumps({"payload": payload, "signatures": signatures}, indent=2) + "\n")
    os.chmod(document_path, 0o600)
    config["standing_authorisation"] = str(document_path.relative_to(root))
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(config_path, 0o600)
    recurring.verify(config, root)
    return {"status": "STANDING_AUTHORISATION_SIGNED", "authorisation_id": authorisation_id,
            "config": str(config_path), "inbox": str(inbox),
            "periods": [{"label": p["label"], "investigation_id": p["investigation_id"]} for p in periods],
            "next": f"drop each period's exports into {inbox}/<label>/ — or run demo-inbox — then tick"}


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------

def _notify(message):
    if sys.platform == "darwin" and shutil.which("osascript"):
        subprocess.run(["osascript", "-e", f'display notification "{message}" with title "GaaR"'],
                       check=False, capture_output=True)


def _print(summary):
    for s in summary:
        shown = (f"OVERDUE {s['overdue_days']}d" if s["state"] == "OVERDUE"
                 else "QUARANTINED (D14)" if s.get("integrity_event") else s["state"])
        line = f"  {s['label']}  {shown:<22} {s.get('verdict') or '':<13} " \
               f"{'' if s.get('issues') is None else str(s['issues']) + ' findings'}"
        print(line)
        delta = s.get("delta")
        if delta:
            print(f"      since {delta['previous_label']}: verdict {delta['verdict_before']} → {delta['verdict_after']}"
                  f"{' (changed)' if delta['verdict_changed'] else ' (unchanged)'}; findings "
                  f"{delta['issues_before']} → {delta['issues_after']}")
            if delta["codes_resolved"]:
                print("      resolved: " + ", ".join(delta["codes_resolved"]))
            if delta["codes_new"]:
                print("      new:      " + ", ".join(delta["codes_new"]))
            if delta["codes_persisting"]:
                print("      still:    " + ", ".join(delta["codes_persisting"]))


def _watch_lock(root):
    import fcntl
    handle = open(Path(root) / "pilot" / "watch.lock", "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _launchd_loaded():
    if not shutil.which("launchctl"):
        return False
    return subprocess.run(["launchctl", "list", "com.gaar.recurring"], capture_output=True).returncode == 0


def tick(args):
    config, root = _load(args.config)
    probe = _watch_lock(root)
    if probe is None:
        print(time.strftime("%H:%M:%S"), "watch is running on this workspace; this scheduled check was skipped")
        return {"status": "TICKED"}
    probe.close()
    when = None
    if getattr(args, "as_of", None):
        from datetime import datetime
        when = datetime.fromisoformat(args.as_of)
        if when.tzinfo is None:
            raise ValueError("--as-of needs a time zone, for example 2026-10-01T09:00:00+08:00")
        print(f"SIMULATED CLOCK {when.isoformat()} — constructed demonstration only; recorded in every result it produces")
    try:
        summary = recurring.tick(config, root, notify=_notify if args.notify else None, now=when)
    except recurring.SchedulerBusy:
        print(time.strftime("%H:%M:%S"), "another check is still running; this one was skipped")
        return {"status": "TICKED"}
    print(time.strftime("%H:%M:%S"), "checked", len(summary), "periods")
    _print(summary)
    return {"status": "TICKED"}


def watch(args):
    config, root = _load(args.config)
    if _launchd_loaded():
        raise ValueError("the launchd schedule com.gaar.recurring is loaded; run one scheduler at a time. "
                         "Unload it (launchctl unload -w ~/Library/LaunchAgents/com.gaar.recurring.plist) or skip watch")
    lock = _watch_lock(root)
    if lock is None:
        raise ValueError("another watch is already running on this workspace")
    print(f"Watching {Path(args.config).expanduser()} every {args.every}s. Ctrl-C to stop.")
    seen = {}
    while True:
        try:
            config, root = _load(args.config)
            summary = recurring.tick(config, root, notify=_notify if args.notify else None)
        except recurring.SchedulerBusy:
            time.sleep(args.every)
            continue
        except (ValueError, FileNotFoundError) as exc:
            print(f"{time.strftime('%H:%M:%S')} Stopped: this workspace's standing authorisation changed or no "
                  f"longer matches what was signed ({exc}). Restart watch if the new series is intended.")
            return {"status": "WATCH_STOPPED"}
        changed = [s for s in summary if seen.get(s["label"]) != s["state"] or s.get("ran")]
        if changed:
            print(time.strftime("%H:%M:%S"))
            _print(changed)
        seen = {s["label"]: s["state"] for s in summary}
        time.sleep(args.every)


def status(args):
    config, root = _load(args.config)
    payload = recurring.verify(config, root)
    when = None
    if args.as_of:
        from datetime import datetime
        when = datetime.fromisoformat(args.as_of)
        if when.tzinfo is None:
            raise ValueError("--as-of needs a time zone, for example 2026-10-02T09:00:00+08:00")
        print(f"PREVIEW as of {when.isoformat()} — read-only; nothing runs and nothing is recorded")
    print(f"{payload['authorisation_id']}  {payload['control_id']}  {payload['system_id']}  "
          f"(signed {payload['signed_at']}; overdue after {payload.get('grace_days', 2)} day(s) grace)")
    _print([recurring.period_state(config, root, p, when) for p in payload["periods"]])
    return {"status": "OK"}


def demo_inbox(args):
    config, root = _load(args.config)
    payload = recurring.verify(config, root)
    source = FIXTURES.get(args.week)
    if not source:
        raise ValueError("constructed exports exist for --week 1, 2 and 3")
    period = payload["periods"][args.week - 1]
    declared = json.loads((source / "changes.json").read_text())["as_of"]
    if declared != period["as_of"]:
        raise ValueError(f"week {args.week} exports are for {declared}, but period {args.week} ends {period['as_of']}")
    folder = root / config["periodic_evidence"]["inbox"] / period["label"]
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in config["periodic_evidence"]["evidence"]:
        shutil.copyfile(source / item["file"], folder / item["file"])
    return {"status": "EXPORTS_ARRIVED", "period": period["label"], "folder": str(folder)}


def install_schedule(args):
    config_path = Path(args.config).expanduser().resolve()
    _, root = _load(config_path)
    label = "com.gaar.recurring"
    plist = Path(args.plist_dir).expanduser() / f"{label}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    log = root / "pilot" / "schedule.log"
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>
    <string>{sys.executable}</string><string>{Path(__file__).resolve()}</string>
    <string>tick</string><string>--config</string><string>{config_path}</string><string>--notify</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>StartInterval</key><integer>{args.every_minutes * 60}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
""")
    return {"status": "SCHEDULE_WRITTEN", "plist": str(plist),
            "start": f"launchctl load -w {plist}", "stop": f"launchctl unload -w {plist}", "log": str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("authorise", help="sign a standing authorisation for a series of periods")
    a.add_argument("--constructed-demo", action="store_true", help="use the constructed pack, test keys and a 4-week series")
    a.add_argument("--workspace", default=str(Path.home() / "gaar-recurring-demo"))
    for flag in ("--output-config", "--inbox", "--id-prefix", "--confirm", "--system-id", "--version", "--framework",
                 "--control", "--requirement-version", "--policy", "--policy-version", "--first-period-end",
                 "--owner-key", "--owner-name", "--governance-key", "--governance-name", "--approver-key",
                 "--approver-name"):
        a.add_argument(flag)
    a.add_argument("--cadence-days", type=int, default=7)
    a.add_argument("--slack-minutes", type=int, default=10,
                   help="clock-skew tolerance at a period's end, signed into the authorisation (D14)")
    a.add_argument("--grace-days", type=int, default=2,
                   help="days after a period ends before missing exports count as OVERDUE (signed into the authorisation)")
    a.add_argument("--periods", type=int)
    a.add_argument("--element", action="append")
    a.add_argument("--reconcile", action="append")
    a.add_argument("--layout", action="append", help="EVIDENCE_ID=FILE_NAME expected in every period folder")
    a.add_argument("--reviewer-token-env", default="GAAR_REVIEWER_TOKEN")
    a.add_argument("--policy-approval", help="the signed approval of the governing policy (tools/gaar_policy.py); "
                                              "required for any series on real evidence")
    a.add_argument("--mapping-review", help="an independent, signed review of the --mapping document")
    a.add_argument("--mapping", help="a governance-signed mapping document from gaar_mapping.py sign; "
                                      "the series is pinned to it")
    a.set_defaults(func=authorise)
    for name, func in (("tick", tick), ("watch", watch), ("status", status)):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--notify", action="store_true", help="macOS notification when a new result is ready")
        if name == "watch":
            p.add_argument("--every", type=int, default=30)
        if name == "tick":
            p.add_argument("--as-of", help="simulated clock for a signed constructed-demo series only; recorded in results")
        if name == "status":
            p.add_argument("--as-of", help="preview period states at this time (read-only), e.g. 2026-10-02T09:00:00+08:00")
        p.set_defaults(func=func)
    d = sub.add_parser("demo-inbox", help="simulate a week's constructed exports arriving")
    d.add_argument("--config", required=True)
    d.add_argument("--week", type=int, required=True)
    d.set_defaults(func=demo_inbox)
    s = sub.add_parser("install-schedule", help="write a macOS launchd job that ticks on a timer")
    s.add_argument("--config", required=True)
    s.add_argument("--every-minutes", type=int, default=60)
    s.add_argument("--plist-dir", default=str(Path.home() / "Library/LaunchAgents"))
    s.set_defaults(func=install_schedule)
    args = parser.parse_args()
    result = args.func(args)
    if result and result.get("status") not in {"TICKED", "OK"}:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped")
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
