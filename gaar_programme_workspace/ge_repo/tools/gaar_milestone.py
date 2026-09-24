#!/usr/bin/env python3
"""The whole milestone check on your machine, in order, as one resumable command.

    python tools/gaar_milestone.py --config ~/gaar-recurring-demo/operations.json \
        --out ~/Desktop/GaaR_Quality_Policy_Workpaper.docx

It runs, in this order, and stops only where a person must act:

1. the canonical test run and the guard trace. Both are skipped on a rerun if they already passed on this exact
   code tree: the tree's hash is recorded beside them;
2. the policy approval check. If no approval covers the current policy text, it stops and prints the approve
   command (approval is a human act; this tool never signs);
3. the series check: signatures, pinned policy and mapping, configuration drift;
4. one scheduler tick: arrived periods run, and a record blocked only by a software upgrade is rerun under this
   version (runbook U1), keeping the old one intact;
5. the attestation check. If no period is attested yet, it stops and prints the command that opens the app in its
   inbox view. You sign there, then rerun this command, and it continues from here;
6. generate the gate-status report, verify it, render the workpaper, freeze the pack;
7. a summary of every gate against the state this milestone expects, written to reports/milestone-<time>.txt.
   That file is the one thing to send back.

Exit codes: 0 all expected, 1 a gate differs from expectation or a check failed, 3 waiting on a human step.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Not in .test_runs/: the gate-status report reads every record there as a test run or trace.
STATE = ROOT / ".milestone_state.json"
EXPECTED = {"Policy approval": "HELD", "Independent mapping review": "HELD", "A valid test run": "HELD",
            "A refusal or integrity rule": "HELD", "Collection completeness": "HELD", "Attestation quality": "HELD",
            "Procedure completeness": "OPEN"}
WHY_OPEN = {"Procedure completeness": "no adversarial pack yet: needs the external pack author (your side)"}


def tree_sha256() -> str:
    """The code and governing text the tests ran against. Local working state is excluded."""
    h = hashlib.sha256()
    skip = {".test_runs", "reports", "packs", "__pycache__", ".pytest_cache", "runs", "var"}
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if rel.parts[:3] == ("docs", "quality", "approvals") or path == STATE:   # events and own state, not code
            continue
        if path.is_file() and not skip & set(rel.parts) and path.suffix in {".py", ".md", ".json", ".txt", ".yaml"}:
            h.update(str(rel).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def say(line=""):
    print(line, flush=True)


def _latest(prefix_trace):
    runs = sorted((ROOT / ".test_runs").glob("trace-*.json" if prefix_trace else "[0-9]*.json"))
    return (runs[-1], json.loads(runs[-1].read_text())) if runs else (None, None)


def tests_and_trace(force):
    tree = tree_sha256()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    latest_run, latest_trace = _latest(False)[1] or {}, _latest(True)[1] or {}
    if (not force and state.get("tree_sha256") == tree and state.get("tests") == "PASS" and state.get("trace") == "PASS"
            and latest_run.get("verdict") == "COMPLETE RUN, ALL PASSED" and latest_trace.get("verdict") == "PASS"):
        say(f"1. tests and trace: already passed on this code tree ({tree[:12]}) at {state['at']}; not rerun")
        return True
    say("1. canonical test run (about 4 minutes)…")
    run = subprocess.run([sys.executable, str(ROOT / "tools/run_all_tests.py")], cwd=ROOT, text=True,
                         capture_output=True)
    lines = [l for l in run.stdout.splitlines() if l.startswith(("COLLECTED", "VERDICT", "run record"))]
    for l in lines:
        say("   " + l)
    _, record = _latest(False)
    tests_ok = run.returncode == 0 and record and record.get("verdict") == "COMPLETE RUN, ALL PASSED"
    if not tests_ok:
        say("   the test run did not pass; output tail:")
        say("\n".join("   " + l for l in (run.stdout + run.stderr).splitlines()[-25:]))
        return False
    say("   guard trace…")
    trace = subprocess.run([sys.executable, str(ROOT / "tools/trace_unreached_guards.py")], cwd=ROOT, text=True,
                           capture_output=True)
    for l in trace.stdout.splitlines():
        say("   " + l)
    if trace.returncode:
        return False
    STATE.write_text(json.dumps({"tree_sha256": tree, "tests": "PASS", "trace": "PASS",
                                 "at": datetime.now().astimezone().isoformat()}, indent=2) + "\n")
    return True


def policy_approved():
    from governance.production import policy_approval as pa
    identity = pa.policy_identity(pa.POLICY)
    covering = []
    for path in sorted(pa.APPROVALS.glob("*.approval.json")) if pa.APPROVALS.is_dir() else []:
        try:
            covering.append(pa.verify(pa.load(path), pa.POLICY)["approver"])
        except Exception:
            continue
    if covering:
        say(f"2. policy {identity['policy_version']} ({identity['policy_sha256'][:12]}): approved by {', '.join(covering)}")
        return True
    say(f"2. policy {identity['policy_version']} ({identity['policy_sha256'][:12]}) has no approval. Read it, then run:")
    say(f"     python tools/gaar_policy.py approve --key ~/.gaar-test-keys/owner.key --name \"Test Owner\" "
        f"--confirm {identity['policy_sha256'][:12]}")
    say("   and rerun this command.")
    return False


def series_ok(config_path):
    from governance.operations.runtime import load
    from governance.production import recurring
    config, root = load(config_path)
    try:
        recurring.verify(config, root)
    except Exception as exc:
        say(f"3. series: REFUSED: {exc}")
        say("   the series no longer matches what was signed; re-authorise it (see the kit's instructions)")
        return None
    periods = recurring.load(config, root)["payload"]["periods"]
    states = [recurring.period_state(config, root, p) for p in periods]
    say("3. series: signatures and pinned inputs verify")
    for s in states:
        say(f"     {s['label']}  {s['state']:<22} {s.get('verdict') or ''}")
    return config, root, states


def scheduler_tick(config_path):
    """One tick of the one scheduler: runs arrived periods and reruns records blocked only by an upgrade (U1)."""
    from governance.production import recurring, scheduler
    try:
        result = scheduler.tick(config_path)
    except scheduler.SchedulerBusy as exc:
        say(f"   scheduler: {exc}; using the state it last recorded")
        result = None
    if result:
        for name, outcome in result["jobs"].items():
            extra = ""
            if name == "series":
                reran = [p["label"] for p in outcome.get("periods", []) if p.get("superseded")]
                extra = (f"; reran under this software (runbook U1): {', '.join(reran)}" if reran else "")
            say(f"   scheduler job {name}: {outcome['status']}{extra}"
                + (f" — {outcome['error']}" if outcome.get("error") else ""))
    from governance.operations.runtime import load
    config, root = load(config_path)
    periods = recurring.load(config, root)["payload"]["periods"]
    return [recurring.period_state(config, root, p) for p in periods], (result or {}).get("jobs", {})


def attested(config_path, states):
    if any(s["state"] == "ATTESTED" for s in states):
        say("4. attestation: " + ", ".join(s["label"] for s in states if s["state"] == "ATTESTED") + " attested")
        return True
    waiting = [s["label"] for s in states if s["state"] == "AWAITING_ATTESTATION"]
    say("4. attestation: none yet. This is the one step that must be yours. Open the app:")
    say(f"     GAAR_UI=simple GAAR_REVIEWER_TOKEN=gaar-test-123 WB_INVESTIGATION_CONFIG={config_path} "
        f"python -m streamlit run app_gaar.py --server.port 8502")
    say(f"   The inbox lists what needs you. Open {waiting[-1] if waiting else 'the latest period'}, sign "
        "\"No exceptions noted for this period (assurance only)\", take the screenshot, stop the app with Ctrl-C, "
        "and rerun this command.")
    return False


def report_and_workpaper(config_path, out):
    from governance.production import gate_status
    sys.path.insert(0, str(ROOT / "tools"))
    import gaar_workpaper
    report = gate_status.generate(str(config_path))
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    stamp = report["derivation_receipt"]["generated_at"].replace(":", "").replace("+", "_")
    target = reports / f"gate_status-{stamp}.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    target.with_suffix(".md").write_text(gate_status.render_markdown(report))
    check = gate_status.verify(json.loads(target.read_text()))
    say(f"5. gate-status report: {target.relative_to(ROOT)}; verify: valid={check['valid']} ({check['reason']})")
    if not check["valid"]:
        return None, None
    written = gaar_workpaper.build(target, out)
    say(f"   workpaper: {written['workpaper']}")
    return report, target


def summary(report, target, out, pack=None):
    lines = [f"GaaR milestone check — {datetime.now().astimezone().isoformat(timespec='seconds')}",
             f"policy {report['policy']['policy_version']} ({report['policy']['policy_sha256'][:12]}), "
             f"series {report['series']}, report {target.name} (verified), workpaper {out}",
             f"frozen pack (what to share): {pack}", "",
             f"{'Gate':<30} {'State':<9} {'Expected':<9}"]
    differs = []
    for g in report["gates"]:
        want = EXPECTED.get(g["gate"], "?")
        mark = "" if g["state"] == want else "  <-- differs"
        differs += [g["gate"]] if mark else []
        lines.append(f"{g['gate']:<30} {g['state']:<9} {want:<9}{mark}")
        lines.append(f"    {g['evidence']}" + (f"  [{WHY_OPEN[g['gate']]}]" if g["gate"] in WHY_OPEN else ""))
    watch_rows = []
    try:
        from governance.watcher import intel
        if intel.configured():
            health = intel.health()
            watch = (f"{len(health)} source(s), {sum(h['state'] == 'OK' for h in health)} OK; "
                     f"{len(intel.needs_triage())} item(s) to triage")
            watch_rows = [f"    {h['source_id']:<26} {(h.get('jurisdiction') or ''):<10} {h['state']:<13} "
                          + ("verified" if h.get("address_verified") else "NOT YET VERIFIED")
                          + (f"  last success {h['last_success'][:16]}" if h["last_success"] else "")
                          + (f"  error: {str(h['error'])[:90]}" if h["state"] == "FAILING" and h.get("error") else "")
                          for h in health]
        else:
            watch = "not set up (optional: python tools/gaar_watch.py setup)"
    except Exception as exc:
        watch = f"unavailable ({type(exc).__name__}: {exc})"
    lines += ["", f"guard register: {report['guard_register']['summary']}", f"regulatory watch: {watch}", *watch_rows, "",
              "RESULT: " + ("ALL GATES AS EXPECTED" if not differs else "DIFFERS: " + ", ".join(differs))]
    text = "\n".join(lines) + "\n"
    path = ROOT / "reports" / f"milestone-{target.stem.removeprefix('gate_status-')}.txt"
    path.write_text(text)
    say("")
    say(text)
    say(f"summary written to {path}  <- send this file back, with the screenshot of the inbox and the signed item")
    return not differs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="the series workspace, e.g. ~/gaar-recurring-demo/operations.json")
    parser.add_argument("--out", required=True, help="where to write the workpaper .docx")
    parser.add_argument("--rerun-tests", action="store_true", help="run tests and trace even if they passed on this tree")
    args = parser.parse_args()
    config_path, out = Path(args.config).expanduser().resolve(), Path(args.out).expanduser()
    if not tests_and_trace(args.rerun_tests):
        raise SystemExit(1)
    if not policy_approved():
        raise SystemExit(3)
    series = series_ok(config_path)
    if series is None:
        raise SystemExit(1)
    say("3b. scheduler tick")
    states, jobs = scheduler_tick(config_path)
    if jobs.get("series", {}).get("status") == "FAILED":
        say("   the series job failed; see the inbox: python tools/gaar_scheduler.py inbox --config " + str(config_path))
        raise SystemExit(1)
    if not attested(config_path, states):
        raise SystemExit(3)
    report, target = report_and_workpaper(config_path, out)
    if report is None:
        raise SystemExit(1)
    sys.path.insert(0, str(ROOT / "tools"))
    import gaar_pack
    pack = gaar_pack.freeze(target, out)
    check = gaar_pack.verify(pack["pack"])
    say(f"   frozen pack: {pack['pack']} (verify: valid={check['valid']})")
    from governance.production import inbox
    say(f"   status line: {inbox.status_line(config_path)['text']}")
    raise SystemExit(0 if summary(report, target, out, pack["pack"]) and check["valid"] else 1)


if __name__ == "__main__":
    main()
