"""Twin adjudications: how a disagreement between the answer key and the checks is settled, and who settled it."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from governance.watcher.store import HashChainStore

LOG = Path(__file__).resolve().parent / "adjudications.yaml"
SIDE = {"key_error": "key", "check_error": "check", "generator_artifact": "generator"}


def home(path=None) -> Path:
    p = Path(path or os.environ.get("GAAR_TWIN_HOME") or Path.home() / "gaar-twin").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def entries(log: Path = LOG) -> list[dict]:
    """The log, checked against the rule: one classification, and the fix on that side only."""
    data = yaml.safe_load(Path(log).read_text(encoding="utf-8"))
    for e in data["entries"]:
        if e.get("classification") not in SIDE:
            raise ValueError(f"{e['id']}: classification must be one of {', '.join(SIDE)}")
        if e.get("fix_side") != SIDE[e["classification"]]:
            raise ValueError(f"{e['id']}: a {e['classification']} is fixed on the {SIDE[e['classification']]} side only")
        if not e.get("reading_of_the_data") or not e.get("regression_test"):
            raise ValueError(f"{e['id']}: an adjudication needs the reading of the data and a regression test")
    return data["entries"]


def _store(path=None) -> HashChainStore:
    return HashChainStore(home(path) / "adjudications.jsonl", "gaar.twin.adjudication.v1")


def confirm(entry_id: str, by: str, note: str = "", path=None, log: Path = LOG) -> dict:
    """A named person confirms they read the generated data and agree with the classification."""
    known = {e["id"]: e for e in entries(log)}
    if entry_id not in known:
        raise ValueError(f"unknown adjudication {entry_id}")
    if not by.strip():
        raise ValueError("a confirmation needs the name of the person who read the data")
    e = known[entry_id]
    return _store(path).append("TwinAdjudicationConfirmed", {
        "id": entry_id, "classification": e["classification"], "fix_side": e["fix_side"], "by": by.strip(),
        "note": note, "at": datetime.now(timezone.utc).isoformat()})["payload"]


def status(path=None, log: Path = LOG) -> list[dict]:
    confirmed = {}
    for r in _store(path).read():
        confirmed.setdefault(r["payload"]["id"], []).append(r["payload"]["by"])
    return [{"id": e["id"], "classification": e["classification"], "fix_side": e["fix_side"],
             "confirmed_by": confirmed.get(e["id"], []),
             "state": "HUMAN_ADJUDICATED" if confirmed.get(e["id"]) else "AWAITING_A_NAMED_PERSON"}
            for e in entries(log)]
