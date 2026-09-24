#!/usr/bin/env python3
"""Phase 0 in one command.

    python tools/gaar_phase0.py --mode C --fast qwen2.5:7b

Modes: A = Colibri everywhere, B = fast Ollama model everywhere,
C = fast Ollama model for examine/explain/plan and Colibri for challenge.

It checks the model servers, archives the previous run, provisions a fresh
workspace from the constructed evidence pack, runs the pipeline without the
browser, prints progress, and ends with a short report meant to be pasted back
into chat. Open the reviewer app afterwards to read the result and attest.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
HOME = Path.home()
IID = "CHG-TEST-001"
ELEMENTS = [
    "chg.1=Every production change is approved before execution by an authorised approver who is not its implementer",
    "chg.2=Every production change is executed as approved: window, targets, actions, implementer, credential, artefact and a valid privilege grant",
    "chg.3=Changes inside a freeze have a prior approved exception, and failed changes have a recorded approved recovery",
    "chg.4=The change record is complete against an independent record of production changes",
]


# D8 mapping for the constructed pack: each obligation lists the codes of the
# deterministic procedures that test it. Codes are the ones the procedures emit.
RECONCILIATION_MAP = {
    "chg.1": ["APPROVAL_AFTER_EXECUTION", "APPROVAL_NOT_ESTABLISHED", "NO_MATCHING_APPROVED_TICKET", "SELF_APPROVAL"],
    "chg.2": ["OUTSIDE_APPROVED_WINDOW", "DEVIATES_FROM_APPROVED_SCOPE", "IMPLEMENTER_NOT_APPROVED",
              "CREDENTIAL_NOT_APPROVED_FOR_CHANGE", "IMPLEMENTATION_CONTENT_MISMATCH", "PRIVILEGE_NOT_ESTABLISHED"],
    "chg.3": ["FREEZE_WITHOUT_PRIOR_EXCEPTION", "RECOVERY_NOT_ESTABLISHED"],
    "chg.4": ["COLLECTION_POPULATION_DISAGREEMENT"],
}


def say(message=""):
    print(message, flush=True)


def http_json(url, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read() or b"{}")


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def preflight(args):
    problems = []
    if port_open(8502):
        problems.append("The reviewer app is running on port 8502. Stop it (Ctrl-C) before a run: "
                        "a running app keeps the old workspace in memory.")
    need_ollama = args.mode in ("B", "C")
    if args.mode == "D":
        say("  models   off  deterministic record only")
    need_colibri = args.mode in ("A", "C")
    colibri_model = args.colibri_model
    if need_ollama:
        try:
            _, tags = http_json(f"{args.ollama}/api/tags")
            names = {m.get("name") for m in tags.get("models", [])}
            wanted = args.fast if ":" in args.fast else args.fast + ":latest"
            if args.fast not in names and wanted not in names:
                problems.append(f"Ollama is running but '{args.fast}' is not pulled. Run: ollama pull {args.fast}")
            else:
                say(f"  ollama   ok   {args.fast}")
        except Exception as exc:
            problems.append(f"Ollama is not reachable at {args.ollama} ({type(exc).__name__}). Open the Ollama app or run: ollama serve")
    if need_colibri:
        try:
            _, models = http_json(f"{args.colibri}/models")
            ids = [m.get("id") for m in models.get("data", [])]
            colibri_model = colibri_model or (ids[0] if ids else None)
            if not colibri_model:
                problems.append("Colibri answered but lists no model.")
            else:
                try:
                    code, _ = http_json(f"{args.colibri}/chat/completions",
                                        {"model": colibri_model, "max_tokens": 5,
                                         "messages": [{"role": "user", "content": "Reply OK"}]}, timeout=120)
                    say(f"  colibri  ok   {colibri_model} (idle)")
                except urllib.error.HTTPError as exc:
                    if exc.code == 429:
                        problems.append("Colibri is busy with an earlier request (429). Restart it: Ctrl-C in its window, then coli serve")
                    else:
                        problems.append(f"Colibri rejected a tiny test request: {exc.code} {exc.read().decode()[:200]}")
        except urllib.error.HTTPError as exc:
            problems.append(f"Colibri /models failed: {exc.code}")
        except Exception as exc:
            problems.append(f"Colibri is not reachable at {args.colibri} ({type(exc).__name__}). Start it: coli serve")
    return problems, colibri_model


# --------------------------------------------------------------------------
# workspace
# --------------------------------------------------------------------------

def archive_previous(workspace, out_dir):
    programme = workspace / "pilot" / "programme"
    if programme.exists() and any(programme.iterdir()):
        name = out_dir / ("autosave_" + time.strftime("%Y%m%d_%H%M%S"))
        say(f"  archived previous run -> {shutil.make_archive(str(name), 'zip', programme)}")


def provision(args, workspace, keys):
    pilot = str(ROOT / "tools" / "gaar_pilot.py")
    for name in ("owner", "reviewer"):
        if not (keys / f"{name}.key").exists():
            subprocess.run([sys.executable, pilot, "keygen", "--out", str(keys / f"{name}.key")],
                           check=True, capture_output=True, text=True)
    shutil.rmtree(workspace, ignore_errors=True)
    pack = Path(args.pack).expanduser()
    command = [sys.executable, pilot, "provision", "--output-config", str(workspace / "operations.json"),
               "--investigation-id", IID, "--confirm", IID, "--system-id", "CONSTRUCTED-payments-api",
               "--version", "4.x", "--period", "2026-09-15T00:00:00+08:00", "--framework", "INTERNAL",
               "--control", "CHANGE.MGMT", "--requirement-version", "constructed-cm-v1",
               "--policy", str(pack / "evidence/change_policy.md"), "--policy-version", "v1",
               "--evidence", f"CHANGES={pack / 'evidence/changes.json'}",
               "--evidence", f"POPULATION={pack / 'evidence/population.json'}",
               "--owner-key", str(keys / "owner.key"), "--owner-name", "Test Owner",
               "--governance-key", str(keys / "owner.key"), "--governance-name", "Test Owner",
               "--approver-key", str(keys / "reviewer.key"), "--approver-name", "Test Reviewer",
               "--model", args.fast]
    for element in ELEMENTS:
        command += ["--element", element]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("Provisioning failed:\n" + (result.stderr or result.stdout)[-1500:])


def configure(args, workspace, colibri_model):
    path = workspace / "operations.json"
    config = json.loads(path.read_text())
    fast = dict(provider="ollama", base_url=args.ollama, model=args.fast,
                max_tokens=args.fast_tokens, num_ctx=args.num_ctx, timeout_seconds=args.timeout)
    deep = dict(provider="openai_compatible", base_url=args.colibri, model=colibri_model,
                max_tokens=args.cap, context_tokens=args.colibri_ctx, timeout_seconds=args.timeout)
    if args.mode == "D":
        config["model_stages"] = "disabled"
        config["reconciliation_map"] = {"CHANGE.MGMT": RECONCILIATION_MAP}
        config["deterministic_completion"] = True
        path.write_text(json.dumps(config, indent=2) + "\n")
        return {stage: "none" for stage in ("examine", "explain", "plan", "challenge")}
    assessor, challenger = {"A": (deep, deep), "B": (fast, fast), "C": (fast, deep)}[args.mode]
    for stage in ("examine", "explain", "plan"):
        config["models"][stage].update(assessor)
    config["models"]["challenge"].update(challenger)
    config["reconciliation_map"] = {"CHANGE.MGMT": RECONCILIATION_MAP}
    config["deterministic_completion"] = True
    path.write_text(json.dumps(config, indent=2) + "\n")
    return {stage: config["models"][stage]["model"] for stage in ("examine", "explain", "plan", "challenge")}


# --------------------------------------------------------------------------
# run with progress
# --------------------------------------------------------------------------

def run_with_progress(workspace):
    from governance.operations.runtime import load
    from governance.production.orchestrator import run, case_directory
    config, root = load(workspace / "operations.json")
    receipts = case_directory(config, root, IID) / "inference_receipts"
    outcome = {}

    def worker():
        try:
            outcome["report"] = run(config, root, IID)
        except Exception as exc:
            outcome["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=worker, daemon=True)
    started = time.time()
    thread.start()
    seen = set()
    last_beat = started
    while thread.is_alive():
        thread.join(5)
        for path in sorted(receipts.glob("*.json"), key=os.path.getmtime) if receipts.exists() else []:
            if path in seen:
                continue
            seen.add(path)
            try:
                r = json.loads(path.read_text())
                say(f"  [{int(time.time() - started):5d}s] {r.get('stage', '?'):18} {r.get('model', ''):24} "
                    f"{r.get('status', '')} {('- ' + r['error'][:80]) if r.get('error') else ''}")
            except (OSError, ValueError):
                pass
        if time.time() - last_beat >= 60:
            last_beat = time.time()
            say(f"  [{int(time.time() - started):5d}s] still working...")
    return config, root, outcome, int(time.time() - started)


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def report(config, root, outcome, seconds, models, args):
    from governance.investigation import InvestigationEngine, InvestigationStore
    from governance.production.orchestrator import case_directory
    case = case_directory(config, root, IID)
    lines = [f"PHASE0 RUN {args.mode} | examine={models['examine']} challenge={models['challenge']} | {seconds}s total"]
    run_report = outcome.get("report") or {}
    if outcome.get("error"):
        lines.append(f"STOPPED: {outcome['error'][:300]}")
    lines.append(f"checkpoint={run_report.get('checkpoint')} verdict={(run_report.get('gate') or {}).get('verdict')}")
    if run_report.get("checkpoint") == "DETERMINISTIC_COMPLETE":
        gone = run_report["model_stage_unavailable"]
        if gone.get("disabled_by_configuration"):
            lines.append(f"deterministic record: model stages disabled by configuration; "
                         f"verdict {run_report['deterministic_verdict']} from tests + D8; attest in the reviewer app")
        else:
            lines.append(f"deterministic completion: {gone['stage']} unavailable ({gone['error'][:120]}); "
                         f"verdict {run_report['deterministic_verdict']} from tests + D8; attest in the reviewer app")
    request = run_report.get("request") or run_report.get("next_request")
    if request:
        lines.append(f"request: {str(request.get('reason'))[:300]}")
    blockers = (run_report.get("gate") or {}).get("blockers")
    if blockers:
        lines.append(f"blockers: {blockers}")

    lines.append("stages:")
    for path in sorted((case / "inference_receipts").glob("*.json"), key=os.path.getmtime):
        r = json.loads(path.read_text())
        try:
            took = int((datetime.fromisoformat(r["finished_at"]) - datetime.fromisoformat(r["started_at"])).total_seconds())
        except Exception:
            took = -1
        lines.append(f"  {r.get('stage', '?'):18} {r.get('model', ''):24} {r.get('status', ''):18} {took:5d}s"
                     + (f"  {r['error'][:100]}" if r.get("error") else ""))

    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    rows, values = engine.snapshot(IID)
    lines.append("signed stages: " + ", ".join(row["stage"] for row in rows))
    if "examine" in values:
        lines.append("examine (accepted): " + ", ".join(f"{f.element_id}={f.status}[{len(f.evidence_refs)} refs]"
                                                   for f in values["examine"].findings))
    else:
        examine = [p for p in (case / "inference_receipts").glob("examine-*.json")]
        if examine:
            r = json.loads(max(examine, key=os.path.getmtime).read_text())
            try:
                findings = json.loads(r.get("response") or "{}").get("findings", [])
                lines.append("examine (rejected): " + ", ".join(
                    f"{f.get('element_id')}={f.get('status')}[{len(f.get('evidence_refs') or [])} refs]" for f in findings))
                for f in findings:
                    lines.append(f"    {f.get('element_id')}: {str(f.get('rationale', ''))[:140]}")
            except ValueError:
                lines.append("examine (rejected): response was not valid JSON: " + str(r.get("response", ""))[:200])
    event = __import__("governance.production.journal", fromlist=["Journal"]).Journal(
        case / "operations.sqlite", config["trusted_keys"]).latest("obligation_reconciliation")
    if event:
        rec = event["payload"]
        lines.append("reconciled (D8): " + ", ".join(
            f"{o['element_id']}={o['governed_status']}" + (" [assessor said SUPPORTED]" if o["false_assurance"] else "")
            for o in rec["obligations"]))
        examine_receipts = sorted((case / "inference_receipts").glob("examine-*.json"), key=os.path.getmtime)
        attempted = None
        if examine_receipts:
            receipt = json.loads(examine_receipts[-1].read_text())
            from governance.production.reconciliation import attempted_false_assurance
            attempted = attempted_false_assurance(receipt.get("response") or "", rec["obligations"])
        lines.append(f"deterministic issues: {len(rec['issues'])}")
        if attempted is None:
            lines.append("false assurance: attempted n/a (no model asked) · recorded 0")
        elif not attempted["parsed"]:
            lines.append(f"false assurance: attempted unknown (answer not parseable) · recorded {rec['false_assurance_count']}")
        else:
            lines.append(f"false assurance: attempted {attempted['attempted']} of {attempted['obligations']} "
                         f"(what the model said) · recorded {rec['false_assurance_count']} (what reached the record)")
    if "explain" in values:
        lines.append(f"hypotheses: {len(values['explain'].hypotheses)} "
                     f"(material {sum(h.material for h in values['explain'].hypotheses)})")
    if "verify" in values:
        for test in values["verify"].tests:
            result = json.loads(test.result_json or "{}")
            lines.append(f"test {test.test_id} {test.status}: discrepancies={len(result.get('findings', []))} "
                         f"gaps={len(result.get('assurance_gaps', []))}")
    if "challenge" in values:
        challenge = values["challenge"]
        lines.append(f"challenge: findings={len(challenge.findings)} missing_explanations={len(challenge.missing_explanations)}")
        for finding in challenge.findings:
            lines.append(f"    {finding.finding_id}: {finding.claim[:140]}")
    if "conclude" in values:
        lines.append(f"conclusion: {values['conclude'].verdict}")
    return lines, case


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["A", "B", "C", "D"], required=True,
                        help="A Colibri everywhere, B fast model everywhere, C fast + Colibri challenge, D no model (pilot)")
    parser.add_argument("--fast", default="qwen2.5:7b")
    parser.add_argument("--colibri-model", default=None, help="defaults to the first model Colibri lists")
    parser.add_argument("--cap", type=int, default=1024, help="Colibri output token limit")
    parser.add_argument("--colibri-ctx", type=int, default=4096,
                        help="Colibri context window in tokens; its startup log shows it as 'KV 1xN'")
    parser.add_argument("--fast-tokens", type=int, default=4096)
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--colibri", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--pack", default=str(HOME / "gaar-test/evidence-pack"))
    parser.add_argument("--workspace", default=str(HOME / "gaar-constructed-test"))
    parser.add_argument("--keys", default=str(HOME / ".gaar-test-keys"))
    parser.add_argument("--out", default=str(HOME / "gaar-test/phase0"))
    args = parser.parse_args()

    workspace, keys, out = Path(args.workspace), Path(args.keys), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    say(f"Phase 0 run {args.mode}: preflight")
    problems, colibri_model = preflight(args)
    if problems:
        say("\nNOT STARTED:")
        for problem in problems:
            say(f"  - {problem}")
        return 2
    archive_previous(workspace, out)
    say("  provisioning fresh workspace")
    provision(args, workspace, keys)
    models = configure(args, workspace, colibri_model or "unused")
    say("  models: " + ", ".join(f"{k}={v}" for k, v in models.items()))
    say("running (progress appears as each stage returns)")
    config, root, outcome, seconds = run_with_progress(workspace)
    lines, case = report(config, root, outcome, seconds, models, args)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (case / "phase0_report.txt").write_text("\n".join(lines) + "\n")
    tag = models["examine"].replace(":", "_").replace(".", "")
    saved = shutil.make_archive(str(out / f"run_{args.mode}_{tag}_{stamp}"), "zip", case)
    say("\n" + "=" * 20 + " PASTE FROM HERE " + "=" * 20)
    for line in lines:
        say(line)
    say("=" * 57)
    say(f"saved: {saved}")
    say("Review and attest: GAAR_REVIEWER_TOKEN=gaar-test-123 WB_INVESTIGATION_CONFIG="
        f"{workspace / 'operations.json'} python -m streamlit run app_gaar.py --server.port 8502")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
