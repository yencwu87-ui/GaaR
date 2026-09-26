"""The regulatory watch feeds M1 (block 1, B1-2).

The watch sees a new MAS publication's title and link, never its text: MAS's site refuses automated clients, and GaaR
does not bypass that. So the chain is:

1. A new MAS regulatory item is first triaged in the inbox as before. Once a person marks it RELEVANT, and until M1 has
   read it, it is an inbox item: save the publication's text.
2. `propose_from_watch` reads the saved file (text, or a PDF read locally; never a cloud service), keeps a copy under
   its SHA-256, and runs M1 on it, recording which watch item the proposal came from.
3. A proposal with undecided items is an inbox item: decide each one on its own record.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from governance.names import require_person

from . import exists, home, reg_to_control, store

REGULATORY = ("INSTRUMENT", "CONSULTATION")


def _is_mas(item: dict) -> bool:
    return "MAS" in (item.get("authority") or "").upper() or item.get("source_id", "").startswith("mas-")


def links(path=None) -> dict:
    return {r["payload"]["item_id"]: r["payload"] for r in store("watch_links", path).read()} if exists(path) else {}


def awaiting_text(watch_home=None, path=None, now=None) -> list[dict]:
    """MAS regulatory items a person has not ruled out and M1 has not read yet."""
    from governance.watcher import intel
    if not intel.configured(watch_home):
        return []
    linked = links(path)
    return [i for i in intel.items(watch_home, now) if _is_mas(i) and i["kind"] in REGULATORY
            and i["item_id"] not in linked and (i.get("triage") or {}).get("decision") == "RELEVANT"]


def _read(file: Path) -> str:
    if file.suffix.lower() == ".pdf":
        import fitz                                             # PyMuPDF, local: evidence never goes to a cloud reader
        with fitz.open(file) as doc:
            return "\n".join(page.get_text() for page in doc)
    return file.read_text(encoding="utf-8")


def propose_from_watch(item_id: str, text_file, by: str, watch_home=None, path=None) -> dict:
    from governance.watcher import intel
    by = require_person(by, "a proposal from the watch needs the name of the person who saved the publication")
    item = next((i for i in intel.items(watch_home) if i["item_id"] == item_id), None)
    if item is None:
        raise ValueError(f"no watch item {item_id}")
    if not _is_mas(item) or item["kind"] not in REGULATORY:
        raise ValueError(f"watch item {item_id} is not a MAS instrument or consultation: M1 reads MAS publications")
    if item_id in links(path):
        raise ValueError(f"watch item {item_id} already has proposal {links(path)[item_id]['proposal_id']}")
    file = Path(text_file).expanduser()
    if not file.is_file():
        raise ValueError(f"no saved publication at {file}")
    text = _read(file)
    proposal = reg_to_control.propose(text, "MAS", item["title"], item["url"], path=path)
    sha = proposal["publication_sha256"]
    kept = home(path) / "publications" / f"{sha}.txt"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text, encoding="utf-8")
    store("watch_links", path).append("RaaSWatchLinked", {
        "item_id": item_id, "proposal_id": proposal["proposal_id"], "publication_sha256": sha, "saved_by": by,
        "saved_file": file.name, "url": item["url"], "title": item["title"],
        "at": datetime.now(timezone.utc).isoformat()})
    return proposal


def publication(proposal_id: str, path=None) -> str:
    """The kept text a proposal was made from, re-checked against its hash, for the per-item decisions."""
    proposal, _ = reg_to_control._proposal(proposal_id, path)
    kept = home(path) / "publications" / f"{proposal['publication_sha256']}.txt"
    if not kept.is_file():
        raise ValueError(f"the text of proposal {proposal_id} was not kept here")
    text = kept.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != proposal["publication_sha256"]:
        raise ValueError(f"the kept text of proposal {proposal_id} no longer matches its hash")
    return text


def awaiting_decision(path=None) -> list[dict]:
    """Proposals with items no one has decided yet."""
    if not exists(path):
        return []
    rows = [r["payload"] for r in store("reg_changes", path).read()]
    out = []
    for p in (r for r in rows if "items" in r):
        decided = {r["item_id"] for r in rows if r.get("proposal_id") == p["proposal_id"] and "decision" in r}
        open_items = [i["item_id"] for i in p["items"] if i["item_id"] not in decided]
        if open_items:
            out.append({"proposal_id": p["proposal_id"], "title": p["title"], "reference": p["reference"],
                        "undecided": len(open_items), "items": len(p["items"]), "since": p["at"]})
    return out
