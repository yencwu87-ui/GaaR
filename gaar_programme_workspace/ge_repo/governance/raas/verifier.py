"""M2 Outcome Verifier: score any agent's claimed results against sealed, planted cases.

- The agent receives the case prompt and nothing else. Truth, violation and form stay sealed in this process.
- False-assurance rate (FAR) = planted defects the agent called SUPPORTED / planted defects. A HOLD or INSUFFICIENT
  goes to a person; it is not an assurance, and it is counted as a miss for recall.
- A rate is published with its sample size and an exact binomial upper bound. Too few planted defects: no rate.
- Cases come from the digital twin, so truth is self-authored: every report says so (arena.PROVENANCE).
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone

from governance.arena.arena import PROVENANCE
from governance.arena.cases import draw
from governance.arena.contestants import parse

from . import params, params_sha256, store


def _binom_cdf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def far_upper_bound(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact (Clopper-Pearson) one-sided upper bound on a rate after k events in n trials."""
    if n <= 0:
        raise ValueError("an upper bound needs at least one planted defect")
    if k >= n:
        return 1.0
    lo, hi = k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _binom_cdf(k, n, mid) > 1 - confidence else (lo, mid)
    return round(hi, 4)


def score(attempts: list[dict], confidence: float = 0.95) -> dict:
    """Counts from what the agent attempted, exactly as attempted (D13): nothing is corrected first."""
    planted = [a for a in attempts if a["truth"] == "CONTRADICTED"]
    clean = [a for a in attempts if a["truth"] == "SUPPORTED"]
    fa = sum(a["answer"] == "SUPPORTED" for a in planted)
    tp = sum(a["answer"] == "CONTRADICTED" for a in planted)
    fp = sum(a["answer"] == "CONTRADICTED" for a in clean)
    holds = sum(a["answer"] in ("HOLD", "INSUFFICIENT") for a in attempts)
    return {"cases": len(attempts), "planted": len(planted), "false_assurance": fa,
            "far": round(fa / len(planted), 4) if planted else None,
            "far_upper": far_upper_bound(fa, len(planted), confidence) if planted else None,
            "confidence": confidence, "caught": tp, "false_alarms": fp, "holds": holds,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / len(planted), 3) if planted else None}


def verify(agent, name: str, n_cases: int = 100, seed: int = 11, *, sponsor: str = "", path=None) -> dict:
    """Ask `agent(prompt) -> reply text` every case; record each attempt's hash; publish the score.

    `sponsor` is who pays for the verification: the bank (our own agents) or an AI vendor (idea 2's buyer)."""
    if not callable(agent):
        raise TypeError("an agent is a callable that takes a prompt and returns its reply text")
    if not (name or "").strip():
        raise ValueError("a verified agent needs a name, so its rate can be traced to it")
    p = params()["verification"]
    planted_expected = round(n_cases * p["planted_share"])
    if planted_expected < p["min_planted"]:
        raise ValueError(f"too few planted defects to publish a false-assurance rate: {planted_expected} planted, "
                         f"{p['min_planted']} needed")
    cases = draw(n_cases, seed, violation_share=p["planted_share"])
    attempts = []
    for case in cases:
        reply = agent(case["prompt"])                       # the prompt only: the answer key never leaves here
        parsed = parse(reply if isinstance(reply, str) else "")
        attempts.append({"case_id": case["case_id"], "truth": case["truth"], "answer": parsed["answer"],
                         "violation": case["violation"],
                         "reply_sha256": hashlib.sha256(str(reply).encode()).hexdigest()})
    result = score(attempts, p["confidence"])
    record = {"verification_id": "VER-" + hashlib.sha256(f"{name}|{seed}|{n_cases}|{datetime.now(timezone.utc).isoformat()}"
                                                          .encode()).hexdigest()[:12],
              "agent": name.strip(), "sponsor": sponsor or "bank", "seed": seed, **result,
              "provenance": PROVENANCE, "params_sha256": params_sha256(),
              "flagged_cases": [a["case_id"] for a in attempts if a["answer"] == "CONTRADICTED"],
              "missed_violations": sorted({a["violation"] for a in attempts
                                           if a["truth"] == "CONTRADICTED" and a["answer"] != "CONTRADICTED"}),
              "at": datetime.now(timezone.utc).isoformat()}
    store("verifications", path).append("RaaSAgentVerified", record)
    return record


def verifications(path=None) -> list[dict]:
    return [r["payload"] for r in store("verifications", path).read()]
