"""Append-only storage for immutable GovernanceResult artifacts.

The result itself carries its Ed25519 seal. This store adds a lightweight SHA-256 chain so
insertions/removals/re-ordering in the local JSONL store are detectable independently of the
result's own content seal.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from governance.result_contract import GovernanceResult

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "result_store.jsonl"
GENESIS = "0" * 64


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()


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


class ResultStore:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)

    def last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last: dict[str, Any] | None = None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        return (last or {}).get("record_hash", GENESIS)

    def append(self, result: GovernanceResult) -> GovernanceResult:
        with _append_lock(self.path):
            previous = self.last_hash()
            record = {
                "store_schema_version": "gaar.result-store.v1",
                "result_id": result.result_id,
                "content_hash": result.content_hash,
                "prev_hash": previous,
                "result": result.model_dump(mode="json"),
            }
            record["record_hash"] = _record_hash(record)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(_canon(record) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return result

    def read(self) -> list[GovernanceResult]:
        if not self.path.exists():
            return []
        out: list[GovernanceResult] = []
        previous = GENESIS
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("prev_hash") != previous:
                    raise ValueError("result store chain is broken")
                if record.get("record_hash") != _record_hash(record):
                    raise ValueError("result store record hash is invalid")
                result = GovernanceResult.model_validate(record["result"])
                if result.result_id != record.get("result_id"):
                    raise ValueError("result store result_id mismatch")
                if result.content_hash != record.get("content_hash"):
                    raise ValueError("result store content_hash mismatch")
                out.append(result)
                previous = record["record_hash"]
        return out

    def get(self, result_id: str) -> GovernanceResult | None:
        for result in self.read():
            if result.result_id == result_id:
                return result
        return None
