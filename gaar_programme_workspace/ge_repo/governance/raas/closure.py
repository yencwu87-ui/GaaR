"""M3 Closure Desk: every exception ends closed by an independent retest, or held under a signed, expiring risk
acceptance. Those are the only two outcomes a bank is billed for, and they are counted separately.

    OPEN -> ASSIGNED -> FIX_EVIDENCED -> CLOSED            (retest PASS by someone other than the owner)
                             |        -> ASSIGNED          (retest FAIL: reopened, the owner fixes again)
    OPEN | ASSIGNED -> RISK_ACCEPTED -> (after expiry) ASSIGNED again, as if never accepted

Gaming guard (the Lambda School failure): "closed" is never the owner's word. The owner evidences a fix; a different
person retests it; a risk acceptance needs an approver who is not the owner, a reason and an expiry.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from governance.names import require_person

from . import params, store

RESULTS = ("PASS", "FAIL")


def _ledger(path=None):
    return store("closure", path)


def _events(exception_id: str, path=None) -> list[dict]:
    return [r["payload"] for r in _ledger(path).read() if r["payload"]["exception_id"] == exception_id]


def _fold(events: list[dict], as_of: str) -> dict:
    s = {"state": None, "owner": None, "fix_by": None, "history": []}
    for e in events:
        kind = e["event"]
        s["history"].append(kind)
        if kind == "OPENED":
            s.update(state="OPEN", control_id=e["control_id"], finding=e["finding"], source=e["source"])
        elif kind == "ASSIGNED":
            s.update(state="ASSIGNED", owner=e["owner"])
        elif kind == "FIX_EVIDENCED":
            s.update(state="FIX_EVIDENCED", fix_by=e["by"], evidence_ref=e["evidence_ref"])
        elif kind == "RETESTED":
            s.update(state="CLOSED" if e["result"] == "PASS" else "ASSIGNED", retested_by=e["by"])
        elif kind == "RISK_ACCEPTED":
            s.update(state="RISK_ACCEPTED", accepted_by=e["by"], expires_on=e["expires_on"])
    if s["state"] == "RISK_ACCEPTED" and s["expires_on"] < as_of:
        s["state"] = "ASSIGNED"                                  # an expired acceptance is an open exception again
        s["acceptance_expired"] = True
    return s


def state(exception_id: str, as_of: str | None = None, path=None) -> dict:
    events = _events(exception_id, path)
    if not events:
        raise ValueError(f"no exception {exception_id} on the closure desk")
    return {"exception_id": exception_id, **_fold(events, as_of or date.today().isoformat())}


def _append(exception_id: str, event: str, path=None, **fields) -> dict:
    payload = {"exception_id": exception_id, "event": event, **fields, "at": datetime.now(timezone.utc).isoformat()}
    _ledger(path).append("RaaSClosureEvent", payload)
    return state(exception_id, path=path)


def _require(s: dict, allowed: tuple, action: str):
    if s["state"] not in allowed:
        raise ValueError(f"{s['exception_id']} is {s['state']}: it cannot be {action}")


def open_exception(exception_id: str, control_id: str, finding: str, source: str, path=None) -> dict:
    if _events(exception_id, path):
        raise ValueError(f"exception {exception_id} is already on the closure desk")
    if not (finding or "").strip() or not (source or "").strip():
        raise ValueError("an exception needs the finding and the source that raised it")
    return _append(exception_id, "OPENED", path, control_id=control_id, finding=finding.strip(), source=source.strip())


def assign(exception_id: str, owner: str, by: str, path=None) -> dict:
    s = state(exception_id, path=path)
    _require(s, ("OPEN", "ASSIGNED"), "assigned")
    owner = require_person(owner, "an exception needs the name of the control owner who will fix it")
    by = require_person(by, "an assignment needs the name of the person making it")
    return _append(exception_id, "ASSIGNED", path, owner=owner, by=by)


def evidence_fix(exception_id: str, evidence_ref: str, by: str, path=None) -> dict:
    s = state(exception_id, path=path)
    _require(s, ("ASSIGNED",), "evidenced as fixed")
    by = require_person(by, "a fix needs the name of the person evidencing it")
    if by != s["owner"]:
        raise ValueError(f"only the assigned owner ({s['owner']}) evidences the fix")
    if not (evidence_ref or "").strip():
        raise ValueError("a fix needs a reference to its evidence")
    return _append(exception_id, "FIX_EVIDENCED", path, evidence_ref=evidence_ref.strip(), by=by)


def retest(exception_id: str, result: str, by: str, note: str = "", path=None) -> dict:
    s = state(exception_id, path=path)
    _require(s, ("FIX_EVIDENCED",), "retested")
    if result not in RESULTS:
        raise ValueError("a retest result is PASS or FAIL")
    by = require_person(by, "a retest needs the name of the person who performed it")
    if by in (s["owner"], s["fix_by"]):
        raise ValueError("the retest must be performed by someone other than the owner who fixed it")
    return _append(exception_id, "RETESTED", path, result=result, by=by, note=note)


def accept_risk(exception_id: str, by: str, reason: str, expires_on: str, as_of: str | None = None, path=None) -> dict:
    today = as_of or date.today().isoformat()
    s = state(exception_id, as_of=today, path=path)
    _require(s, ("OPEN", "ASSIGNED"), "risk-accepted")
    by = require_person(by, "a risk acceptance needs the name of the approver")
    if by == s["owner"]:
        raise ValueError("a risk acceptance needs an approver other than the control owner")
    if not (reason or "").strip():
        raise ValueError("a risk acceptance needs its reason on record")
    limit = (date.fromisoformat(today) + timedelta(days=params()["risk_acceptance"]["max_days"])).isoformat()
    if not today < expires_on <= limit:
        raise ValueError(f"a risk acceptance must expire after {today} and no later than {limit}")
    return _append(exception_id, "RISK_ACCEPTED", path, by=by, reason=reason.strip(), expires_on=expires_on)


def summary(as_of: str | None = None, path=None) -> dict:
    """Every exception's state now, and the billable outcomes: closed by retest and under acceptance, apart."""
    today = as_of or date.today().isoformat()
    ids = sorted({r["payload"]["exception_id"] for r in _ledger(path).read()})
    rows = [{"exception_id": i, **_fold(_events(i, path), today)} for i in ids]
    count = lambda st: sum(r["state"] == st for r in rows)                        # noqa: E731
    return {"as_of": today, "exceptions": rows, "total": len(rows), "closed_by_retest": count("CLOSED"),
            "risk_accepted": count("RISK_ACCEPTED"),
            "still_open": len(rows) - count("CLOSED") - count("RISK_ACCEPTED"),
            "billable": count("CLOSED") + count("RISK_ACCEPTED"),
            "reopened_after_failed_retest": sum(r["history"].count("RETESTED") > 1 or
                                                (r["state"] == "ASSIGNED" and "RETESTED" in r["history"]) for r in rows),
            "expired_acceptances": sum(bool(r.get("acceptance_expired")) for r in rows)}
