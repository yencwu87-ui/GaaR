"""The one scheduler: all machine work runs here, each job isolated, each outcome a signed journal event.

UI invariant (docs/design/inbox_and_scheduler.md): the UI reads journals and hosts signed human actions; all machine
work executes in this scheduler; there is no second execution path.

A tick runs every registered job in order. A job that raises does not stop the others: its failure is journaled as
that job's outcome, and the inbox shows it as work. A job that reaches a governed gate stops there; stopping is what
creates the inbox item (the item is derived from the journals the job wrote, never written by the job itself).
"""
from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path

DEFAULT_INTERVAL_SECONDS = 3600
STALE_AFTER_INTERVALS = 2


def _folder(root: Path) -> Path:
    return Path(root) / "scheduler"


def journal_for(config: dict, root: Path):
    from .journal import Journal
    path = _folder(root) / "operations.sqlite"
    return Journal(path, config["trusted_keys"]) if path.exists() else None


# ---------------------------------------------------------------------------------------------------------
# Jobs. Each takes the tick context and returns a small, JSON-serialisable outcome with a "status".
# ---------------------------------------------------------------------------------------------------------

def job_series(ctx: dict) -> dict:
    """The standing-authorisation series: run arrived periods, rerun records blocked only by an upgrade (U1)."""
    from . import recurring
    if not ctx["config"].get("standing_authorisation"):
        return {"status": "NOT_CONFIGURED", "detail": "no standing authorisation in this workspace"}
    try:
        summary = recurring.tick(ctx["config"], ctx["root"], now=ctx["now"])
    except recurring.SchedulerBusy:
        return {"status": "SKIPPED_BUSY", "detail": "another series check was running"}
    periods = [{"label": s["label"], "state": s["state"], "verdict": s.get("verdict"),
                "ran": bool(s.get("ran")), "superseded": bool(s.get("superseded")),
                "rerun_failed": s.get("rerun_failed")} for s in summary]
    failed = [p for p in periods if p["rerun_failed"]]
    return {"status": "FAILED" if failed else "OK", "periods": periods,
            "stopped_at_gate": [p["label"] for p in periods if p["state"] == "AWAITING_ATTESTATION"],
            **({"error": "; ".join(p["rerun_failed"] for p in failed)} if failed else {})}


def job_gate_status(ctx: dict) -> dict:
    """The live gate-status report the status line reads. Live, not evidence: evidence is a frozen pack."""
    from . import gate_status
    report = gate_status.generate(str(ctx["config_path"]))
    target = _folder(ctx["root"]) / "gate_status.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    return {"status": "OK", "body_sha256": report["body_sha256"],
            "gates": {g["gate"]: g["state"] for g in report["gates"]}}


def job_watcher(ctx: dict) -> dict:
    """Regulatory watch: each subscribed source is checked when due (every 8 hours by default)."""
    from governance.watcher import intel
    if not intel.configured():
        return {"status": "NOT_CONFIGURED", "detail": "no watch subscriptions; run tools/gaar_watch.py setup"}
    result = intel.run_due()
    return {"status": "OK", "scanned": [s["source_id"] for s in result["scanned"]], "not_due": result["not_due"],
            "sources_failing": [f["source_id"] for f in result["failed"]],
            "new_publications": sum(s["new"] for s in result["scanned"])}


def job_field(ctx: dict) -> dict:
    """Field agents (Part 2): collect ended periods' evidence from the systems under the approved mandate."""
    from governance.field import builder
    if not ctx["config"].get("standing_authorisation"):
        return {"status": "NOT_CONFIGURED", "detail": "no standing authorisation in this workspace"}
    return builder.run(ctx["config"], ctx["root"], now=ctx["now"])


# field runs before series, so evidence it delivers is assessed in the same tick
JOBS = [("field", job_field), ("series", job_series), ("watcher", job_watcher), ("gate_status", job_gate_status)]


# ---------------------------------------------------------------------------------------------------------

class SchedulerBusy(RuntimeError):
    pass


def tick(config_path, now: datetime | None = None, jobs=None, interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> dict:
    from governance.operations.runtime import load, signers_for
    config_path = Path(config_path).expanduser().resolve()
    config, root = load(config_path)
    folder = _folder(root)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(folder / "tick.lock", "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SchedulerBusy("another scheduler tick is running on this workspace")
    try:
        from .journal import Journal
        executor = signers_for(config, root)["executor"]
        journal = Journal(folder / "operations.sqlite", config["trusted_keys"])
        started = datetime.now().astimezone()
        tick_id = started.isoformat()
        ctx = {"config": config, "root": root, "config_path": config_path, "now": now}
        results = {}
        for name, job in (jobs if jobs is not None else JOBS):
            try:
                outcome = job(ctx)
            except Exception as exc:                            # isolation: one job's crash is its own outcome
                outcome = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"[:500]}
            outcome = json.loads(json.dumps(outcome, default=str))
            event = journal.append(f"{tick_id}:{name}", "job_outcome", {"tick": tick_id, "job": name, **outcome},
                                   executor, "executor")
            results[name] = {**outcome, "event_hash": event["event_hash"]}
        finished = datetime.now().astimezone()
        journal.append(f"{tick_id}:tick", "scheduler_tick",
                       {"tick": tick_id, "started_at": tick_id, "finished_at": finished.isoformat(),
                        "interval_seconds": interval_seconds, "simulated_clock": now.isoformat() if now else None,
                        "jobs": {n: r["status"] for n, r in results.items()}}, executor, "executor")
        return {"status": "TICKED", "tick": tick_id, "jobs": results}
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def status(config: dict, root: Path, now: datetime | None = None) -> dict:
    """Is the scheduler alive? An empty inbox is only meaningful if it is."""
    now = now or datetime.now().astimezone()
    journal = journal_for(config, root)
    events = journal.read() if journal else []
    ticks = [e for e in events if e["kind"] == "scheduler_tick"]
    if not ticks:
        return {"state": "NEVER_RAN", "last_tick": None, "jobs": {}}
    last = ticks[-1]["payload"]
    finished = datetime.fromisoformat(last["finished_at"])
    interval = last.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS
    age = (now - finished).total_seconds()
    outcomes = {e["payload"]["job"]: {**e["payload"], "event_hash": e["event_hash"]}
                for e in events if e["kind"] == "job_outcome" and e["payload"]["tick"] == last["tick"]}
    return {"state": "STALE" if age > STALE_AFTER_INTERVALS * interval else "ALIVE", "last_tick": last,
            "age_seconds": max(0, int(age)), "interval_seconds": interval, "jobs": outcomes,
            "tick_event_hash": ticks[-1]["event_hash"]}


def since(seconds: int) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)} min ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)} h ago"
    return f"{round(seconds / 86400)} days ago"
