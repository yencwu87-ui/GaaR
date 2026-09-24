"""The inbox: what needs a person, derived from signed journals, read-only.

Nothing here executes machine work or writes an event (UI invariant, docs/design/inbox_and_scheduler.md). Every item
names the journal event it comes from and its age. Aging is signed policy, not a UI preference:

- an attestation is due within one cadence of its record becoming ready (the series' cadence_days, signed in the
  standing authorisation); past that it is overdue, and the inbox says so first;
- missing exports are overdue after the signed grace_days (the existing rule, unchanged).

System items come first, because while one is open an empty or short inbox cannot be trusted: the scheduler has
never run, has stopped (stale), or a job failed; or the series no longer matches what was signed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import recurring, scheduler

HUMAN, SYSTEM = "HUMAN", "SYSTEM"


def _when(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.astimezone()


def _rel(root: Path, path: Path) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)


def _system_items(config, root, now, config_path) -> list[dict]:
    items = []
    health = scheduler.status(config, root, now)
    tick_cmd = f"python tools/gaar_scheduler.py tick --config {config_path}"
    if health["state"] == "NEVER_RAN":
        items.append({"id": "scheduler:never", "who": SYSTEM, "kind": "scheduler",
                      "title": "The scheduler has never run for this workspace",
                      "why": "No machine work has been checked, so an empty inbox would mean nothing, not nothing to do.",
                      "action": tick_cmd, "origin": None})
        return items
    if health["state"] == "STALE":
        items.append({"id": "scheduler:stale", "who": SYSTEM, "kind": "scheduler",
                      "title": f"The scheduler last ran {scheduler.since(health['age_seconds'])} "
                               f"(expected every {health['interval_seconds'] // 60} min)",
                      "why": "Nothing new is being checked while it is stopped; the inbox shows only what it last saw.",
                      "action": tick_cmd + "   (or reload its launchd job)",
                      "origin": {"journal": "scheduler/operations.sqlite", "event_hash": health["tick_event_hash"]}})
    for name, outcome in health["jobs"].items():
        if outcome["status"] == "FAILED":
            items.append({"id": f"job:{name}", "who": SYSTEM, "kind": "job_failed",
                          "title": f"Scheduler job '{name}' failed",
                          "why": outcome.get("error", "no error recorded"),
                          "action": "Fix the cause; the next tick retries. Other jobs were not affected.",
                          "origin": {"journal": "scheduler/operations.sqlite", "event_hash": outcome["event_hash"]}})
    return items


def _upgrade_parts(config, journal) -> list[str]:
    """Read-only: which bound software parts differ from what this record was produced under."""
    from .qualification import fingerprint
    binding = journal.latest("binding")
    if not binding:
        return []
    bound, current = binding["payload"]["fingerprint"], fingerprint(config)
    return sorted(k for k in set(bound) | set(current) if bound.get(k) != current.get(k))


def _series_items(config, root, now) -> list[dict]:
    if not config.get("standing_authorisation"):
        return []
    try:
        payload = recurring.verify(config, root)
    except Exception as exc:
        return [{"id": "series:refused", "who": SYSTEM, "kind": "series_refused",
                 "title": "The series no longer matches what was signed", "why": str(exc),
                 "action": "Find out what changed. A new value means a new authorisation (policy §4).", "origin": None}]
    items, cadence = [], timedelta(days=payload["cadence_days"])
    rule = f"within one cadence ({payload['cadence_days']} days, signed in {payload['authorisation_id']}) of the record becoming ready"
    for period in payload["periods"]:
        state = recurring.period_state(config, root, period, now)
        journal = recurring._journal(config, root, period["investigation_id"])
        events = journal.read() if journal else []
        journal_path = _rel(root, recurring._case(config, root, period["investigation_id"]) / "operations.sqlite")
        for event in events:
            if event["kind"] == "integrity_event":
                item = event["payload"]
                items.append({"id": f"integrity:{event['event_hash'][:12]}", "who": HUMAN, "kind": "investigate",
                              "title": f"Integrity event on {period['label']}: {item['finding']}",
                              "why": f"Rule {item['rule']}. The delivery was moved, untouched, to {item['quarantined_to']}.",
                              "action": "Find out who produced it and why (runbook E1).",
                              "investigation_id": period["investigation_id"], "since": event["at"],
                              "origin": {"journal": journal_path, "event_hash": event["event_hash"]}})
        if state["state"] == "AWAITING_ATTESTATION":
            report = next(e for e in events if e["event_key"] == "deterministic_run_report")
            ready = _when(report["at"])
            due = ready + cadence
            parts = _upgrade_parts(config, journal)
            items.append({"id": f"attest:{period['label']}", "who": HUMAN, "kind": "attest",
                          "title": f"Attest {period['label']}: {state['verdict']}",
                          "why": ("Blocked: the software was upgraded after this record. The scheduler reruns it "
                                  "on its next tick (runbook U1); nothing to sign until then."
                                  if parts else "A deterministic record is ready and awaits your attestation."),
                          "action": "Open it, read the reconciliation, sign or decline.",
                          "investigation_id": period["investigation_id"], "since": report["at"],
                          "due": due.isoformat(), "due_rule": rule, "overdue": now > due, "blocked": parts or None,
                          "origin": {"journal": journal_path, "event_hash": report["event_hash"]}})
        elif state["state"] == "OVERDUE":
            items.append({"id": f"overdue:{period['label']}", "who": HUMAN, "kind": "chase",
                          "title": f"Evidence for {period['label']} overdue by {state['overdue_days']} day(s)",
                          "why": "Missing: " + (", ".join(state["missing_files"]) or "the exports"),
                          "action": "Chase the exports from their owners. Nothing can be assessed until they arrive.",
                          "investigation_id": period["investigation_id"], "overdue": True,
                          "due_rule": f"grace {payload['grace_days']} day(s) after the period ends, signed in "
                                      f"{payload['authorisation_id']}",
                          "origin": {"authorisation": payload["authorisation_id"], "period": period["label"]}})
    return items


def _watch_items(now) -> list[dict]:
    """Regulatory watch: failing sources are system work; untriaged P1/P2 intel is a person's work."""
    from governance.watcher import intel
    if not intel.configured():
        return []
    found = []
    for h in intel.health(now=now):
        if h["state"] in ("FAILING", "OVERDUE"):
            found.append({"id": f"watch:{h['source_id']}", "who": SYSTEM, "kind": "watch_source",
                          "title": f"Regulatory watch cannot check {h['source_id']}" if h["state"] == "FAILING"
                                   else f"Regulatory watch has not checked {h['source_id']} on schedule",
                          "why": (h["error"] or "no successful check within two intervals")
                                 + f" · {h['consecutive_failures']} failed attempt(s) in a row"
                                 + (f" since {h['failing_since'][:16]}" if h.get("failing_since") else "")
                                 + (f" · last success {h['last_success'][:16]}" if h["last_success"] else " · never succeeded"),
                          "action": "Until this is fixed, 'no new publications' from this source means nothing. "
                                    "Retries run automatically; if it keeps failing, check the source page or unsubscribe.",
                          "origin": {"watch_source": h["source_id"]}})
    rules = intel.subscriptions()["triage_due_days"]
    for i in intel.needs_triage(now=now):
        since = _when(i["first_seen"])
        due = since + timedelta(days=rules[i["priority"]])
        controls = ", ".join(f"{m['framework']} {m['control_id']}" for m in i.get("matched_controls") or [])
        found.append({"id": f"intel:{i['item_id']}", "who": HUMAN, "kind": "triage", "intel_item_id": i["item_id"],
                      "title": f"{i['priority']} · {i['title']}",
                      "why": ("Likely touches " + controls + ". " if controls else "")
                             + {"CONSULTATION": "Consultation: a future obligation.", "INSTRUMENT": "Instrument: may apply now.",
                                "THREAT_DIGEST": "New actively exploited vulnerabilities."}.get(i["kind"], ""),
                      "action": "Open it and mark it relevant, not relevant, or keep watching.",
                      "since": i["first_seen"], "due": due.isoformat(),
                      "due_rule": f"{i['priority']} triage within {rules[i['priority']]} day(s) (watch subscriptions)",
                      "overdue": now > due, "origin": {"watch_item": i["item_id"], "source": i["source_id"]}})
    return found


def items(config_path, now: datetime | None = None) -> list[dict]:
    from governance.operations.runtime import load
    config_path = Path(config_path).expanduser().resolve()
    config, root = load(config_path)
    now = now or datetime.now().astimezone()
    found = _system_items(config, root, now, config_path) + _series_items(config, root, now) + _watch_items(now)
    for item in found:
        if item.get("since"):
            item["age_days"] = round((now - _when(item["since"])).total_seconds() / 86400, 1)
    # System first (they decide whether the rest can be trusted), then overdue, then oldest first.
    return sorted(found, key=lambda i: (i["who"] != SYSTEM, not i.get("overdue"), -(i.get("age_days") or 0)))


def status_line(config_path, now: datetime | None = None, found: list[dict] | None = None) -> dict:
    """Reports governance; is not governance. Derived from the scheduler's gate report and the journals."""
    import json
    from governance.operations.runtime import load
    config_path = Path(config_path).expanduser().resolve()
    config, root = load(config_path)
    now = now or datetime.now().astimezone()
    found = items(config_path, now) if found is None else found
    parts = []
    report_path = Path(root) / "scheduler" / "gate_status.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    if report:
        states = [g["state"] for g in report["gates"] if g["state"] != "NOT_APPLICABLE"]
        counts = [f"{states.count(s)} {s.lower()}" for s in ("HELD", "PARTIAL", "OPEN") if states.count(s)]
        parts.append(f"Gates: {', '.join(counts)}")
    else:
        parts.append("Gates: no report yet")
    human = [i for i in found if i["who"] == HUMAN]
    overdue = sum(bool(i.get("overdue")) for i in human)
    parts.append(f"{len(human)} item(s) waiting" + (f" ({overdue} overdue)" if overdue else ""))
    health = scheduler.status(config, root, now)
    covered = [name for name, outcome in health.get("jobs", {}).items() if outcome.get("status") != "NOT_CONFIGURED"]
    parts.append("scheduler has never run" if health["state"] == "NEVER_RAN" else
                 f"scheduler last ran {scheduler.since(health['age_seconds'])}"
                 + (" — STALE" if health["state"] == "STALE" else "")
                 + (f" (covers {', '.join(covered)})" if covered else ""))
    help_text = ("It covers only the jobs named; anything else (for example the classic workbench's own Watcher tab) "
                 "is outside it. "
                 "This line reports gate state; it is not the gates. It is derived from the gate-status report the "
                 "scheduler generates"
                 + (f" (content hash {report['body_sha256'][:12]}, as of {report['as_of'][:19]})" if report else "")
                 + " and from the signed journals, never typed in by hand. Verify a report with "
                   "`python tools/gaar_gate_status.py verify --report <file>`.")
    return {"text": " · ".join(parts), "help": help_text, "scheduler": health["state"]}
