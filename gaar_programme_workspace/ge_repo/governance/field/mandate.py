"""The collection mandate: the only thing that tells a field agent where it may read, and for whom.

A mandate names the series it serves, the tower that owns the systems, and each source: which connector reads it,
what it holds (its role in the evidence), how its rows map to the evidence contract, and, for a credential, the NAME of
the environment variable that holds it. A named person approves the mandate; the approval pins its SHA-256. Change one
byte and the agents stop until it is approved again. The mandate lives beside the series (root/field/mandate.yaml),
not in the signed series configuration, so approving or changing it never counts as configuration drift.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from governance.names import require_person
from governance.watcher.store import HashChainStore

ROLES = ("changes", "independent", "tickets", "privilege_grants", "freezes", "freeze_exceptions", "recoveries",
         "incidents")
CONNECTORS = ("git", "table", "http_json")
SECRET_KEY = re.compile(r"(password|passwd|secret|token|api[_-]?key|private[_-]?key)", re.I)


def folder(root: Path) -> Path:
    path = Path(root) / "field"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def path_for(root: Path) -> Path:
    return folder(root) / "mandate.yaml"


def _store(root: Path) -> HashChainStore:
    return HashChainStore(folder(root) / "mandates.jsonl", "gaar.field-mandate.v1")


def _secrets(node, where="mandate") -> list[str]:
    """Any key that looks like a credential must be an environment-variable NAME (`*_env`), never a value."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if SECRET_KEY.search(str(k)) and not str(k).endswith("_env") and v not in (None, ""):
                found.append(f"{where}.{k}")
            found += _secrets(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _secrets(v, f"{where}[{i}]")
    return found


def validate(data: dict) -> dict:
    for key in ("mandate_id", "system_id", "owner", "sources"):
        if not data.get(key):
            raise ValueError(f"a mandate needs {key}")
    leaked = _secrets(data)
    if leaked:
        raise ValueError(f"a mandate names the environment variable that holds a credential, never the credential "
                         f"itself: {', '.join(leaked)}")
    ids = [s.get("source_id") for s in data["sources"]]
    if len(set(ids)) != len(ids) or not all(ids):
        raise ValueError("every source needs its own source_id")
    for s in data["sources"]:
        if s.get("connector") not in CONNECTORS:
            raise ValueError(f"{s['source_id']}: connector must be one of {', '.join(CONNECTORS)} (all read-only)")
        if s.get("role") not in ROLES:
            raise ValueError(f"{s['source_id']}: role must be one of {', '.join(ROLES)}")
        if s["role"] != "independent" and not s.get("map"):
            raise ValueError(f"{s['source_id']}: a source needs a field map to the evidence contract")
    roles = [s["role"] for s in data["sources"]]
    for needed in ("changes", "independent", "tickets"):
        if needed not in roles:
            raise ValueError(f"a mandate needs a {needed} source")
    where = lambda s: s.get("repo") or s.get("path") or s.get("url")
    primary = {where(s) for s in data["sources"] if s["role"] == "changes"}
    second = {where(s) for s in data["sources"] if s["role"] == "independent"}
    if primary & second:
        raise ValueError("the independent population must be read from a different system than the change records")
    return data


def approve(root: Path, by: str, note: str = "") -> dict:
    """A named person approves the mandate as it stands now. The approval pins its hash."""
    by = require_person(by, "a mandate approval needs the name of the person approving it")
    path = path_for(root)
    if not path.is_file():
        raise ValueError(f"no mandate at {path}")
    raw = path.read_bytes()
    data = validate(yaml.safe_load(raw) or {})
    return _store(root).append("CollectionMandateApproved", {
        "mandate_id": data["mandate_id"], "sha256": hashlib.sha256(raw).hexdigest(), "owner": data["owner"],
        "approved_by": by, "note": note, "sources": [s["source_id"] for s in data["sources"]],
        "at": datetime.now(timezone.utc).isoformat()})["payload"]


def load_approved(root: Path) -> tuple[dict, dict]:
    """The mandate and its approval, or a refusal saying why the agents may not run."""
    path = path_for(root)
    if not path.is_file():
        raise ValueError("no collection mandate for this series; field agents are not configured")
    raw = path.read_bytes()
    approvals = [r["payload"] for r in _store(root).read()]
    if not approvals:
        raise ValueError("the collection mandate has not been approved")
    if approvals[-1]["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("the collection mandate changed after it was approved; approve it again before the agents run")
    return validate(yaml.safe_load(raw) or {}), approvals[-1]
