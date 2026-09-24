"""One canonical source for element text, and a check that the derived views still agree.

The D1.2 incident: the same six elements existed in `control_contracts.yaml`,
`contracts/mgf_agentic.yaml` and `predicate_specs.yaml`. Two were repaired, one was not, and
nothing noticed until an unrelated test asserted the corrected wording and failed. `A.5.2` and
three other ISO elements had drifted the same way into `semantic_registry.yaml` — eleven
elements where the canonical contract said one thing and a derived view said another.

That class of defect is not fixable by being careful. It is fixable by naming one writable
representation and making every other one derived:

    control_contracts.yaml          canonical — element text is authored here and nowhere else
        |
        +-- contracts/<framework>.yaml      derived
        +-- semantic_registry.yaml          derived (field: governed_text)
        +-- predicate_specs.yaml            derived (elements keyed by id)

A derived view may add fields the canon does not carry — `verification`, `expected_evidence`,
predicate specifications, intent. What it may not do is restate the requirement differently,
because then there are two requirements and no way to tell which one an assessment was against.

`check()` reports drift and `sync()` repairs it in one direction only. There is deliberately no
reverse sync: a derived file cannot promote its own wording to canonical, because the whole point
is that authoring happens in one place. Fixing drift by copying the derived text back would make
whichever file was edited last the source of truth, which is where this started.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

SCHEMA = "semantic-canon.1"
ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "governance" / "knowledge"
CANONICAL = KNOWLEDGE / "control_contracts.yaml"


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split())


# ---------------------------------------------------------------- canonical

def canonical_elements(path: Path | None = None) -> dict[tuple[str, str], str]:
    """{(control_id, element_id): text} from the one authored file."""
    doc = yaml.safe_load((path or CANONICAL).read_text(encoding="utf-8")) or {}
    out: dict[tuple[str, str], str] = {}
    for c in doc.get("controls") or []:
        cid = str(c.get("control_id") or c.get("id") or "")
        for e in c.get("elements") or []:
            out[(cid, str(e.get("id")))] = _norm(e.get("text"))
    return out


# ---------------------------------------------------------------- derived views
#
# Each view declares how to walk it. Adding a new derived representation means adding an entry
# here — which is the point: a representation nobody declared is a representation nobody checks.

def _walk_contract(doc: Any) -> Iterable[tuple[str, str, dict, str]]:
    ctrls = doc.get("controls") if isinstance(doc, dict) else doc
    if isinstance(ctrls, dict):
        ctrls = list(ctrls.values())
    for c in ctrls or []:
        cid = str(c.get("control_id") or c.get("id") or "")
        for e in c.get("elements") or []:
            yield cid, str(e.get("id")), e, "text"


def _walk_registry(doc: Any) -> Iterable[tuple[str, str, dict, str]]:
    for c in (doc or {}).get("controls") or []:
        cid = str(c.get("control_id") or "")
        for e in c.get("elements") or []:
            yield cid, str(e.get("id")), e, "governed_text"


def _walk_predicate_specs(doc: Any) -> Iterable[tuple[str, str, dict, str]]:
    """Two shapes in one file: a top-level control, and a `frameworks` block of them."""
    def _one(block: dict):
        cid = str(block.get("control_id") or "")
        els = block.get("elements") or {}
        items = els.items() if isinstance(els, dict) else (
            (str(e.get("id")), e) for e in els)
        for eid, e in items:
            if isinstance(e, dict):
                yield cid, str(eid), e, "text"
    if not isinstance(doc, dict):
        return
    yield from _one(doc)
    fw = doc.get("frameworks")
    if isinstance(fw, dict):
        for block in fw.values():
            for b in (block if isinstance(block, list) else [block]):
                if isinstance(b, dict):
                    yield from _one(b)


DERIVED: list[tuple[str, Callable]] = [
    *[(f"governance/knowledge/contracts/{n}.yaml", _walk_contract)
      for n in ("mas", "mgf_agentic", "safr", "nist_ai_rmf", "iso_42001")],
    ("governance/knowledge/semantic_registry.yaml", _walk_registry),
    ("governance/knowledge/predicate_specs.yaml", _walk_predicate_specs),
]


# ---------------------------------------------------------------- check / sync

def check(root: Path | None = None) -> dict[str, Any]:
    """Every place a derived view restates the requirement differently from the canon."""
    base = root or ROOT
    canon = canonical_elements(base / "governance/knowledge/control_contracts.yaml")
    findings: list[dict[str, Any]] = []
    seen_views = []
    for rel, walk in DERIVED:
        p = base / rel
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        n = 0
        present = set()
        for cid, eid, el, field in walk(doc):
            n += 1
            key = (cid, eid)
            present.add(key)
            if key not in canon:
                findings.append({"view": rel, "ref": f"{cid}.{eid}", "code": "NOT_IN_CANON",
                                 "detail": "derived view defines an element the canon does not"})
                continue
            if _norm(el.get(field)) != canon[key]:
                findings.append({
                    "view": rel, "ref": f"{cid}.{eid}", "code": "TEXT_DRIFT",
                    "canonical": canon[key][:120], "derived": _norm(el.get(field))[:120]})
        # Structural drift, which text comparison cannot see. `sync` rewrites the text of
        # elements the two have in common; an element the canon gained after the derived view
        # was generated is simply absent, and every text check passes. Re-authoring S1.2 and
        # S2.1 from four elements to five left the registry at four and `coverage_summary()`
        # reported 85 SAFR elements while the canon held 86 — a text-only canonicaliser is a
        # partial one.
        controls_in_view = {cid for cid, _ in present}
        for key in canon:
            if key[0] in controls_in_view and key not in present:
                findings.append({"view": rel, "ref": f"{key[0]}.{key[1]}",
                                 "code": "MISSING_IN_DERIVED",
                                 "detail": "the canon defines an element this view does not carry"})
        seen_views.append({"view": rel, "elements": n})
    return {"schema": SCHEMA, "canonical_elements": len(canon), "views": seen_views,
            "findings": findings,
            "drift": len([f for f in findings if f["code"] == "TEXT_DRIFT"]),
            "orphans": len([f for f in findings if f["code"] == "NOT_IN_CANON"]),
            "missing": len([f for f in findings if f["code"] == "MISSING_IN_DERIVED"]),
            "clean": not findings}


def sync(root: Path | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    """Rewrite derived element text from the canon. One direction, always."""
    base = root or ROOT
    canon = canonical_elements(base / "governance/knowledge/control_contracts.yaml")
    changed: list[dict[str, str]] = []
    for rel, walk in DERIVED:
        p = base / rel
        if not p.exists():
            continue
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        n = 0
        present: set[tuple[str, str]] = set()
        field_of: dict[str, str] = {}
        for cid, eid, el, field in walk(doc):
            key = (cid, eid)
            present.add(key)
            field_of[cid] = field
            if key in canon and _norm(el.get(field)) != canon[key]:
                changed.append({"view": rel, "ref": f"{cid}.{eid}"})
                el[field] = canon[key]
                n += 1

        # Structural sync: an element the canon gained is appended with its text and id only.
        # Nothing else is fabricated — a derived view's own fields (verification, predicate spec,
        # expected evidence) are regenerated by the module that owns them, and inventing values
        # here would put a guess in a governed file.
        missing = [k for k in canon
                   if k[0] in {c for c, _ in present} and k not in present]
        if missing:
            ctrls = doc.get("controls") if isinstance(doc, dict) else doc
            if isinstance(ctrls, dict):
                ctrls = list(ctrls.values())
            by_id = {str(c.get("control_id") or c.get("id") or ""): c for c in (ctrls or [])}
            for cid, eid in missing:
                c = by_id.get(cid)
                if c is None or not isinstance(c.get("elements"), list):
                    continue
                # Copy the fields the canon actually carries. Propagating an authored value is
                # not fabrication; inventing one the canon does not hold would be. Fields a
                # derived view owns (verification mode, predicate spec, audit result) are left
                # for the module that computes them.
                src = _canonical_element(cid, eid)
                row = {"id": eid, field_of.get(cid, "text"): canon[(cid, eid)]}
                for f in ("intent", "scope", "applies_when", "expected_evidence",
                          "source_locator"):
                    if src.get(f) is not None:
                        row[f] = src[f]
                c["elements"].append(row)
                changed.append({"view": rel, "ref": f"{cid}.{eid}", "added": True})
                n += 1
        # The registry carries a `summary` block. Any structural change makes it a stale cache,
        # and a cached count that disagrees with the elements beneath it is the same class of
        # defect as a derived text that disagrees with the canon — recompute it here rather than
        # leaving a number nobody regenerates.
        if n and isinstance(doc, dict) and isinstance(doc.get("summary"), dict):
            _recount_summary(doc)
        # Prune elements the canon no longer defines. Re-authoring a control can reduce its
        # element count — the SAFR archetypes had four apiece and several genuine decompositions
        # have two or three — and a derived view left holding the surplus keeps publishing
        # requirements that were deliberately withdrawn.
        keep = {(cid, eid) for cid, eid, _, _ in walk(doc)} & set(canon)
        ctrls = doc.get("controls") if isinstance(doc, dict) else doc
        if isinstance(ctrls, dict):
            ctrls = list(ctrls.values())
        for c in ctrls or []:
            ccid = str(c.get("control_id") or c.get("id") or "")
            before = c.get("elements") or []
            after = [e for e in before if (ccid, str(e.get("id"))) in keep]
            if len(after) != len(before):
                changed.extend({"view": rel, "ref": f"{ccid}.{e.get('id')}", "pruned": True}
                               for e in before if e not in after)
                c["elements"] = after
                n += 1
        if n and not dry_run:
            p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
                         encoding="utf-8")
    return {"schema": SCHEMA, "updated": len(changed), "changes": changed, "dry_run": dry_run}


def _canonical_element(control_id: str, element_id: str, path: Path | None = None) -> dict:
    """The full canonical element record, not only its text."""
    doc = yaml.safe_load((path or CANONICAL).read_text(encoding="utf-8")) or {}
    for c in doc.get("controls") or []:
        if str(c.get("control_id") or c.get("id")) == control_id:
            for e in c.get("elements") or []:
                if str(e.get("id")) == element_id:
                    return e
    return {}


def _recount_summary(doc: dict) -> None:
    """Recompute the registry's cached counts from the elements actually present."""
    import collections
    els = [(c, e) for c in doc.get("controls") or [] for e in (c.get("elements") or [])]
    fw = collections.Counter(str(c.get("framework") or "?") for c, _ in els)
    mode = collections.Counter(str(e.get("verification") or "") for _, e in els)
    s = doc["summary"]
    s["elements_total"] = s["semantic_elements"] = len(els)
    s["controls_total"] = s["controls"] = len(doc.get("controls") or [])
    s["framework_elements"] = dict(fw)
    s["deterministic_elements"] = mode.get("DETERMINISTIC", 0)
    s["human_judgement_elements"] = mode.get("HUMAN_JUDGEMENT", 0)
    s["out_of_band_elements"] = mode.get("OUT_OF_BAND", 0)
    for k, v in mode.items():
        if k:
            s[f"verification_{k}"] = v
    s["predicate_specifications_available"] = sum(
        1 for _, e in els if e.get("predicate_available")
        or (e.get("predicate_spec") or {}).get("present"))


def report(c: dict[str, Any]) -> str:
    if c["clean"]:
        return (f"{c['canonical_elements']} canonical element(s); "
                f"{len(c['views'])} derived view(s) agree.")
    lines = [f"{c['drift']} drifted, {c['orphans']} orphaned, {c['missing']} missing "
             f"across {len(c['views'])} view(s):"]
    for f in c["findings"][:20]:
        if f["code"] == "TEXT_DRIFT":
            lines.append(f"  {f['ref']:12} {Path(f['view']).name}")
            lines.append(f"     canon  : {f['canonical'][:88]}")
            lines.append(f"     derived: {f['derived'][:88]}")
        else:
            lines.append(f"  {f['ref']:12} {Path(f['view']).name} — {f['detail']}")
    if len(c["findings"]) > 20:
        lines.append(f"  ... and {len(c['findings']) - 20} more")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if "--sync" in sys.argv:
        r = sync(dry_run="--dry-run" in sys.argv)
        print(f"{r['updated']} derived element(s) {'would be' if r['dry_run'] else ''} updated")
    else:
        c = check()
        print(report(c))
        raise SystemExit(0 if c["clean"] else 2)
