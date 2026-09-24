"""Controlled regulatory-change review. A source upload is evidence, never an authorisation.

    CURRENT GOVERNED CONTRACT  ── remains immutable ──┐
                                                       │
    NEW SOURCE ─> fingerprint ─> candidate matching ─> element comparison ─> REVIEW ARTEFACT
                                                                                   │
                                                              human review ─> proposed revision
                                                                                   │
                                                              explicit approval ─> new version

This module implements everything up to and including the review artefact, and deliberately
stops there. It has no function that writes to `control_contracts.yaml`, and a test asserts that
none exists. The reason is the same one that governs the assessor: the thing that analyses a
change must not also be the thing authorised to make it.

Four states, kept separate because collapsing any two is how an upload becomes a rewrite:

    source_match        this passage appears relevant to this control
    semantic_change     the governed obligation differs from what the source now says
    proposed_revision   here is a candidate element text
    approved_revision   the governance authority accepted that candidate

Only the first two are produced here. `proposed_revision` requires a human to author it;
`approved_revision` requires a named approver and is recorded elsewhere. A passage being relevant
is not evidence that the obligation changed, and an obligation having changed is not a proposal
for what it should now say.

On matching: retrieval is lexical and deliberately weak. A confident matcher would produce
confident wrong answers on a 60-page consultation paper, and the cost of a missed match is a
human reading the section, while the cost of a false match presented confidently is a reviewer
approving a revision against the wrong passage.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "mas-change-review.1"

UNCHANGED, CHANGED, NEW, REMOVED, UNMATCHED = "UNCHANGED", "CHANGED", "NEW", "REMOVED", "UNMATCHED"

_STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "is", "are", "be", "that",
         "this", "with", "by", "as", "at", "from", "its", "their", "which", "should", "must",
         "may", "any", "all", "where", "such", "shall", "will", "an", "has", "have"}


def _terms(text: Any) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if t not in _STOP and len(t) > 3}


def _overlap(element_text: str, passage_text: str) -> float:
    """Containment of the element in the passage, not Jaccard similarity.

    Jaccard divides by the union, so a 15-word element against a 90-word paragraph scores low
    however completely the paragraph states the obligation. Run that way against the very
    consultation paper these elements were derived from, every one of the 101 came back CHANGED
    or UNMATCHED and none UNCHANGED — which is the metric failing, not the contract having moved.

    Containment asks the question actually being asked: how much of this element's substance
    appears in this passage. It is asymmetric on purpose — a long passage covering the element
    fully should score 1.0, because the obligation is there.
    """
    x, y = _terms(element_text), _terms(passage_text)
    return len(x & y) / len(x) if x else 0.0


# ---------------------------------------------------------------- fingerprint

def fingerprint(path: str | Path, *, uploaded_by: str = "", note: str = "") -> dict[str, Any]:
    """Provenance for an uploaded source. Recorded before anything is compared against it.

    Without this an analysis cannot say which document it ran against, and a review artefact
    that cannot name its source is not evidence of anything.
    """
    p = Path(path)
    raw = p.read_bytes()
    return {"schema": SCHEMA, "file": p.name, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "uploaded_by": uploaded_by or "unrecorded",
            "uploaded_at": date.today().isoformat(),
            "note": note,
            "status": "SOURCE_UNDER_REVIEW",
            "authorises_change": False}


# ---------------------------------------------------------------- passages

def passages(text: str, *, min_words: int = 12) -> list[dict[str, Any]]:
    """Split a source into addressable passages. Paragraph-level, with a stable index."""
    out: list[dict[str, Any]] = []
    for i, block in enumerate(re.split(r"\n\s*\n", text)):
        body = " ".join(block.split())
        if len(body.split()) >= min_words:
            out.append({"passage_id": f"p{len(out):04d}", "block_index": i, "text": body})
    return out


def candidate_passages(target: str, pool: list[dict], *, top: int = 3,
                       floor: float = 0.25) -> list[dict[str, Any]]:
    """Passages that appear relevant. `source_match` only — never a change claim."""
    scored = [{"passage_id": p["passage_id"], "score": round(_overlap(target, p["text"]), 3),
               "text": p["text"][:400]} for p in pool]
    hits = [s for s in scored if s["score"] >= floor]
    return sorted(hits, key=lambda s: -s["score"])[:top]


# ---------------------------------------------------------------- comparison

def compare_element(element: dict, pool: list[dict], *,
                    changed_below: float = 0.70) -> dict[str, Any]:
    """One canonical element against the new source.

    `UNMATCHED` is its own state rather than being folded into REMOVED. A consultation paper that
    does not mention an obligation may have dropped it, may have moved it, or may simply be a
    different document; deciding which is a human judgement and the artefact must not pre-empt it.
    """
    text = str(element.get("text") or "")
    cands = candidate_passages(text, pool)
    top = cands[0]["score"] if cands else 0.0

    # Source match only. The tool reports how much of the element's substance appears in the
    # closest passage and stops.
    #
    # It does not claim CHANGED, and the reason is in the data: run against the very consultation
    # paper these elements were derived from, containment is a continuous distribution — median
    # 0.43, no cliff anywhere. Any threshold would be inventing a boundary, and every element
    # below it would be reported as a changed obligation when the real explanation is that the
    # elements were authored as governed restatements rather than quotations. Low containment
    # means "worded differently", which is what a decomposition is for, and says nothing about
    # whether the obligation moved.
    #
    # `semantic_change` is therefore left null. Deciding it is reading the passage, which is a
    # human act, and a field the tool cannot fill honestly must stay empty rather than be filled
    # by a threshold.
    if not cands:
        band, why = "NONE", "no passage in the new source appears relevant to this element"
    elif top >= 0.70:
        band, why = "STRONG", f"{top:.0%} of the element's substance appears in the closest passage"
    else:
        band, why = "PARTIAL", (f"only {top:.0%} of the element's substance appears in the "
                                f"closest passage — read it before concluding anything")
    return {"element_id": str(element.get("id")), "governed_text": text,
            "source_match": band, "match_score": round(top, 3), "basis": why,
            "candidates": cands,
            "semantic_change": None,     # human judgement; the tool cannot decide it
            "proposed_revision": None,   # a human authors this
            "approved_revision": None,   # requires a named approver, recorded elsewhere
            "review_required": band in ("NONE", "PARTIAL")}


def review_control(control: dict, pool: list[dict]) -> dict[str, Any]:
    rows = [compare_element(e, pool) for e in (control.get("elements") or [])]
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r["source_match"]] = by_state.get(r["source_match"], 0) + 1
    return {"control_id": str(control.get("control_id")),
            "title": str(control.get("title") or ""),
            "current_source": control.get("requirement_source"),
            "current_authority": control.get("requirement_authority"),
            "elements": rows, "by_state": by_state,
            "needs_human_review": any(r["review_required"] for r in rows)}


def review(controls: Iterable[dict], source_path: str | Path, *,
           uploaded_by: str = "", framework: str = "MAS") -> dict[str, Any]:
    """The review artefact. Read-only against the canon by construction.

    Note what is absent: any `NEW` element detection. A passage in the source with no
    corresponding governed element could be a new obligation or could be commentary, and asserting
    the former would have the tool proposing additions to the contract. Unmatched source passages
    are surfaced for a human to read, not classified.
    """
    fp = fingerprint(source_path, uploaded_by=uploaded_by)
    pool = passages(Path(source_path).read_text(encoding="utf-8", errors="replace"))
    subject = [c for c in controls if str(c.get("framework")) == framework]
    rows = [review_control(c, pool) for c in subject]

    totals: dict[str, int] = {}
    for r in rows:
        for k, v in r["by_state"].items():
            totals[k] = totals.get(k, 0) + v
    return {
        "schema": SCHEMA,
        "artefact": "REVIEW_ONLY",
        "source": fp,
        "framework": framework,
        "controls_reviewed": len(rows),
        "elements_reviewed": sum(r["by_state"].get(k, 0) for r in rows for k in r["by_state"]),
        "passages_in_source": len(pool),
        "by_state": totals,
        "controls": rows,
        "needs_human_review": [r["control_id"] for r in rows if r["needs_human_review"]],
        "canon_modified": False,
        "note": ("Review artefact only. The governed contract is unchanged. A CHANGED or "
                 "PARTIAL or NONE match is a prompt for a person to read the source. It is not "
                 "a claim that the obligation changed, not a proposed revision, and not an "
                 "approval. semantic_change is null on every row by design."),
    }


def report(a: dict[str, Any]) -> str:
    s = a["source"]
    lines = [f"{s['file']} · sha256 {s['sha256'][:16]} · uploaded by {s['uploaded_by']} "
             f"· {s['status']}",
             f"{a['controls_reviewed']} control(s), {a['passages_in_source']} passage(s) "
             f"in source",
             f"states: {a['by_state']}",
             f"needs human review: {len(a['needs_human_review'])} control(s)"]
    for r in a["controls"][:10]:
        if r["needs_human_review"]:
            lines.append(f"  {r['control_id']:8} {r['by_state']}  {r['title'][:52]}")
    lines.append(f"canon modified: {a['canon_modified']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- reviewer determination

#: The determinations only a person can make. `UNCHANGED` is on this list deliberately: it is a
#: semantic judgement that the obligation still holds as governed, not the absence of a lexical
#: difference. A matcher scoring 0.92 has not determined UNCHANGED; it has retrieved a passage.
DETERMINATIONS = {UNCHANGED, CHANGED, NEW, REMOVED}


class DeterminationError(ValueError):
    """Raised rather than recording a determination that cannot be attributed or justified."""


def record_determination(row: dict, *, determination: str, rationale: str, reviewer: str,
                         at: str = "", passages_read: list[str] | None = None,
                         reviewer_found_passages: list[str] | None = None,
                         reviewer_found_basis: bool | None = None) -> dict:
    """Attach a human semantic determination to a review row.

    The bar mirrors `adjudicated_case_specific` in the calibration corpus, for the same reason:
    a determination nobody can be identified with, or that cites nothing, cannot be re-argued
    later and is therefore not a governance record.

    `passages_read` is required for CHANGED and NEW. Both assert something about what the source
    now says, and an assertion about a document should name the part of it that was read.
    """
    if determination not in DETERMINATIONS:
        raise DeterminationError(f"{determination!r} is not one of {sorted(DETERMINATIONS)}")
    if not str(reviewer).strip():
        raise DeterminationError("a determination must name the reviewer who made it")
    if len(str(rationale).strip()) < 15:
        raise DeterminationError("a determination needs a rationale that can be re-argued")
    read = [p for p in (passages_read or []) if str(p).strip()]
    found = [p for p in (reviewer_found_passages or []) if str(p).strip()]
    # A passage the reviewer located themselves counts as read — the requirement is that the
    # assertion cites the source, not that retrieval happened to surface it.
    if determination in (CHANGED, NEW) and not (read or found):
        raise DeterminationError(
            f"{determination} asserts what the source now says; name the passage(s) read")

    out = dict(row)
    out["reviewer_determination"] = {
        "determination": determination, "rationale": str(rationale).strip(),
        "reviewer": str(reviewer).strip(), "determined_at": at or date.today().isoformat(),
        "passages_read": read,
        # The retrieval-miss signal. `reviewer_found_passages` are passages the reviewer located
        # in the source that retrieval did not surface; `reviewer_found_basis` records whether
        # they could establish a basis at all. Together these are the only honest input to
        # retrieval adequacy — the tool cannot know what it failed to show.
        "reviewer_found_passages": found,
        "reviewer_found_basis": (bool(found) if reviewer_found_basis is None
                                 else bool(reviewer_found_basis)),
        "retrieval_miss": bool(found) and row.get("source_match") != "STRONG",
        "source_match_at_determination": row.get("source_match"),
        "match_score_at_determination": row.get("match_score"),
        # Enough to reconstruct the determination without the surrounding artefact.
        "source_id": row.get("source_id"),
        "source_hash": row.get("source_hash"),
        "control_id": row.get("control_id"),
    }
    return out


def propose_revision(row: dict, *, text: str, author: str, basis: str) -> dict:
    """A candidate element text. Only reachable once a determination exists.

    Ordering is the control. A revision proposed before anyone determined the obligation changed
    is a rewrite in search of a justification, and the tool should not be able to express it.
    """
    det = (row.get("reviewer_determination") or {}).get("determination")
    if det not in (CHANGED, NEW):
        raise DeterminationError(
            f"a revision needs a determination of {CHANGED} or {NEW} first; this row is "
            f"{det or 'undetermined'}")
    if not str(text).strip() or not str(author).strip():
        raise DeterminationError("a proposed revision needs text and a named author")
    out = dict(row)
    out["proposed_revision"] = {"text": str(text).strip(), "author": str(author).strip(),
                                "basis": str(basis).strip(),
                                "proposed_at": date.today().isoformat(),
                                "approved": False}
    return out


def approve_revision(row: dict, *, approver: str, authority: str) -> dict:
    """The only step that makes a revision eligible for a new contract version.

    Still writes nothing. Approval produces an approved_revision record; building the next
    governed version from a set of them is a separate, deliberate act.
    """
    prop = row.get("proposed_revision")
    if not prop:
        raise DeterminationError("nothing proposed to approve")
    if not str(approver).strip() or not str(authority).strip():
        raise DeterminationError("approval must name the approver and the authority they hold")
    if str(approver).strip() == prop.get("author"):
        raise DeterminationError(
            "the author of a revision cannot approve it — separation is the point of the step")
    out = dict(row)
    out["approved_revision"] = {"text": prop["text"], "approver": str(approver).strip(),
                                "authority": str(authority).strip(),
                                "approved_at": date.today().isoformat(),
                                "supersedes": row.get("governed_text")}
    out["proposed_revision"] = dict(prop, approved=True)
    return out


def determination_progress(artefact: dict) -> dict[str, Any]:
    """How much of the artefact a human has actually worked through."""
    rows = [e for c in artefact.get("controls") or [] for e in c.get("elements") or []]
    determined = [r for r in rows if r.get("reviewer_determination")]
    by = {}
    for r in determined:
        d = r["reviewer_determination"]["determination"]
        by[d] = by.get(d, 0) + 1
    return {"schema": SCHEMA, "rows": len(rows), "determined": len(determined),
            "outstanding": len(rows) - len(determined), "by_determination": by,
            "proposed": sum(1 for r in rows if r.get("proposed_revision")),
            "approved": sum(1 for r in rows if r.get("approved_revision")),
            "ready_for_new_version": bool(determined) and len(determined) == len(rows)}


def retrieval_adequacy(artefact: dict) -> dict[str, Any]:
    """The right objective: did retrieval surface what a reviewer needs to inspect?

    Measured against determinations, not against similarity. A row a reviewer determined
    UNCHANGED while retrieval returned NONE is a retrieval miss — the reviewer found the basis
    somewhere the tool did not surface. That is the number worth improving, and it cannot be
    computed until determinations exist, which is why the matcher should not be tuned first.
    """
    rows = [e for c in artefact.get("controls") or [] for e in c.get("elements") or []]
    determined = [r for r in rows if r.get("reviewer_determination")]
    if not determined:
        return {"schema": SCHEMA, "measurable": False,
                "reason": ("no reviewer determinations recorded; retrieval adequacy is defined "
                           "against what a reviewer needed, so it cannot be computed yet")}
    # A miss is now the reviewer's own report, not an inference from the score. Previously this
    # guessed from `source_match == NONE` plus a determination, which cannot distinguish "the
    # reviewer found it elsewhere" from "the reviewer determined it without a passage".
    misses = [r for r in determined if r["reviewer_determination"].get("retrieval_miss")]
    unfounded = [r for r in determined
                 if r["reviewer_determination"].get("reviewer_found_basis") is False]
    unread = [r for r in determined
              if r.get("source_match") == "STRONG"
              and not r["reviewer_determination"].get("passages_read")]
    return {"schema": SCHEMA, "measurable": True, "determined": len(determined),
            "retrieval_misses": len(misses),
            "miss_rate": round(len(misses) / len(determined), 3),
            "strong_but_unread": len(unread),
            "reviewer_found_no_basis": len(unfounded),
            "note": ("A miss is a row the reviewer could determine from the source while "
                     "retrieval surfaced nothing. Improving retrieval means reducing this, not "
                     "raising similarity scores.")}
