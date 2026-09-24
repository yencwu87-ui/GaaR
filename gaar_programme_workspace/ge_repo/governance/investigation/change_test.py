"""Read-only reconciliation starting from OBSERVED changes, not ticket counts.

Findings establish discrepancies in supplied records, not complete discovery of
unauthorized activity. Collector completeness and authenticity remain audit inputs.
"""
from datetime import datetime, timedelta
import hashlib
import json


def _time(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("timezone-aware timestamps required")
    return t


def reconcile_changes(package):
    required = ("changes", "tickets", "privilege_grants", "freezes", "freeze_exceptions", "incidents", "recoveries")
    if not package.get("scope") or not package.get("as_of"):
        raise ValueError("change export scope and as_of required")
    _time(package["as_of"])
    for name in required:
        if not isinstance(package.get(name), list):
            raise ValueError(f"{name}: explicit export required; missing is not empty")
    coverage = package.get("collection") or {}
    if not coverage.get("source_ids") or coverage.get("complete") is not True:
        return {"status": "NOT_COMPARABLE", "reason": "Actual-change collection coverage is unknown/incomplete; no clean authorization conclusion"}
    # Completeness is a supplied assertion, not something this comparison proves.
    start, end = _time(coverage["period_start"]), _time(coverage["period_end"])
    if start >= end:
        raise ValueError("invalid collection interval")
    policy = package.get("policy") or {}
    lookback = policy.get("incident_lookback_hours")
    if isinstance(lookback, bool) or not isinstance(lookback, (int, float)) or not 0 <= lookback <= 8760:
        raise ValueError("explicit bounded incident lookback policy required")
    if policy.get("failed_change_requires_recovery") not in (True, False):
        raise ValueError("explicit failed-change recovery policy required")
    tickets = {}
    for ticket in package["tickets"]:
        if not ticket.get("ticket_id") or ticket["ticket_id"] in tickets:
            raise ValueError("duplicate/empty ticket ID; ambiguous approvals")
        tickets[ticket["ticket_id"]] = ticket
    ids = set()
    findings, observations = [], []
    for change in package["changes"]:
        cid = change.get("event_id")
        if not cid or cid in ids:
            raise ValueError("duplicate/empty actual change event ID")
        ids.add(cid)
        when = _time(change["occurred_at"])
        if not start <= when < end:
            raise ValueError("observed change lies outside exported collection interval")
        if not all(change.get(k) for k in ("asset_id", "actor_id", "credential_id", "actions")):
            raise ValueError("change requires actual target, implementer, credential and actions")
        if not isinstance(change["actions"], list) or any(not isinstance(x, str) for x in change["actions"]):
            raise ValueError("actions must be normalized observed identifiers")
        if change.get("outcome") not in {"succeeded", "failed"}:
            raise ValueError("explicit change outcome required")
        def finding(code, reason, refs=()):
            findings.append({"event_id": cid, "code": code, "reason": reason, "refs": list(refs),
                             "status": "RECORD_DISCREPANCY"})
        ticket = tickets.get(change.get("ticket_id"))
        if ticket is None:
            finding("NO_MATCHING_APPROVED_TICKET", "Observed change has no matching supplied ticket")
        else:
            tid = ticket["ticket_id"]
            if not ticket.get("approved_by") or not ticket.get("approved_at") or ticket.get("status") != "approved":
                finding("APPROVAL_NOT_ESTABLISHED", "No valid approval in supplied ticket", (tid,))
            elif _time(ticket["approved_at"]) > when:
                finding("APPROVAL_AFTER_EXECUTION", "Approval timestamp follows actual implementation", (tid,))
            if not _time(ticket["window_start"]) <= when < _time(ticket["window_end"]):
                finding("OUTSIDE_APPROVED_WINDOW", "Execution occurred outside approved implementation window", (tid,))
            if change["asset_id"] not in ticket.get("allowed_targets", []) or not set(change["actions"]) <= set(ticket.get("allowed_actions", [])):
                finding("DEVIATES_FROM_APPROVED_SCOPE", "Observed target/actions exceed the approved request", (tid,))
            if change["actor_id"] not in ticket.get("allowed_implementers", []):
                finding("IMPLEMENTER_NOT_APPROVED", "Actual implementer is not authorized by this ticket", (tid,))
            if change["credential_id"] not in ticket.get("allowed_credentials", []):
                finding("CREDENTIAL_NOT_APPROVED_FOR_CHANGE", "Actual credential differs from the approved change credentials", (tid,))
            if ticket.get("approved_spec_hash") and change.get("actual_spec_hash") != ticket["approved_spec_hash"]:
                finding("IMPLEMENTATION_CONTENT_MISMATCH", "Actual change specification hash is missing or differs from the approved version", (tid,))
        grants = [g for g in package["privilege_grants"]
                  if g.get("actor_id") == change["actor_id"] and g.get("credential_id") == change["credential_id"]
                  and g.get("approved_by") and g.get("approved_at") and _time(g["approved_at"]) <= when
                  and _time(g["valid_from"]) <= when < _time(g["valid_until"])
                  and change["asset_id"] in g.get("allowed_targets", [])
                  and set(change["actions"]) <= set(g.get("allowed_actions", []))]
        if not grants:
            finding("PRIVILEGE_NOT_ESTABLISHED", "No timely matching privilege grant for actual actor, credential, target and actions")
        for freeze in package["freezes"]:
            if change["asset_id"] not in freeze.get("targets", []):
                continue
            if _time(freeze["start"]) <= when < _time(freeze["end"]):
                exceptions = [x for x in package["freeze_exceptions"] if x.get("freeze_id") == freeze["freeze_id"]
                              and x.get("event_id") == cid and x.get("approved_by")
                              and x.get("approved_at") and _time(x["approved_at"]) <= when]
                if not exceptions:
                    finding("FREEZE_WITHOUT_PRIOR_EXCEPTION", "Actual implementation falls inside a freeze without a matching prior exception", (freeze["freeze_id"],))
        for incident in package["incidents"]:
            if change["asset_id"] in incident.get("assets", []):
                elapsed = when - _time(incident["started_at"])
                if timedelta(0) <= elapsed <= timedelta(hours=lookback):
                    observations.append({"event_id": cid, "code": "POST_INCIDENT_CHANGE", "incident_id": incident["incident_id"],
                        "status": "INVESTIGATE_CONTEXT", "reason": "May be legitimate remediation or unauthorized activity; timing alone is not a breach"})
        if change["outcome"] == "failed" and policy["failed_change_requires_recovery"]:
            recovery = [r for r in package["recoveries"] if r.get("event_id") == cid
                        and r.get("method") in {"rollback", "approved_fix_forward"}
                        and r.get("approved_by") and r.get("status") == "succeeded"
                        and _time(r["completed_at"]) >= when]
            if not recovery:
                finding("RECOVERY_NOT_ESTABLISHED", "Failed change has no successful authorized rollback/fix-forward record")
    return {"schema": "change-reconciliation.1", "status": "COMPUTED_ON_SUPPLIED_EXPORTS",
            "scope": package["scope"], "as_of": package["as_of"], "synthetic": package.get("synthetic") is True,
            "actual_changes_examined": len(ids), "findings": findings, "observations": observations,
            "input_sha256": hashlib.sha256(json.dumps(package, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "limitation": "Supplied-record reconciliation; no live change discovery. Source authenticity, clock quality, collection completeness and approver authority need separate corroboration. No findings is not proof that no unauthorized changes occurred.",
            "changes_control_verdict": False}
