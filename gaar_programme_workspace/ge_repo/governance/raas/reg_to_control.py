"""M1 Reg-to-Control: a new publication becomes proposed control amendments and additions, each quoting its passage.

- Every obligation sentence-block in the publication ("must", "shall", "should", "is expected to", ...) is read.
- It amends the existing control it shares the most distinctive terms with, if it shares at least
  reg_to_control.min_shared_terms; otherwise it is proposed as a new control. Each item quotes the publication verbatim
  with character offsets and the publication's SHA-256, so anyone can check the quote.
- M1 never proposes retiring a control: silence in a new publication is not repeal. A person decides that.
- A named person decides each item on its own record, after the quote is re-verified against the publication text.
  Bulk acceptance is refused (the basis rule, governance/basis.py). The control set is signed only when every item
  is decided.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from governance.basis import _tokens, passages
from governance.names import require_person

from . import params, store

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "governance" / "knowledge" / "contracts"
DECISIONS = ("ACCEPT", "REJECT")


def _controls(framework: str) -> list[dict]:
    for path in sorted(CONTRACTS.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data.get("framework") == framework:
            return data["controls"]
    raise ValueError(f"no control contracts for framework {framework}")


def _control_terms(c: dict) -> set[str]:
    text = " ".join([c.get("title", ""), c.get("requirement", "")] + [e.get("text", "") for e in c.get("elements") or []])
    return set(_tokens(text))


def _obligation(text: str, markers: list[str]) -> bool:
    low = " " + re.sub(r"\s+", " ", text.lower()) + " "
    return any(f" {m} " in low for m in markers)


def propose(publication: str, framework: str, title: str, reference: str, path=None) -> dict:
    if not (publication or "").strip():
        raise ValueError("there is no publication text to read")
    if not (title or "").strip() or not (reference or "").strip():
        raise ValueError("a proposal needs the publication's title and reference")
    cfg = params()["reg_to_control"]
    controls = _controls(framework)
    terms = {c["control_id"]: _control_terms(c) for c in controls}
    df = Counter(t for ts in terms.values() for t in ts)
    idf = lambda t: math.log(1 + len(controls) / (1 + df[t]))                  # noqa: E731  rare terms weigh more
    sha = hashlib.sha256(publication.encode("utf-8")).hexdigest()
    items, new_n = [], 0
    for p in passages(publication):
        if not _obligation(p["text"], cfg["obligation_markers"]):
            continue
        words = set(_tokens(p["text"]))
        ranked = sorted(((sum(idf(t) for t in words & ts), sorted(words & ts), cid) for cid, ts in terms.items()),
                        key=lambda x: -x[0])
        best = ranked[0]
        quote = " ".join(p["text"].split())
        item = {"quote": quote, "start": p["start"], "end": p["end"]}
        if len(best[1]) >= cfg["min_shared_terms"]:
            c = next(x for x in controls if x["control_id"] == best[2])
            item.update(action="AMEND", control_id=best[2], control_title=c.get("title", ""), shared_terms=best[1][:8])
        else:
            new_n += 1
            item.update(action="ADD", control_id=f"{framework}-NEW-{new_n}", control_title="(new control: a person "
                        "writes its title)", shared_terms=best[1][:8], nearest_control=best[2])
        item["item_id"] = "I" + hashlib.sha256(f"{sha}|{p['start']}".encode()).hexdigest()[:8]
        items.append(item)
    if not items:
        raise ValueError("the publication states no obligation this module can read: a person must review it")
    proposal = {"proposal_id": "RCP-" + sha[:12], "framework": framework, "title": title.strip(),
                "reference": reference.strip(), "publication_sha256": sha, "items": items,
                "counts": dict(Counter(i["action"] for i in items)), "retirements_proposed": 0,
                "at": datetime.now(timezone.utc).isoformat()}
    store("reg_changes", path).append("RaaSRegChangeProposed", proposal)
    return proposal


def _proposal(proposal_id: str, path=None) -> tuple[dict, dict]:
    rows = [r["payload"] for r in store("reg_changes", path).read()]
    found = [r for r in rows if r.get("proposal_id") == proposal_id and "items" in r]
    if not found:
        raise ValueError(f"no proposal {proposal_id}")
    decided = {r["item_id"]: r for r in rows if r.get("proposal_id") == proposal_id and "decision" in r}
    return found[-1], decided


def decide(proposal_id: str, item_id: str, decision: str, by: str, publication: str, note: str = "",
           path=None) -> dict:
    """One person, one item, one recorded decision. The publication is supplied again and must hash to the one the
    proposal was made from, so every quote is re-verified by its offsets."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    by = require_person(by, "a control-set decision needs the name of the person making it")
    proposal, decided = _proposal(proposal_id, path)
    item = next((i for i in proposal["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise ValueError(f"proposal {proposal_id} has no item {item_id}")
    if item_id in decided:
        raise ValueError(f"item {item_id} was already decided by {decided[item_id]['by']}")
    if hashlib.sha256(publication.encode("utf-8")).hexdigest() != proposal["publication_sha256"]:
        raise ValueError("the publication text differs from the one this proposal was made from")
    record = {"proposal_id": proposal_id, "item_id": item_id, "decision": decision, "by": by, "note": note,
              "action": item["action"], "control_id": item["control_id"], "rigor": "per-item",
              "at": datetime.now(timezone.utc).isoformat()}
    store("reg_changes", path).append("RaaSRegChangeDecided", record)
    return record


def decide_all(*_args, **_kwargs):
    """Kept so the refusal is explicit: accepting a machine-proposed control set in bulk is not a sign-off."""
    raise ValueError("bulk sign-off is refused: decide each proposed control change on its own record, after "
                     "reading its passage")


def control_set(proposal_id: str, path=None) -> dict:
    """The signed control set, only once every item is decided."""
    proposal, decided = _proposal(proposal_id, path)
    open_items = [i["item_id"] for i in proposal["items"] if i["item_id"] not in decided]
    if open_items:
        raise ValueError(f"the control set is not signed: {len(open_items)} item(s) undecided")
    accepted = [dict(i, decided_by=decided[i["item_id"]]["by"]) for i in proposal["items"]
                if decided[i["item_id"]]["decision"] == "ACCEPT"]
    return {"proposal_id": proposal_id, "framework": proposal["framework"], "title": proposal["title"],
            "reference": proposal["reference"], "publication_sha256": proposal["publication_sha256"],
            "accepted": accepted, "rejected": len(proposal["items"]) - len(accepted),
            "signed_by": sorted({d["by"] for d in decided.values()}), "status": "SIGNED"}
