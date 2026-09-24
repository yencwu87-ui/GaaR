"""Runtime integration for Workstream C Governance Change Intelligence.

This module connects GovernanceChange + ImpactAssessment to the immutable result/state stores.
It is intentionally boring: it does not assess controls, choose PASS/FAIL, or call an LLM.
It only persists the change/impact and emits SYSTEM-triggered CURRENT -> REVIEW_REQUIRED events
for the results that are currently projected as CURRENT.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from governance.change_intelligence import GovernanceChange, ImpactAssessment, build_review_required_events
from governance.result_contract import ResultStateLog, StateTransitionEvent, ValidityState
from governance.result_store import ResultStore

ROOT = Path(__file__).resolve().parent
DEFAULT_CHANGE_LOG = ROOT / "governance_change_events.jsonl"
GENESIS = "0" * 64


def enabled() -> bool:
    return os.environ.get("WB_GAAR_CHANGE_INTELLIGENCE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


@contextmanager
def _append_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class ChangeImpactStore:
    """Append-only, hash-chained store for GovernanceChange / ImpactAssessment records."""

    def __init__(self, path: str | Path = DEFAULT_CHANGE_LOG):
        self.path = Path(path)

    def last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        return (last or {}).get("record_hash", GENESIS)

    def append(self, record_type: str, record: dict[str, Any]) -> dict[str, Any]:
        with _append_lock(self.path):
            prev = self.last_hash()
            body = {
                "store_schema_version": "gaar.change-impact-store.v1",
                "record_type": record_type,
                "record_id": record.get("change_id") or record.get("impact_id"),
                "prev_hash": prev,
                "payload": record,
            }
            body["record_hash"] = _hash(body)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(_canon(body) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return body

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        prev = GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("prev_hash") != prev:
                    raise ValueError("change-impact store chain is broken")
                if record.get("record_hash") != _hash({k: v for k, v in record.items() if k != "record_hash"}):
                    raise ValueError("change-impact record hash is invalid")
                out.append(record)
                prev = record["record_hash"]
        return out


def current_result_ids(
    results: Iterable[Any],
    state_log: ResultStateLog,
) -> set[str]:
    """Project current results from immutable artifacts + the state event stream."""
    current: set[str] = set()
    for result in results:
        if state_log.current_state(result.result_id) == ValidityState.CURRENT:
            current.add(result.result_id)
    return current


def apply_change(
    change: GovernanceChange,
    impact: ImpactAssessment,
    *,
    result_store: ResultStore | None = None,
    state_log: ResultStateLog | None = None,
    change_store: ChangeImpactStore | None = None,
    actor_id: str = "governance-change-engine",
) -> dict[str, Any]:
    """Persist a detected change and emit only the valid system review triggers.

    No human decision is fabricated. When enabled, the function produces:
    GovernanceChange + ImpactAssessment + zero or more CURRENT -> REVIEW_REQUIRED events.
    """
    if not enabled():
        return {"enabled": False, "change": change, "impact": impact, "state_events": ()}

    store = result_store or ResultStore()
    states = state_log or ResultStateLog()
    audit_store = change_store or ChangeImpactStore()

    results = store.read()
    current_ids = current_result_ids(results, states)

    audit_store.append("GovernanceChange", change.to_dict())
    audit_store.append("ImpactAssessment", impact.to_dict())

    events = build_review_required_events(
        change,
        impact,
        results=results,
        current_result_ids=current_ids,
        actor_id=actor_id,
        prev_hash=states.last_hash(),
    )
    persisted: list[StateTransitionEvent] = []
    for event in events:
        persisted.append(states.append(event))

    return {
        "enabled": True,
        "change": change,
        "impact": impact,
        "current_result_ids": sorted(current_ids),
        "state_events": tuple(persisted),
    }
