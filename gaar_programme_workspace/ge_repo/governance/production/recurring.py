"""Recurring results — the "as a service" part of result-as-a-service.

What a human signs, once
------------------------
A standing authorisation: this control, for this system, over these named
periods, from these sources, reconciled with this mapping, with the evidence
arriving in this inbox layout. Owner and governance sign it. At the same time
they sign the opening two stages of every period's investigation, so each
period is a genuinely authorised investigation from the start. The scheduler
can run what was signed; it cannot create anything that was not.

What the scheduler does, repeatedly
-----------------------------------
For each authorised period, in order: if its evidence has arrived and it has
no result yet, run it (deterministic procedures, D8, completion). Then compare
it with the previous period's result and record what changed, in a signed
journal event. Nothing is sent anywhere; the reviewer sees each new result in
the app, marked as awaiting attestation.

What stays with a person
------------------------
Signing the standing authorisation, and attesting each period's result.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from governance.investigation.store import canonical, digest
from governance.result_contract import verify_signature

DELTA = "period_delta"


ID_SCHEME = "SA2"


def authorisation_id_inputs(**inputs) -> dict:
    """Everything that makes one authorisation different from another, plus a nonce.

    The id is written into every period's signed opening stage, so it must be
    derived before signing, from inputs rather than from the finished document.
    The nonce makes two separate signing acts with identical inputs two distinct
    authorisations: "which authorisation authorised this result?" has one answer.
    """
    return {"scheme": ID_SCHEME, **inputs}


def authorisation_id(inputs: dict) -> str:
    return f"{ID_SCHEME}-" + digest(inputs)[:16]


def plan_periods(first_end: str, cadence_days: int, count: int, prefix: str) -> list[dict]:
    first = datetime.fromisoformat(first_end)
    if first.tzinfo is None:
        raise ValueError("period end must carry a timezone")
    periods = []
    for index in range(count):
        end = first + timedelta(days=cadence_days * index)
        label = end.date().isoformat()
        periods.append({"label": label, "as_of": end.isoformat(), "investigation_id": f"{prefix}-{label}"})
    return periods


def load(config: dict, root: Path) -> dict:
    return json.loads((Path(root) / config["standing_authorisation"]).read_text())


def verify(config: dict, root: Path) -> dict:
    """Signatures, and that the configuration still matches what was signed."""
    document = load(config, root)
    payload = document["payload"]
    for role in ("owner", "governance"):
        signature = next((s for s in document["signatures"] if s["role"] == role), None)
        if not signature:
            raise ValueError(f"standing authorisation lacks the {role} signature")
        policy = config["trusted_keys"].get(signature["key_id"], {})
        if role not in policy.get("roles", []) or policy.get("actor_type") != "human":
            raise ValueError(f"standing authorisation {role} signature is not from a trusted human {role}")
        if not verify_signature(policy["public_key"], signature["signature"], canonical(payload).encode()):
            raise ValueError(f"standing authorisation {role} signature is invalid")
    inputs = payload.get("authorisation_id_inputs")
    if inputs is not None:                     # scheme SA2; older SA- authorisations carry no inputs and still resolve
        if authorisation_id(inputs) != payload["authorisation_id"]:
            raise ValueError("the authorisation id does not match the inputs it was derived from")
        checks = {"control": payload["control_id"], "system_id": payload["system_id"],
                  "periods": [p["as_of"] for p in payload["periods"]], "mapping_sha256": payload["mapping_sha256"],
                  "mapping_document_sha256": payload.get("mapping_document_sha256")}
        for key, value in checks.items():
            if inputs.get(key) != value:
                raise ValueError(f"the authorisation id was derived from a different {key}")
    control = payload["control_id"]
    if payload["mapping_sha256"] != digest((config.get("reconciliation_map") or {}).get(control)):
        raise ValueError("reconciliation mapping differs from the signed standing authorisation")
    layout = config.get("periodic_evidence") or {}
    if {p["as_of"]: p["label"] for p in payload["periods"]} != layout.get("periods"):
        raise ValueError("periodic evidence layout differs from the signed standing authorisation")
    if [(e["evidence_id"], e["file"]) for e in layout.get("evidence", [])] != [tuple(x) for x in payload["evidence_layout"]]:
        raise ValueError("evidence file layout differs from the signed standing authorisation")
    for period in payload["periods"]:
        if config.get("expected_heads", {}).get(period["investigation_id"]) != period["initial_head"]:
            raise ValueError(f"{period['investigation_id']} is not the investigation that was signed")
    if payload.get("mapping_document_sha256"):
        reference = config.get("reconciliation_mapping_document") or {}
        try:
            document = json.loads(Path(reference["path"]).read_text())
        except (KeyError, OSError, ValueError):
            raise ValueError("the signed mapping document pinned by the standing authorisation is missing") from None
        if digest(document) != payload["mapping_document_sha256"]:
            raise ValueError("the signed mapping document differs from the one the standing authorisation pins")
    if "grace_days" in payload and payload["grace_days"] != config["periodic_evidence"].get("grace_days", 2):
        raise ValueError("the overdue grace period differs from the signed standing authorisation")
    if "slack_minutes" in payload and payload["slack_minutes"] != config["periodic_evidence"].get("slack_minutes", 10):
        raise ValueError("the arrival slack window differs from the signed standing authorisation")
    if payload.get("governing_policy_sha256"):
        from . import policy_approval as pa
        if pa.policy_identity()["policy_sha256"] != payload["governing_policy_sha256"]:
            raise ValueError("the governing policy text has changed since this series was authorised (runbook U1)")
        reference = config.get("governing_policy") or {}
        try:
            approval = pa.load(reference["approval_path"])
        except (KeyError, OSError, ValueError):
            raise ValueError("the policy approval pinned by the standing authorisation is missing") from None
        if pa.approval_sha256(approval) != payload.get("governing_policy_approval_sha256"):
            raise ValueError("the policy approval differs from the one the standing authorisation pins")
        pa.verify(approval)
    if payload.get("mapping_review_sha256"):
        review_ref = (config.get("reconciliation_mapping_document") or {}).get("review") or {}
        try:
            review = json.loads(Path(review_ref["path"]).read_text())
        except (KeyError, OSError, ValueError):
            raise ValueError("the mapping review pinned by the standing authorisation is missing") from None
        if digest(review) != payload["mapping_review_sha256"]:
            raise ValueError("the mapping review differs from the one the standing authorisation pins")
    if payload.get("model_stages") != config.get("model_stages"):
        raise ValueError("model-stage setting differs from the signed standing authorisation")
    return payload


def _case(config, root, iid):
    from .orchestrator import case_directory
    return case_directory(config, root, iid)


def _journal(config, root, iid):
    from .journal import Journal
    path = _case(config, root, iid) / "operations.sqlite"
    return Journal(path, config["trusted_keys"]) if path.exists() else None


def _record(journal):
    if journal is None:
        return None
    event = next((e for e in journal.read() if e["event_key"] == "deterministic_run_report"), None)
    return event["payload"] if event else None


def _arrival(config, root, period, arrived, now):
    from governance.operations.runtime import arrival_problem
    now = now or datetime.now().astimezone()
    folder = Path(root) / config["periodic_evidence"]["inbox"] / period["label"]
    slack = config["periodic_evidence"].get("slack_minutes", 10)
    problems = set()
    for name in arrived:
        try:
            package = json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        problem = arrival_problem(package if isinstance(package, dict) else {}, period["as_of"], now, slack)
        if problem:
            problems.add(problem)
    if "PREMATURE_COMPLETE" in problems:
        return "PREMATURE_EXPORT"
    if "EARLY_PARTIAL" in problems:
        return "EARLY_PARTIAL"
    return None


def quarantine(config, root, period, executor, now) -> dict:
    """Move a premature-complete delivery aside, untouched, and record it as a signed integrity event."""
    import shutil
    from .journal import Journal
    inbox = Path(root) / config["periodic_evidence"]["inbox"]
    source = inbox / period["label"]
    stamp = now.strftime("%Y%m%dT%H%M%S%z")
    target = inbox / "_quarantine" / f"{period['label']}-{stamp}"
    target.parent.mkdir(parents=True, exist_ok=True)
    files = {}
    import hashlib
    for path in sorted(source.iterdir()):
        if path.is_file():
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    shutil.move(str(source), str(target))
    case = _case(config, root, period["investigation_id"])
    case.mkdir(parents=True, exist_ok=True)
    event = {"investigation_id": period["investigation_id"], "rule": "D14 / runbook E1",
             "finding": "an export declared complete collection for a period that had not ended",
             "period_end": period["as_of"], "detected_at": now.isoformat(), "files_sha256": files,
             "quarantined_to": str(target.relative_to(Path(root)))}
    Journal(case / "operations.sqlite", config["trusted_keys"]).append(
        "integrity_event-" + stamp, "integrity_event", event, executor, "executor")
    return event


def period_state(config, root, period, now=None) -> dict:
    journal = _journal(config, root, period["investigation_id"])
    record = _record(journal)
    folder = Path(root) / config["periodic_evidence"]["inbox"] / period["label"]
    files = [item["file"] for item in config["periodic_evidence"]["evidence"]]
    arrived = [f for f in files if (folder / f).is_file()]
    attestation = journal.latest("pilot_attestation") if journal else None
    if attestation:
        state = "ATTESTED"
    elif record:
        state = "AWAITING_ATTESTATION"
    elif arrived and _arrival(config, root, period, arrived, now):
        state = _arrival(config, root, period, arrived, now)       # D14: PREMATURE_EXPORT or EARLY_PARTIAL
    elif len(arrived) == len(files):
        state = "EVIDENCE_READY"
    else:
        # "Week 3 has not happened yet" and "week 3 did not arrive" must never look the same.
        now = now or datetime.now().astimezone()
        ends = datetime.fromisoformat(period["as_of"])
        grace = timedelta(days=config["periodic_evidence"].get("grace_days", 2))
        if now < ends:
            state = "NOT_YET_DUE"
        elif now > ends + grace:
            state = "OVERDUE"
        else:
            state = "EVIDENCE_INCOMPLETE" if arrived else "AWAITING_EVIDENCE"
    overdue_days = None
    if state == "OVERDUE":
        overdue_days = (now - (datetime.fromisoformat(period["as_of"])
                               + timedelta(days=config["periodic_evidence"].get("grace_days", 2)))).days
    return {**period, "state": state, "overdue_days": overdue_days, "verdict": (record or {}).get("deterministic_verdict"),
            "issues": (record or {}).get("issues"), "missing_files": sorted(set(files) - set(arrived))}


def _codes(journal):
    rec = journal.latest("obligation_reconciliation")["payload"]
    return rec, {i["code"] for i in rec["issues"]}


def compare(previous, current_journal) -> dict:
    prev_journal = previous["journal"]
    prev_rec, prev_codes = _codes(prev_journal)
    cur_rec, cur_codes = _codes(current_journal)
    prev_status = {o["element_id"]: o["governed_status"] for o in prev_rec["obligations"]}
    cur_status = {o["element_id"]: o["governed_status"] for o in cur_rec["obligations"]}
    prev_basis = {o["element_id"]: o["basis"] for o in prev_rec["obligations"]}
    cur_basis = {o["element_id"]: o["basis"] for o in cur_rec["obligations"]}
    coverage = lambda rec: {"corroborated": bool((rec.get("coverage") or {}).get("corroborated")),
                            "reason": (rec.get("coverage") or {}).get("reason")
                            or ("no coverage statement in this record" if not rec.get("coverage") else None)}
    prev_verdict = _record(prev_journal)["deterministic_verdict"]
    cur_verdict = _record(current_journal)["deterministic_verdict"]
    return {
        "previous_investigation_id": previous["investigation_id"], "previous_label": previous["label"],
        "verdict_before": prev_verdict, "verdict_after": cur_verdict, "verdict_changed": prev_verdict != cur_verdict,
        "obligation_changes": [{"element_id": e, "before": prev_status.get(e), "after": cur_status.get(e)}
                               for e in sorted(set(prev_status) | set(cur_status))
                               if prev_status.get(e) != cur_status.get(e)],
        "basis_changes": [{"element_id": e, "status": cur_status.get(e), "before": prev_basis.get(e), "after": cur_basis.get(e)}
                          for e in sorted(set(prev_basis) | set(cur_basis))
                          if prev_status.get(e) == cur_status.get(e) and prev_basis.get(e) != cur_basis.get(e)],
        "coverage_before": coverage(prev_rec), "coverage_after": coverage(cur_rec),
        "codes_resolved": sorted(prev_codes - cur_codes), "codes_new": sorted(cur_codes - prev_codes),
        "codes_persisting": sorted(prev_codes & cur_codes),
        "issues_before": len(prev_rec["issues"]), "issues_after": len(cur_rec["issues"]),
    }


class SchedulerBusy(RuntimeError):
    """Another check is running on this workspace right now."""


def tick(config: dict, root: Path, notify=None, now=None) -> list[dict]:
    """Run every authorised period whose evidence has arrived and that has no result yet.

    Only one check runs on a workspace at a time; a concurrent caller gets
    SchedulerBusy and should simply skip this round.
    """
    import fcntl
    lock_path = Path(root) / "pilot" / "tick.lock"
    handle = open(lock_path, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SchedulerBusy("another check is running on this workspace")
    try:
        return _tick(config, root, notify, now)
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _tick(config: dict, root: Path, notify=None, now=None) -> list[dict]:
    from .orchestrator import run
    from governance.operations.runtime import signers_for
    payload = verify(config, root)
    if now is not None and not payload.get("constructed_demo"):
        raise ValueError("a simulated clock is allowed only for a signed constructed demonstration series")
    run_config = {**config, "simulated_clock": now.isoformat()} if now is not None else config
    executor = signers_for(config, root)["executor"]
    summary, previous = [], None
    for period in payload["periods"]:
        state = period_state(config, root, period, now)
        if state["state"] == "PREMATURE_EXPORT":
            event = quarantine(config, root, period, executor, now or datetime.now().astimezone())
            state = {**period_state(config, root, period, now), "integrity_event": event}
            if notify:
                notify(f"{period['label']}: premature complete export quarantined (integrity event)")
        if state["state"] == "EVIDENCE_READY":
            outcome = run(run_config, root, period["investigation_id"])
            state = {**period_state(config, root, period, now), "ran": True, "checkpoint": outcome.get("checkpoint")}
            journal = _journal(config, root, period["investigation_id"])
            if state["state"] == "AWAITING_ATTESTATION" and previous and journal.latest(DELTA) is None:
                delta = compare(previous, journal)
                journal.append(DELTA, DELTA, delta, executor, "executor")
                state["delta"] = delta
            if notify and state["state"] == "AWAITING_ATTESTATION":
                notify(f"{period['label']}: new {state['verdict']} result awaiting attestation")
        summary.append(state)
        if state["state"] in {"AWAITING_ATTESTATION", "ATTESTED"}:
            previous = {**period, "journal": _journal(config, root, period["investigation_id"])}
    notified_path = Path(root) / "pilot" / "overdue_notified.json"
    notified = set(json.loads(notified_path.read_text())) if notified_path.exists() else set()
    for state in summary:
        if state["state"] == "OVERDUE" and state["label"] not in notified:
            notified.add(state["label"])
            if notify:
                notify(f"{state['label']}: evidence OVERDUE by {state['overdue_days']} day(s)")
    notified_path.write_text(json.dumps(sorted(notified)) + "\n")
    status_path = Path(root) / "pilot" / "schedule_status.json"
    status_path.write_text(json.dumps({"checked_at": datetime.now().astimezone().isoformat(),
                                       "periods": [{k: v for k, v in s.items() if k != "delta"} for s in summary]},
                                      indent=2) + "\n")
    return summary
