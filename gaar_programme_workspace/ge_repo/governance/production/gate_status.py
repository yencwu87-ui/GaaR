"""Gate-status report — how each quality-policy gate is held at a given moment (quality policy §2, D16).

The policy states rules and is pinned by hash, so it cannot carry status that events change. This report does.
It is generated, never hand-edited, and every statement in it is derived from an input named in its derivation
receipt: each file by hash, each case journal by its head at the report's moment. A live report is evaluated as
of its own generation time, so it can be regenerated and checked later: events after that moment cannot change it.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from governance.investigation.store import digest
from . import policy_approval as pa

PACKAGE = pa.PACKAGE
REGISTER = PACKAGE / "docs/quality/unexercised_guards.md"
RUNS = PACKAGE / ".test_runs"
PACKS = PACKAGE / "adversarial"
GENERATOR = Path(__file__)
GATES = ("Independent mapping review", "Procedure completeness", "A refusal or integrity rule", "Policy approval",
         "A valid test run", "Collection completeness", "Attestation quality")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    path = Path(path)
    return str(path.relative_to(PACKAGE)) if path.is_relative_to(PACKAGE) else str(path)


def _when(text):
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        moment = datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%S%z")
    return moment if moment.tzinfo else moment.astimezone()


def _latest_record(prefix_trace: bool, moment, inputs):
    if not RUNS.is_dir():
        return None
    chosen = None
    for path in sorted(RUNS.glob("*.json")):
        if path.name.startswith("trace-") != prefix_trace:
            continue
        record = json.loads(path.read_text())
        if _when(record["at"]) <= moment and (chosen is None or _when(record["at"]) > _when(chosen[1]["at"])):
            chosen = (path, record)
    if chosen:
        inputs.append({"kind": "trace record" if prefix_trace else "test run record", "path": _rel(chosen[0]),
                       "sha256": _sha(chosen[0])})
    return chosen[1] if chosen else None


def _register(inputs):
    if not REGISTER.exists():
        return {"entries": 0, "summary": "no register"}
    inputs.append({"kind": "guard register", "path": _rel(REGISTER), "sha256": _sha(REGISTER)})
    text = REGISTER.read_text()
    summary = re.search(r"^Summary: (.+)$", text, re.M)
    rows = [line for line in text.splitlines() if line.startswith("| ") and "Disposition" not in line
            and not set(line.replace("|", "").strip()) <= set("-")]
    return {"entries": len(rows), "summary": summary.group(1).strip() if summary else "no summary line",
            "test_required": sum("| Test required |" in r for r in rows),
            "pending_external_review": sum("pending external review" in r.lower() for r in rows)}


def _journal_events(config, case_dir, moment, inputs):
    path = Path(case_dir) / "operations.sqlite"
    if not path.is_file():
        return []
    from .journal import Journal
    events = [e for e in Journal(path, config["trusted_keys"]).read() if _when(e["at"]) <= moment]
    inputs.append({"kind": "case journal", "path": _rel(path), "head": events[-1]["event_hash"] if events else None,
                   "events_up_to_moment": len(events)})
    return events


def generate(config_path=None, as_of=None) -> dict:
    generated_at = datetime.now().astimezone()
    moment = _when(as_of) if as_of else generated_at
    inputs, gates = [], {}

    identity = pa.policy_identity(pa.POLICY)
    inputs.append({"kind": "governing policy", "path": identity["policy_path"], "sha256": identity["policy_sha256"]})
    approvals = []
    for path in sorted(pa.APPROVALS.glob("*.approval.json")) if pa.APPROVALS.is_dir() else []:
        try:
            payload = pa.verify(pa.load(path), pa.POLICY)
        except Exception:
            continue                                        # an approval of another text does not cover this one
        if _when(payload["approved_at"]) <= moment:         # only what existed at the report's moment
            inputs.append({"kind": "policy approval", "path": _rel(path), "sha256": _sha(path)})
            approvals.append(payload["approver"])
    gates["Policy approval"] = (("HELD", f"policy {identity['policy_version']} ({identity['policy_sha256'][:12]}) "
                                          f"approved by {', '.join(approvals)}") if approvals else
                                ("OPEN", f"no approval covers policy {identity['policy_version']} "
                                         f"({identity['policy_sha256'][:12]}) at this moment"))

    run = _latest_record(False, moment, inputs)
    if run is None:
        gates["A valid test run"] = ("OPEN", "no canonical test run record at this moment")
    elif run.get("verdict") == "ENVIRONMENT NOT READY":
        # D27 (v28 round): this record stops before any test and has no pass counts; reading them crashed the report
        gates["A valid test run"] = ("OPEN", f"the latest run stopped before any test: environment not ready "
                                             f"({len(run.get('environment_missing') or [])} package(s) missing "
                                             f"in {run.get('conda_env') or run.get('python') or 'an unnamed environment'}), "
                                             f"at {run['at']}")
    else:
        ok = run.get("verdict") == "COMPLETE RUN, ALL PASSED" and not run.get("environment_missing")
        gates["A valid test run"] = ("HELD" if ok else "OPEN",
                                     f"{run.get('verdict')}: {run.get('collected', 0)} collected, "
                                     f"{run.get('passed', 0)} passed, {run.get('skipped', 0)} skipped, at {run['at']}")

    trace = _latest_record(True, moment, inputs)
    register = _register(inputs)
    if trace is None:
        gates["A refusal or integrity rule"] = ("OPEN", "no guard trace record at this moment")
    else:
        state = "PARTIAL" if trace["verdict"] == "PASS" and trace["unreached"] else (
            "HELD" if trace["verdict"] == "PASS" else "OPEN")
        gates["A refusal or integrity rule"] = (state, f"trace {trace['verdict']}: {trace['unreached']} refusal lines "
                                                       f"unreached, {trace['registered']} registered; register: "
                                                       f"{register['summary']}")

    packs = [p for p in sorted(PACKS.glob("*/result.json")) if PACKS.is_dir()
             and _when(json.loads(p.read_text())["run_at"]) <= moment]
    for path in packs:
        inputs.append({"kind": "adversarial pack result", "path": _rel(path), "sha256": _sha(path)})
    gates["Procedure completeness"] = (("PARTIAL", f"{len(packs)} adversarial pack result(s) recorded")
                                       if packs else ("OPEN", "no adversarial pack has been run"))

    series_id = None
    if config_path:
        from governance.operations.runtime import load
        from . import recurring
        config, root = load(Path(config_path).expanduser())
        inputs.append({"kind": "workspace configuration", "path": _rel(Path(config_path).expanduser().resolve()),
                       "sha256": _sha(Path(config_path).expanduser().resolve())})
        reference = (config.get("reconciliation_mapping_document") or {}).get("review")
        if reference:
            review_path = Path(reference["path"])
            inputs.append({"kind": "mapping review", "path": _rel(review_path), "sha256": _sha(review_path)})
            review = json.loads(review_path.read_text())["payload"]
            if _when(review["reviewed_at"]) <= moment:
                gates["Independent mapping review"] = (
                    "HELD" if review["outcome"] == "AGREED" else "OPEN",
                    f"{review['outcome']} by {review['reviewer']} (key proxy for person; see policy §10)")
        gates.setdefault("Independent mapping review", ("OPEN", "no review of this series' mapping at this moment"))
        if config.get("standing_authorisation"):
            payload = recurring.load(config, root)["payload"]
            series_id = payload["authorisation_id"]
            due = assessed = warned = attested = 0
            simulated = []
            grace_days = config["periodic_evidence"].get("grace_days", 2)
            from datetime import timedelta
            for period in payload["periods"]:
                events = _journal_events(config, recurring._case(config, root, period["investigation_id"]), moment, inputs)
                if _when(period["as_of"]) + timedelta(days=grace_days) <= moment:
                    due += 1
                if any(e["event_key"] == "deterministic_run_report" for e in events):
                    assessed += 1
                simulated += [e["payload"]["clock_simulated"] for e in events
                              if isinstance(e.get("payload"), dict) and e["payload"].get("clock_simulated")]
                for e in events:
                    if e["kind"] == "pilot_attestation":
                        attested += 1
                        warned += bool(e["payload"]["attestation"].get("rationale_warnings"))
            gates["Collection completeness"] = (
                ("HELD" if assessed >= due else "PARTIAL"),
                f"{assessed} period(s) assessed, {due} due (grace {grace_days} day(s)); shown, not enforced"
                + (f"; constructed demonstration: periods assessed on a simulated clock (latest {max(simulated, key=_when)}), "
                   "so a period can be assessed before it is due by the report's own time" if simulated else ""))
            gates["Attestation quality"] = ("HELD" if attested else "OPEN",
                                            f"{attested} attestation(s), {warned} carrying a rationale warning; "
                                            "warnings recorded, their review is a procedure")
    for gate in GATES:
        gates.setdefault(gate, ("NOT_APPLICABLE", "evaluated per series: pass --config"))

    body = {"report": "gate_status", "format": 1, "policy": identity, "series": series_id,
            "as_of": moment.isoformat(), "live": as_of is None,
            "gates": [{"gate": g, "state": gates[g][0], "evidence": gates[g][1]} for g in GATES],
            "guard_register": register}
    receipt = {"generated_at": generated_at.isoformat(), "generator": _rel(GENERATOR),
               "generator_sha256": _sha(GENERATOR), "config": str(config_path) if config_path else None,
               "inputs": inputs}
    return {**body, "body_sha256": digest(body), "derivation_receipt": receipt}


def verify(report: dict) -> dict:
    """Regenerate from the inputs the receipt names, as of the report's moment, and compare."""
    receipt = report.get("derivation_receipt")
    if not receipt:
        return {"valid": False, "reason": "no derivation receipt: this is not a gate-status report"}
    if receipt["generator_sha256"] != _sha(GENERATOR):
        return {"valid": False, "reason": "generated by a different version of the generator"}
    again = generate(receipt["config"], report["as_of"])
    body = {k: report.get(k) for k in ("report", "format", "policy", "series", "as_of", "live", "gates", "guard_register")}
    if digest(body) != report["body_sha256"]:
        return {"valid": False, "reason": "the report's content does not match its own hash: it was edited"}
    if [g for g in again["gates"]] != report["gates"] or again["guard_register"] != report["guard_register"]:
        return {"valid": False, "reason": "regenerating from the named inputs gives a different result"}
    if again["derivation_receipt"]["inputs"] != receipt["inputs"]:
        return {"valid": False, "reason": "an input named in the receipt has changed"}
    return {"valid": True, "reason": "regenerated from the named inputs as of the report's moment: identical"}


def render_markdown(report: dict) -> str:
    receipt = report["derivation_receipt"]
    lines = [f"# Gate status — policy {report['policy']['policy_version']} ({report['policy']['policy_sha256'][:12]})",
             "", f"As of **{report['as_of']}**" + (" (live)" if report["live"] else " (historical)")
             + (f" · series **{report['series']}**" if report["series"] else ""),
             "", "Generated by the gate-status tool. Never edit by hand; verify with "
             "`python tools/gaar_gate_status.py verify --report <file>`.", "",
             "| Gate | State | Evidence |", "|---|---|---|"]
    lines += [f"| {g['gate']} | {g['state']} | {g['evidence']} |" for g in report["gates"]]
    reg = report["guard_register"]
    lines += ["", f"**Guard register:** {reg['summary']}", "", "## Derivation receipt", "",
              f"Generated {receipt['generated_at']} by `{receipt['generator']}` ({receipt['generator_sha256'][:12]}); "
              f"content hash {report['body_sha256'][:12]}.", "", "| Input | Path | Hash or head |", "|---|---|---|"]
    lines += [f"| {i['kind']} | `{i['path']}` | {(i.get('sha256') or i.get('head') or '—')[:16]} |"
              for i in receipt["inputs"]]
    return "\n".join(lines) + "\n"
