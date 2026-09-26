"""A constructed bank environment for field agents to collect from (Part 2 demonstration).

The digital twin (governance/twin) decides what happened in each period, including the violations it plants. This
module writes those facts into the kinds of systems a bank has, so field agents have something real to read:
- a git deployment repository: one commit per change, dated when the change ran, with the change's trailers;
- ITSM exports (CSV): tickets, freezes, freeze exceptions, recoveries;
- an IAM privilege-grant export (CSV);
- a host audit log (JSON), the independent population.
The answer keys are sealed as the twin always seals them. Every file is marked constructed.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

import yaml

from governance.twin.generator import generate_period, seal

EMAIL_DOMAIN = "meranti.example"
LISTS = ("allowed_targets", "allowed_actions", "allowed_implementers", "allowed_credentials", "targets")
TABLES = {
    "tickets": ("itsm/tickets.csv", ["ticket_id", "status", "approved_by", "approved_at", "window_start", "window_end",
                                     "allowed_targets", "allowed_actions", "allowed_implementers", "allowed_credentials",
                                     "approved_spec_hash"]),
    "privilege_grants": ("iam/grants.csv", ["grant_id", "actor_id", "credential_id", "approved_by", "approved_at",
                                            "valid_from", "valid_until", "allowed_targets", "allowed_actions"]),
    "freezes": ("itsm/freezes.csv", ["freeze_id", "start", "end", "targets"]),
    "freeze_exceptions": ("itsm/freeze_exceptions.csv", ["freeze_id", "event_id", "approved_by", "approved_at", "reason"]),
    "recoveries": ("itsm/recoveries.csv", ["event_id", "method", "approved_by", "status", "completed_at"]),
}


def _git(repo: Path, *args, env=None):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env={**os.environ, **(env or {})})


def _append(path: Path, columns: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        if new:
            writer.writeheader()
        for row in rows:
            writer.writerow({k: ";".join(v) if isinstance(v, list) else v for k, v in row.items()})


def write_period(systems: Path, generated: dict):
    """Record one twin period in the constructed systems."""
    pkg = generated["changes"]
    repo = systems / "deploy-repo"
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q", "-b", "main")
        (repo / "README.md").write_text("Meranti Bank (constructed) deployment log. CONSTRUCTED_TEST_DATA.\n")
        _git(repo, "add", "README.md")
        _git(repo, "-c", "user.name=setup", "-c", f"user.email=setup@{EMAIL_DOMAIN}", "commit", "-q", "-m", "init",
             env={"GIT_AUTHOR_DATE": "2026-01-01T00:00:00+08:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+08:00"})
    for change in pkg["changes"]:
        message = (f"Deploy {change['asset_id']} for {change['ticket_id']}\n\nChange-Id: {change['event_id']}\n"
                   f"Ticket: {change['ticket_id']}\nAsset: {change['asset_id']}\nActions: {';'.join(change['actions'])}\n"
                   f"Credential: {change['credential_id']}\nSpec: {change['actual_spec_hash']}\nOutcome: {change['outcome']}\n")
        _git(repo, "-c", f"user.name={change['actor_id']}", "-c", f"user.email={change['actor_id']}@{EMAIL_DOMAIN}",
             "commit", "-q", "--allow-empty", "-m", message,
             env={"GIT_AUTHOR_DATE": change["occurred_at"], "GIT_COMMITTER_DATE": change["occurred_at"]})
    for role, (rel, columns) in TABLES.items():
        _append(systems / rel, columns, pkg.get(role) or [])
    audit = systems / "hostaudit" / "events.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    events = json.loads(audit.read_text()) if audit.exists() else []
    times = {c["event_id"]: c["occurred_at"] for c in pkg["changes"]}
    start = pkg["collection"]["period_start"]
    for eid in generated["population"]["independent"]["event_ids"]:
        events.append({"event_id": eid, "seen_at": times.get(eid) or start.replace("T00:00", "T12:00"),
                       "host": "constructed-host", "data_classification": "CONSTRUCTED_TEST_DATA"})
    audit.write_text(json.dumps(events, indent=1))


def mandate(system_id: str) -> dict:
    """The mandate a tower owner would approve for these systems."""
    split = lambda col: {"column": col, "split": ";"}
    table = lambda sid, role, rel, fields: {"source_id": sid, "connector": "table", "role": role, "path": f"systems/{rel}",
                                            "map": {f: split(f) if f in LISTS else f for f in fields}}
    return {
        "mandate_id": f"FM-{system_id}-1", "system_id": system_id,
        "owner": "Payments platform tower (constructed)", "data_classification": "CONSTRUCTED_TEST_DATA",
        "settle_minutes": 30,
        "sources": [
            {"source_id": "deploy-repo", "connector": "git", "role": "changes", "repo": "systems/deploy-repo",
             "branch": "main",
             "map": {"event_id": "Change-Id", "ticket_id": "Ticket", "occurred_at": "committed_at", "asset_id": "Asset",
                     "actor_id": {"column": "author_email", "regex": "^([^@]+)@"}, "credential_id": "Credential",
                     "actions": split("Actions"), "actual_spec_hash": "Spec", "outcome": "Outcome"}},
            {"source_id": "host-audit", "connector": "table", "role": "independent", "path": "systems/hostaudit/events.json",
             "map": {"event_id": "event_id", "occurred_at": "seen_at"}},
            table("itsm-tickets", "tickets", "itsm/tickets.csv", TABLES["tickets"][1]),
            table("iam-grants", "privilege_grants", "iam/grants.csv", TABLES["privilege_grants"][1]),
            table("itsm-freezes", "freezes", "itsm/freezes.csv", TABLES["freezes"][1]),
            table("itsm-freeze-exceptions", "freeze_exceptions", "itsm/freeze_exceptions.csv",
                  TABLES["freeze_exceptions"][1][:4]),
            table("itsm-recoveries", "recoveries", "itsm/recoveries.csv", TABLES["recoveries"][1]),
        ]}


def build_environment(config: dict, root: Path, seed: int = 500) -> dict:
    """Write every period of a constructed series into the systems, seal the keys, and write the mandate."""
    from governance.production import recurring
    from . import mandate as mandate_module
    payload = recurring.verify(config, root)
    if not payload.get("constructed_demo"):
        raise ValueError("the constructed environment is only for a signed constructed-demonstration series")
    systems = Path(root) / "systems"
    if systems.exists():
        raise ValueError(f"{systems} already exists; the environment is written once")
    keys = []
    for i, period in enumerate(payload["periods"]):
        generated = generate_period(seed + i, period["as_of"], scope=payload["system_id"],
                                    cadence_days=payload["cadence_days"])
        write_period(systems, generated)
        keys.append(seal(generated["answer_key"], Path(root) / "twin_keys")["key"])
    mandate_module.path_for(root).write_text(
        "# Collection mandate (constructed demonstration). Approve with: python tools/gaar_field.py approve --by \"<name>\"\n"
        + yaml.safe_dump(mandate(payload["system_id"]), sort_keys=False))
    return {"status": "ENVIRONMENT_READY", "systems": str(systems), "periods": [p["label"] for p in payload["periods"]],
            "keys_sealed": len(keys), "mandate": str(mandate_module.path_for(root)),
            "next": "approve the mandate, then let the scheduler tick: the field agents collect each ended period"}
