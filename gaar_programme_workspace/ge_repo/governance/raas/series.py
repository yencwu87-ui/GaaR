"""The recurring series feeds the closure desk (block 1, B1-3), and the desk retests by re-running the series' own
control test (B1-4).

- Every finding in a period's reconciliation opens one exception, keyed by the finding's issue id, so running the hook
  again opens nothing twice. The exception carries the rule code, the change it fired on, the procedure, and the hash
  of the evidence that raised it.
- The retest is the same procedure the series ran (change_authorization), re-run on the owner's corrected export. It
  passes only when that rule no longer fires on that change. An export the procedure cannot compare (collection
  incomplete) is a FAIL, never a pass.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import closure

PROCEDURES = {"change_authorization:2"}


def exception_id(issue: dict) -> str:
    return "EXC-" + issue["issue_id"].removeprefix("ISSUE-")


def open_from_reconciliation(reconciliation: dict, period_label: str, path=None, evidence=None) -> dict:
    """Open one exception per finding; a finding already on the desk is left as it is. `evidence` is the export the
    procedure read: its hash is recorded, so a rerun on that same export is refused."""
    raised_on = closure.evidence_sha256(evidence) if evidence is not None else ""
    opened, already = [], []
    for issue in reconciliation.get("issues") or []:
        eid = exception_id(issue)
        try:
            closure.state(eid, path=path)
            already.append(eid)
            continue
        except ValueError:
            pass
        reason = (issue.get("detail") or {}).get("reason") or issue["code"]
        closure.open_exception(
            eid, issue["element_id"], f"{issue['code']} on {issue['event_id']}: {reason}",
            f"{reconciliation['investigation_id']}/{issue['issue_id']}", path,
            evidence_sha256=raised_on,
            detail={"code": issue["code"], "event_id": issue["event_id"], "procedure": issue.get("procedure"),
                    "class": issue.get("class"), "period": period_label,
                    "evidence_manifest_event_hash": reconciliation.get("evidence_manifest_event_hash")})
        opened.append(eid)
    return {"period": period_label, "opened": opened, "already_open": already}


def open_from_series(config_path, path=None) -> list[dict]:
    """Every period with a result: its findings on the closure desk."""
    from governance.operations.runtime import load
    from governance.production import recurring
    config, root = load(Path(config_path).expanduser())
    out = []
    for period in recurring.load(config, root)["payload"]["periods"]:
        journal = recurring._journal(config, root, period["investigation_id"])
        event = journal.latest("obligation_reconciliation") if journal else None
        if event:
            export = root / config["periodic_evidence"]["inbox"] / period["label"] / "changes.json"
            evidence = json.loads(export.read_text()) if export.is_file() else None
            out.append(open_from_reconciliation(event["payload"], period["label"], path, evidence))
    return out


def retest_for(exception: dict):
    """The series' control test for this exception, as a callable the desk's rerun can execute on new evidence."""
    detail = exception.get("detail") or {}
    if detail.get("procedure") not in PROCEDURES:
        raise ValueError(f"no re-executable control test for procedure {detail.get('procedure')!r}")
    code, event_id = detail["code"], detail["event_id"]

    def change_authorization(package: dict) -> dict:
        from governance.production.procedures import change_authorization as procedure
        try:
            result = procedure(package)
        except ValueError as unreadable:                  # the procedure refuses a malformed export: not a pass
            return {"verdict": "FAIL", "reason": f"the export could not be tested: {unreadable}"}
        if result.get("status") != "COMPUTED_ON_SUPPLIED_EXPORTS":
            return {"verdict": "FAIL", "reason": result.get("reason") or result.get("status")}
        fired = [f for f in result["findings"] + result["assurance_gaps"]
                 if f["code"] == code and f.get("event_id") == event_id]
        return {"verdict": "FAIL" if fired else "PASS", "rule": code, "event_id": event_id,
                "conclusion": result["conclusion"]}
    change_authorization.test_name = f"change_authorization:2 ({code} on {event_id})"
    return change_authorization
