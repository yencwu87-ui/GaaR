"""A model as judge, held to the same discipline as a contestant (kit v22).

Scores in the arena come only from the sealed truth. A judge's verdict never changes a score; it is itself measured:
how often, on cases where the truth says which answer was better, did the judge agree?

Three rules, each enforced here:
- Order swap. The judge sees the pair twice, in both orders. A judge that gives different verdicts in the two orders is
  judging position, not substance: that judgement is discarded and recorded as discarded.
- No self-judging. A judge may not judge a battle it is in, or one involving its own model family.
- Egress. A judge that is not on this machine sees constructed cases only (arena cases are always constructed).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .arena import _rows, cost, params, store
from .cases import draw
from .contestants import Contestant, build

JUDGE_QUESTION = (
    "Two reviewers answered the same question about one production change. Judge which answer is better grounded in "
    "the records: right verdict, and violations that the records actually show. Reply with JSON only: "
    "{\"better\": \"A|B|TIE\", \"reason\": \"one sentence\"}")


def _prompt(case_prompt: str, first: dict, second: dict) -> str:
    return (JUDGE_QUESTION + "\n\nQUESTION AND RECORDS:\n" + case_prompt +
            "\n\nANSWER A:\n" + json.dumps(first["parsed"]) + "\n\nANSWER B:\n" + json.dumps(second["parsed"]))


def _verdict(raw: str) -> str:
    try:
        m = re.search(r"\{.*\}", raw or "", re.S)
        v = str(json.loads(m.group(0)).get("better", "")).strip().upper() if m else ""
    except (ValueError, AttributeError):
        v = ""
    return v if v in ("A", "B", "TIE") else "HOLD"


def judge_battle(judge: str | Contestant, run_id: str, case_id: str, a: str, b: str, path=None) -> dict:
    started, attempts = _rows(run_id, path)
    judge = build(judge) if isinstance(judge, str) else judge
    by = {(x["contestant"], x["case_id"]): x for x in attempts}
    if (a, case_id) not in by or (b, case_id) not in by:
        raise ValueError(f"{a} and {b} did not both answer {case_id} in {run_id}")
    first, second = by[(a, case_id)], by[(b, case_id)]
    if judge.name in (a, b):
        raise ValueError("a contestant may not judge its own battle")
    if judge.family in (first["family"], second["family"]):
        raise ValueError(f"a judge may not judge a battle involving its own model family ({judge.family})")
    cases = {c["case_id"]: c for c in draw(started["cases"], started["seed"],
                                           include_known_blind=started.get("round") == "blind-spot")}
    case = cases[case_id]
    if not judge.local and case["provenance"] != "constructed":      # arena cases are constructed; kept as a guard
        raise PermissionError(f"{judge.name} is not on this machine; it may only see constructed cases")
    raw_ab = judge.raw(_prompt(case["prompt"], first, second))
    raw_ba = judge.raw(_prompt(case["prompt"], second, first))
    v_ab, v_ba = _verdict(raw_ab), {"A": "B", "B": "A"}.get(_verdict(raw_ba), _verdict(raw_ba))
    if "HOLD" in (v_ab, v_ba):
        status, verdict = "HOLD", None
    elif v_ab != v_ba:
        status, verdict = "DISCARDED_INCONSISTENT", None
    else:
        status, verdict = "CONSISTENT", v_ab
    p = params()
    ca, cb = cost(first["truth"], first["parsed"]["answer"], p), cost(second["truth"], second["parsed"]["answer"], p)
    truth_better = "A" if ca < cb else "B" if cb < ca else "TIE"
    return store(path).append("ArenaJudgement", {
        "run_id": run_id, "case_id": case_id, "judge": judge.name, "judge_family": judge.family, "A": a, "B": b,
        "verdict_in_order": v_ab, "verdict_swapped_mapped_back": v_ba, "status": status, "verdict": verdict,
        "truth_better": truth_better, "agrees_with_truth": (verdict == truth_better) if verdict else None,
        "raw": [raw_ab[:1500], raw_ba[:1500]], "affects_scores": False,
        "at": datetime.now(timezone.utc).isoformat()})["payload"]


def judge_quality(run_id: str, path=None) -> dict:
    """How far each judge can be trusted: consistency under order swap, then agreement with the truth."""
    rows = [r["payload"] for r in store(path).read()
            if r["record_type"] == "ArenaJudgement" and r["payload"]["run_id"] == run_id]
    out = {}
    for r in rows:
        q = out.setdefault(r["judge"], {"judgements": 0, "consistent": 0, "discarded_inconsistent": 0, "holds": 0,
                                        "agrees_with_truth": 0})
        q["judgements"] += 1
        q["consistent"] += r["status"] == "CONSISTENT"
        q["discarded_inconsistent"] += r["status"] == "DISCARDED_INCONSISTENT"
        q["holds"] += r["status"] == "HOLD"
        q["agrees_with_truth"] += bool(r["agrees_with_truth"])
    for q in out.values():
        q["agreement_rate"] = round(q["agrees_with_truth"] / q["consistent"], 3) if q["consistent"] else None
    return {"run_id": run_id, "judges": out,
            "meaning": "A judge never changes a score. Inconsistent verdicts under order swap are discarded."}
