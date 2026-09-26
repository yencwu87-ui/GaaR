"""Requirement basis: which passage of the source instrument backs each control (kit v22).

A control is only as good as the requirement it rests on. The contracts state each control's requirement in the
project's own words (MAS: an internal interpretation; the others: drafts) and none cites the instrument text it came
from. This proposes that basis: for every control, the passages in its instrument that most likely back it, quoted
verbatim with their character offsets and the instrument's hash, so anyone can check the quote against the source.

A proposed basis is a lead for a person to confirm, never an anchor on its own. Where no passage shares enough
distinctive terms with the control, the control is reported as having no demonstrated basis, which is the finding.
ISO/IEC 42001 is a licensed standard the repository does not hold, so its controls cannot be anchored here: they read
INSTRUMENT_UNAVAILABLE, which is not the same as having no basis.

Confirmation (the governance-basis layer, mapping-review pattern): a named person confirms or rejects one control's
basis at a time, as its own recorded event, after the quote is re-verified against the instrument. Bulk confirmation is
refused: a machine-proposed basis accepted in bulk would be false assurance one level up. Tier 1 (the pilot's critical
path, config/basis_scope.yaml) is confirmed first; the rest stay visible as proposals.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from governance.names import require_person

ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTS = {
    "MAS": "Final_Consultation_Paper_on_Guidelines_on_AI_Risk_Management_ForRelease.txt",
    "MGF Agentic": "Mgf_for_Agentic_AI_(atx_Release)_July_2026.txt",
    "SAFR": "SAFR.txt",
    "NIST AI RMF": "AI_RMF_Playbook.txt",
}
# What each held instrument is. Every quote carries this flag: a consultation draft is not a requirement in force.
AUTHORITY = {
    "MAS": "CONSULTATION_DRAFT: MAS consultation paper on AI risk management guidelines; not in force",
    "MGF Agentic": "VOLUNTARY_FRAMEWORK: Model AI Governance Framework for Agentic AI v1.5; not binding",
    "SAFR": "WHITE_PAPER: Safeguards for Agentic Finance at Runtime v1.0; no regulatory force",
    "NIST AI RMF": "VOLUNTARY_GUIDANCE: NIST AI RMF Playbook; not binding",
}
DECISIONS = ("CONFIRMED", "REJECTED", "NO_BASIS_IN_INSTRUMENT")
SCOPE = ROOT / "config" / "basis_scope.yaml"
STOP = set("the and for that with this from are was were been have has had its their them they which who what when "
           "where how into onto upon over under such also other than then those these should shall must may can "
           "will would could any all each every both more most some organisation organization organisations "
           "including include includes within across between about ensure ensures ensuring".split())
MIN_SHARED = 3                      # distinctive terms a passage must share with the control to count as a basis


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower()) if t not in STOP]


def passages(text: str, max_words: int = 110) -> list[dict]:
    """Paragraph-sized windows with exact character offsets into the instrument."""
    out, start = [], 0
    for block in re.split(r"(\n\s*\n)", text):
        if block.strip() and not re.fullmatch(r"\n\s*\n", block):
            words = list(re.finditer(r"\S+", block))
            for i in range(0, len(words), max_words):
                chunk = words[i:i + max_words]
                a, b = start + chunk[0].start(), start + chunk[-1].end()
                out.append({"start": a, "end": b, "text": text[a:b]})
        start += len(block)
    merged = []
    for p in out:                                       # a stray heading joins the passage after it
        if merged and len(merged[-1]["text"].split()) < 12:
            prev = merged.pop()
            p = {"start": prev["start"], "end": p["end"], "text": text[prev["start"]:p["end"]]}
        merged.append(p)
    return merged


class Instrument:
    def __init__(self, framework: str):
        self.framework, self.file = framework, INSTRUMENTS[framework]
        path = ROOT / "instruments" / self.file
        self.text = path.read_text(encoding="utf-8")
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.passages = passages(self.text)
        self.tokens = [_tokens(p["text"]) for p in self.passages]
        self.df = Counter(t for toks in self.tokens for t in set(toks))
        self.avg = sum(map(len, self.tokens)) / max(1, len(self.tokens))

    def best(self, query: str, top: int = 2) -> list[dict]:
        q = set(_tokens(query))
        n, scored = len(self.passages), []
        for p, toks in zip(self.passages, self.tokens):
            tf, score = Counter(toks), 0.0
            for t in q & set(toks):
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(toks) / self.avg))
            shared = sorted(q & set(toks), key=lambda t: self.df[t])
            if score > 0:
                scored.append((score, shared, p))
        scored.sort(key=lambda x: -x[0])
        return [{"quote": " ".join(p["text"].split())[:600], "start": p["start"], "end": p["end"], "score": round(s, 2),
                 "shared_terms": shared[:8], "strong": len(shared) >= MIN_SHARED,
                 "authority": AUTHORITY[self.framework]} for s, shared, p in scored[:top]]


def ledger_path() -> Path:
    """Confirmations are runtime state: GAAR_BASIS_LEDGER, or next to the workbench's own data."""
    from governance.paths import workbench_data
    return Path(os.environ.get("GAAR_BASIS_LEDGER") or workbench_data() / "basis_confirmations.jsonl").resolve()


def _store():
    from governance.watcher.store import HashChainStore
    return HashChainStore(ledger_path(), "gaar.basis.v1")


def tier1() -> set[tuple[str, str]]:
    return {(c["framework"], c["control_id"]) for c in yaml.safe_load(SCOPE.read_text(encoding="utf-8"))["tier1"]}


def confirmations() -> dict[tuple[str, str], dict]:
    """The latest decision per control. Earlier decisions stay in the chain."""
    latest = {}
    for r in _store().read():
        latest[(r["payload"]["framework"], r["payload"]["control_id"])] = r["payload"]
    return latest


def report(frameworks=None) -> dict:
    frameworks = frameworks or list(INSTRUMENTS) + ["ISO 42001"]
    out, summary = [], {}
    first, decided = tier1(), confirmations()
    for path in sorted((ROOT / "governance/knowledge/contracts").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        fw = data["framework"]
        if fw not in frameworks:
            continue
        inst = Instrument(fw) if fw in INSTRUMENTS else None
        counts = Counter()
        for c in data["controls"]:
            query = " ".join([c.get("title", ""), c.get("requirement", "")] + [e.get("text", "") for e in c.get("elements") or []])
            candidates = inst.best(query) if inst else []
            status = ("INSTRUMENT_UNAVAILABLE" if inst is None else "PROPOSED_BASIS" if any(x["strong"] for x in candidates)
                      else "NO_DEMONSTRATED_BASIS")
            decision = decided.get((fw, c["control_id"]))
            if decision:
                status = {"CONFIRMED": "CONFIRMED_BASIS", "REJECTED": "PROPOSAL_REJECTED",
                          "NO_BASIS_IN_INSTRUMENT": "NO_BASIS_CONFIRMED"}[decision["decision"]]
            counts[status] += 1
            out.append({"framework": fw, "control_id": c["control_id"], "title": c.get("title", ""), "status": status,
                        "tier": 1 if (fw, c["control_id"]) in first else 2, "decision": decision,
                        "requirement_authority": c.get("requirement_authority"),
                        "instrument": inst.file if inst else None, "instrument_sha256": inst.sha256 if inst else None,
                        "candidates": candidates})
        summary[fw] = dict(counts)
    t1 = [c for c in out if c["tier"] == 1]
    return {"summary": summary, "controls": out,
            "tier1": {"controls": len(t1), "confirmed": sum(c["status"] == "CONFIRMED_BASIS" for c in t1),
                      "open": [f"{c['framework']} {c['control_id']}" for c in t1 if c["decision"] is None]},
            "defect": "D20: no control cites the instrument it derives from (docs/quality/defect_register.md)",
            "meaning": "A proposed basis is a verbatim passage for a person to confirm, not an anchor. "
                       "No demonstrated basis means no passage shares enough distinctive terms with the control. "
                       "Instrument unavailable means the instrument is not held, not that no basis exists."}


def confirm(framework: str, control_id: str, candidate: int, decision: str, by: str, note: str = "") -> dict:
    """One person, one control, one recorded decision, on a quote re-verified against the instrument now."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    by = require_person(by, "a basis decision needs the name of the person making it")
    if framework not in INSTRUMENTS:
        raise ValueError(f"{framework}: instrument unavailable, so there is no passage to confirm")
    hit = [c for c in report([framework])["controls"] if c["control_id"] == control_id]
    if not hit:
        raise ValueError(f"no control {framework} {control_id}")
    cands = hit[0]["candidates"]
    chosen = None
    if decision != "NO_BASIS_IN_INSTRUMENT":
        if not 1 <= candidate <= len(cands):
            raise ValueError(f"{framework} {control_id} has candidates 1 to {len(cands)}")
        chosen = cands[candidate - 1]
        if not verify_quote(chosen, framework):
            raise ValueError("the quote no longer matches the instrument; re-run the report")
    return _store().append("RequirementBasisDecided", {
        "framework": framework, "control_id": control_id, "decision": decision, "by": by, "note": note,
        "tier": hit[0]["tier"], "candidate": chosen, "instrument": hit[0]["instrument"],
        "instrument_sha256": hit[0]["instrument_sha256"], "authority": AUTHORITY[framework], "rigor": "per-control",
        "at": datetime.now(timezone.utc).isoformat()})["payload"]


def confirm_many(*_args, **_kwargs):
    """Kept so the refusal is explicit: bulk acceptance of machine-proposed bases is not a confirmation."""
    raise ValueError("bulk confirmation is refused: confirm each control's basis on its own record, after reading "
                     "its passage")


def verify_quote(candidate: dict, framework: str) -> bool:
    """The quote really is the instrument's text at those offsets (whitespace normalised)."""
    inst = Instrument(framework)
    return " ".join(inst.text[candidate["start"]:candidate["end"]].split())[:600] == candidate["quote"]
