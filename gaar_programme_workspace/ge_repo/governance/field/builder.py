"""Construct one period's evidence from the sources, deliver it to the series inbox, and keep the receipts.

"Construct" means assemble and normalise, never invent: every record in a delivered export is one mapped row of one
source read, and the receipts say which. The builder refuses to deliver when:
- the period has not ended (plus the mandate's settle time for late log entries): a complete export before then would
  claim what cannot yet be true (D14);
- any source could not be read, or any row could not be mapped: an evidence gap goes to the tower owner, and no
  partial export is delivered as if it were whole;
- an export for that period is already in the inbox: delivered evidence is never replaced.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governance.watcher.store import HashChainStore

from . import connectors, mandate as mandate_module

REQUIRED = {
    "changes": ("event_id", "ticket_id", "occurred_at", "asset_id", "actor_id", "credential_id", "actions",
                "actual_spec_hash", "outcome"),
    "independent": ("event_id",),
    "tickets": ("ticket_id", "status", "approved_by", "approved_at", "window_start", "window_end", "allowed_targets",
                "allowed_actions", "allowed_implementers", "allowed_credentials", "approved_spec_hash"),
    "privilege_grants": ("grant_id", "actor_id", "credential_id", "approved_by", "approved_at", "valid_from",
                         "valid_until", "allowed_targets", "allowed_actions"),
    "freezes": ("freeze_id", "start", "end", "targets"),
    "freeze_exceptions": ("freeze_id", "event_id", "approved_by", "approved_at"),
    "recoveries": ("event_id", "method", "approved_by", "status", "completed_at"),
    "incidents": ("incident_id",),
}
FILES = ("changes.json", "population.json")


def _t(text: str) -> datetime:
    moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def ledger(root: Path) -> HashChainStore:
    return HashChainStore(mandate_module.folder(root) / "collections.jsonl", "gaar.field-collection.v1")


def gather(m: dict, root: Path, start: datetime, end: datetime, get=None) -> dict:
    """Read every source and map its rows. Returns records per role, the receipts, and every gap found."""
    records = {role: [] for role in REQUIRED}
    receipts, gaps = [], []
    for source in m["sources"]:
        reader = connectors.READERS[source["connector"]]
        try:
            kwargs = {"get": get} if source["connector"] == "http_json" else {}
            rows, receipt = reader(source, root, start, end, **kwargs)
        except connectors.SourceUnavailable as exc:
            gaps.append({"source_id": source["source_id"], "gap": str(exc)})
            continue
        except (OSError, ValueError, KeyError, TypeError) as exc:
            gaps.append({"source_id": source["source_id"], "gap": f"{source['source_id']}: unreadable ({type(exc).__name__}: {exc})"[:300]})
            continue
        role = source["role"]
        field_map = source.get("map") or {"event_id": source.get("event_id_column", "event_id")}
        mapped, problems = connectors.map_rows(rows, field_map, REQUIRED[role])
        if problems:
            gaps.append({"source_id": source["source_id"],
                         "gap": f"{source['source_id']}: {len(problems)} row(s) could not be mapped ({'; '.join(problems[:3])})"})
        receipts.append({**receipt, "role": role, "mapped": len(mapped)})
        records[role] += mapped
    inside = lambda r: start <= _t(r["occurred_at"]) < end if r.get("occurred_at") else True
    records["changes"] = [r for r in records["changes"] if inside(r)]
    records["independent"] = [r for r in records["independent"] if inside(r)]
    ids = {r["event_id"] for r in records["changes"]} | {r["event_id"] for r in records["independent"]}
    records["recoveries"] = [r for r in records["recoveries"] if r["event_id"] in ids]
    records["freeze_exceptions"] = [r for r in records["freeze_exceptions"] if r["event_id"] in ids]
    records["freezes"] = [r for r in records["freezes"] if _t(r["start"]) < end and _t(r["end"]) > start]
    return {"records": records, "receipts": receipts, "gaps": gaps}


def build(m: dict, root: Path, period: dict, cadence_days: int, now: datetime, get=None) -> dict:
    end = _t(period["as_of"])
    start = end - timedelta(days=cadence_days)
    settle = timedelta(minutes=int(m.get("settle_minutes", 30)))
    if now < end + settle:
        return {"status": "NOT_YET", "period": period["label"],
                "detail": f"collects after {(end + settle).isoformat()} (period end plus settle time)"}
    got = gather(m, root, start, end, get=get)
    if got["gaps"]:
        return {"status": "GAPS", "period": period["label"], "gaps": got["gaps"], "receipts": got["receipts"]}
    r = got["records"]
    sources = [s["source_id"] for s in m["sources"]]
    primary = next(s["source_id"] for s in m["sources"] if s["role"] == "changes")
    independent = next(s["source_id"] for s in m["sources"] if s["role"] == "independent")
    marks = {"data_classification": m["data_classification"]} if m.get("data_classification") else {}
    changes = {**marks, "scope": m["system_id"], "as_of": period["as_of"],
               "policy": m.get("policy", {"incident_lookback_hours": 24, "failed_change_requires_recovery": True}),
               "collection": {"complete": True, "source_ids": sources, "period_start": start.isoformat(),
                              "period_end": end.isoformat(), "collected_by": "field agents under mandate "
                              + m["mandate_id"]},
               "changes": sorted(r["changes"], key=lambda c: c["occurred_at"]), "tickets": r["tickets"],
               "privilege_grants": r["privilege_grants"], "freezes": r["freezes"],
               "freeze_exceptions": r["freeze_exceptions"], "incidents": r["incidents"], "recoveries": r["recoveries"]}
    side = lambda sid, rows: {"scope": m["system_id"], "as_of": period["as_of"], "complete": True, "source_id": sid,
                              "event_ids": sorted({x["event_id"] for x in rows})}
    population = {**marks, "scope": m["system_id"], "as_of": period["as_of"],
                  "primary": side(primary, r["changes"]), "independent": side(independent, r["independent"])}
    return {"status": "READY", "period": period["label"], "files": {"changes.json": changes, "population.json": population},
            "receipts": got["receipts"]}


def deliver(built: dict, inbox: Path, root: Path, approval: dict, now: datetime) -> dict:
    """Write the exports atomically, beside their receipts, and record the delivery in the field ledger."""
    folder = Path(inbox) / built["period"]
    if any((folder / name).exists() for name in FILES):
        raise ValueError(f"evidence for {built['period']} is already in the inbox; field agents never replace it")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    digests = {}
    for name in FILES:
        body = json.dumps(built["files"][name], indent=1, sort_keys=True).encode()
        digests[name] = hashlib.sha256(body).hexdigest()
        tmp = folder / f".{name}.tmp"
        tmp.write_bytes(body)
        os.replace(tmp, folder / name)
    receipt = {"period": built["period"], "delivered_at": now.isoformat(), "mandate_id": approval["mandate_id"],
               "mandate_sha256": approval["sha256"], "mandate_approved_by": approval["approved_by"],
               "exports": digests, "reads": built["receipts"]}
    (folder / "collection_receipts.json").write_text(json.dumps(receipt, indent=1) + "\n")
    ledger(root).append("FieldDelivery", receipt)
    return receipt


def run(config: dict, root: Path, now: datetime | None = None, get=None) -> dict:
    """The scheduler job: for every ended period with no evidence yet, collect and deliver, or report the gaps."""
    from governance.production import recurring
    now = now or datetime.now().astimezone()
    try:
        m, approval = mandate_module.load_approved(root)
    except ValueError as exc:
        if "not configured" in str(exc):
            return {"status": "NOT_CONFIGURED", "detail": str(exc)}
        return {"status": "FAILED", "error": str(exc)}
    payload = recurring.verify(config, root)
    if m["system_id"] != payload["system_id"]:
        return {"status": "FAILED", "error": f"the mandate is for {m['system_id']}, the series for {payload['system_id']}"}
    inbox = Path(root) / config["periodic_evidence"]["inbox"]
    delivered, gaps, waiting = [], [], []
    for period in payload["periods"]:
        if all((inbox / period["label"] / name).exists() for name in FILES):
            continue
        built = build(m, root, period, payload["cadence_days"], now, get=get)
        if built["status"] == "NOT_YET":
            waiting.append(period["label"])
        elif built["status"] == "GAPS":
            gaps += [{"period": period["label"], **g} for g in built["gaps"]]
            ledger(root).append("FieldGap", {"period": period["label"], "gaps": built["gaps"], "at": now.isoformat(),
                                             "owner": m["owner"]})
        else:
            delivered.append(deliver(built, inbox, root, approval, now)["period"])
    return {"status": "GAPS" if gaps else "OK", "delivered": delivered, "waiting": waiting, "gaps": gaps,
            "owner": m["owner"], "mandate_id": m["mandate_id"]}
