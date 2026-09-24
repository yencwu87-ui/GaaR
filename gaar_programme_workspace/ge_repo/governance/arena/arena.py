"""Running the arena: every contestant answers the same cases blind; every attempt is a receipt; scores are derived."""
from __future__ import annotations

import hashlib
import itertools
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import yaml

from governance.names import require_person
from governance.watcher.store import HashChainStore

from .cases import draw
from .contestants import build

PARAMS = Path(__file__).resolve().parents[2] / "config" / "arena.yaml"
PROVENANCE = ("Ground truth: constructed digital-twin cases whose violations were designed by the project's own "
              "authors. Self-authored truth, sealed from the code but not from its authors: a regression measure, "
              "not independent qualification.")


def params() -> dict:
    return yaml.safe_load(PARAMS.read_text(encoding="utf-8"))


def home(path=None) -> Path:
    p = Path(path or os.environ.get("GAAR_ARENA_HOME") or Path.home() / "gaar-arena").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def store(path=None) -> HashChainStore:
    return HashChainStore(home(path) / "arena.jsonl", "gaar.arena.v1")


def cost(truth: str, answer: str, p: dict) -> float:
    c = p["costs"]
    if answer in ("HOLD", "INSUFFICIENT"):
        return c["hold"]
    if answer == truth:
        return 0.0
    return c["false_assurance"] if truth == "CONTRADICTED" else c["false_alarm"]


def run(specs: list[str], n_cases: int = 40, seed: int = 7, path=None, progress=None,
        include_known_blind: bool = False) -> dict:
    """Ask every contestant every case, in a shuffled order per contestant; record each attempt.

    Scores are computed later from these receipts exactly as attempted: nothing is validated or corrected first."""
    p = params()
    contestants = [build(s) for s in specs]
    if len({c.name for c in contestants}) != len(contestants):
        raise ValueError("each contestant may enter once")
    cases = draw(n_cases, seed, include_known_blind=include_known_blind)
    run_id = "ARENA-" + hashlib.sha256(f"{specs}|{n_cases}|{seed}|{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:12]
    s = store(path)
    s.append("ArenaRunStarted", {"run_id": run_id, "contestants": [c.name for c in contestants], "cases": n_cases,
                                 "seed": seed, "round": "blind-spot" if include_known_blind else "standard",
                                 "params_sha256": hashlib.sha256(PARAMS.read_bytes()).hexdigest(),
                                 "params": p, "provenance": PROVENANCE,
                                 "started_at": datetime.now(timezone.utc).isoformat()})
    rng = random.Random(seed)
    stop_after = p.get("stop_after_consecutive_errors", 5)
    for contestant in contestants:
        order = list(cases)
        rng.shuffle(order)
        failing = 0
        for i, case in enumerate(order, 1):
            result = contestant.ask(case)
            failing = failing + 1 if result.get("error") else 0
            s.append("ArenaAttempt", {"run_id": run_id, "contestant": contestant.name, "family": contestant.family,
                                      "local": contestant.local, "case_id": case["case_id"], "truth": case["truth"],
                                      "violation": case["violation"], "form": case["form"],
                                      "prompt_sha256": hashlib.sha256(case["prompt"].encode()).hexdigest(), **result})
            if progress:
                progress(contestant.name, i, len(order), result["parsed"]["answer"])
            if failing >= stop_after:
                # Kit v23: a contestant that cannot be reached is stopped, not asked 100 times. The failed attempts
                # stay on record; the board shows it stopped, and too few cases can never earn a seat.
                s.append("ArenaContestantStopped", {"run_id": run_id, "contestant": contestant.name,
                                                    "after_attempts": i, "last_error": result["error"],
                                                    "reason": f"{stop_after} consecutive failed calls"})
                if progress:
                    progress(contestant.name, i, len(order), f"STOPPED: {stop_after} failed calls in a row")
                break
    s.append("ArenaRunFinished", {"run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat()})
    return leaderboard(run_id, path)


def _rows(run_id, path=None):
    rows = [r["payload"] for r in store(path).read()]
    started = next((r for r in rows if r.get("run_id") == run_id and "contestants" in r), None)
    if started is None:
        raise ValueError(f"no arena run {run_id}")
    attempts = [r for r in rows if r.get("run_id") == run_id and "case_id" in r and "parsed" in r]
    return started, attempts


def rows_all(path=None) -> list[dict]:
    return [r["payload"] for r in store(path).read()]


def runs(path=None) -> list[dict]:
    return [r["payload"] for r in store(path).read() if r["record_type"] == "ArenaRunStarted"]


def leaderboard(run_id: str, path=None) -> dict:
    started, attempts = _rows(run_id, path)
    p = started["params"]
    by = {}
    for a in attempts:
        by.setdefault(a["contestant"], {})[a["case_id"]] = a
    table = []
    for name, answers in by.items():
        tp = fp = fn = tn = holds = fa = 0
        total = 0.0
        for a in answers.values():
            ans, truth = a["parsed"]["answer"], a["truth"]
            total += cost(truth, ans, p)
            if ans in ("HOLD", "INSUFFICIENT"):
                holds += 1
                fn += truth == "CONTRADICTED"
                continue
            if truth == "CONTRADICTED":
                tp += ans == "CONTRADICTED"
                fn += ans != "CONTRADICTED"
                fa += ans == "SUPPORTED"
            else:
                fp += ans == "CONTRADICTED"
                tn += ans == "SUPPORTED"
        n = len(answers)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        q = p["qualification"]
        meets = (precision is not None and recall is not None and precision >= q["precision"] and recall >= q["recall"]
                 and fa <= q["max_false_assurance"] and n >= q["min_cases"])
        table.append({"contestant": name, "cases": n, "weighted_cost": round(total, 2),
                      "cost_per_case": round(total / n, 3) if n else None,
                      "precision": round(precision, 3) if precision is not None else None,
                      "recall": round(recall, 3) if recall is not None else None,
                      "false_assurance": fa, "false_alarms": fp, "holds": holds,
                      "errors": sum(1 for a in answers.values() if a.get("error")),
                      "median_seconds": sorted(a["seconds"] for a in answers.values())[n // 2] if n else None,
                      "meets_numeric_thresholds": meets})
    stopped = {r["contestant"]: r for r in rows_all(path) if r.get("run_id") == run_id and "after_attempts" in r}
    for row in table:
        if row["contestant"] in stopped:
            row["stopped"] = f"after {stopped[row['contestant']]['after_attempts']} attempts: {stopped[row['contestant']]['reason']}"
    elo = _elo(by, p)
    for row in table:
        row["elo"] = elo.get(row["contestant"])
    table.sort(key=lambda r: (r["cost_per_case"] if r["cost_per_case"] is not None else 9e9, -(r["elo"] or 0)))
    fixtures = _calibration(table, started.get("round", "standard"))
    return {"run_id": run_id, "round": started.get("round", "standard"), "contestants": started["contestants"],
            "cases": started["cases"], "table": table,
            "cost_policy": {"false_assurance": p["costs"]["false_assurance"], "false_alarm": p["costs"]["false_alarm"],
                            "hold": p["costs"]["hold"],
                            "false_assurance_to_false_alarm": p["costs"]["false_assurance"] / p["costs"]["false_alarm"],
                            "params_sha256": started.get("params_sha256"),
                            "raw_metrics_beside_weighted": ["precision", "recall", "false_assurance", "false_alarms", "holds"]},
            "params": p["costs"], "provenance": started["provenance"], "calibration": fixtures,
            "qualification_note": p["qualification"]["note"],
            "advisory_seat": None if fixtures["status"] == "SCORER_SUSPECT" else
            [r["contestant"] for r in table if r["meets_numeric_thresholds"] and not r["contestant"].startswith("baseline:")] or None}


FIXTURES = {
    "baseline:rules": "Calibration fixture, not a contestant result: the checks scoring their own twin must be perfect, "
                      "or the scorer is broken. Never quote it as a finding.",
    "baseline:always-supported": "Cost-function check: always saying 'authorised' must score worst on false assurance.",
    "baseline:always-contradicted": "Alarm-fatigue floor: flags everything, no false assurance, many false alarms.",
}


def _calibration(table: list[dict], round_: str) -> dict:
    """The baselines are instruments. If they do not read as designed, no contestant's score can be trusted."""
    rows = {r["contestant"]: r for r in table}
    checks = []
    if "baseline:rules" in rows and round_ == "standard":
        r = rows["baseline:rules"]
        checks.append({"fixture": "baseline:rules", "expected": "cost 0, no false assurance",
                       "held": r["weighted_cost"] == 0 and r["false_assurance"] == 0})
    if "baseline:always-supported" in rows:
        worst = max(r["cost_per_case"] for r in table)
        checks.append({"fixture": "baseline:always-supported", "expected": "highest cost per case",
                       "held": rows["baseline:always-supported"]["cost_per_case"] == worst})
    status = ("NO_FIXTURES" if not checks else "SCORER_CALIBRATED" if all(c["held"] for c in checks)
              else "SCORER_SUSPECT")
    return {"status": status, "checks": checks, "labels": {k: v for k, v in FIXTURES.items() if k in rows}}


def _elo(by: dict, p: dict) -> dict:
    """Pairwise: on each shared case, the lower cost wins. Elo over a fixed, seeded order of those comparisons."""
    rating = {name: float(p["elo"]["start"]) for name in by}
    k = p["elo"]["k"]
    pairs = []
    for a, b in itertools.combinations(sorted(by), 2):
        for case in sorted(set(by[a]) & set(by[b])):
            ca = cost(by[a][case]["truth"], by[a][case]["parsed"]["answer"], {"costs": p["costs"]})
            cb = cost(by[b][case]["truth"], by[b][case]["parsed"]["answer"], {"costs": p["costs"]})
            pairs.append((a, b, 1.0 if ca < cb else 0.0 if ca > cb else 0.5))
    random.Random(0).shuffle(pairs)
    for a, b, score in pairs:
        expected = 1 / (1 + 10 ** ((rating[b] - rating[a]) / 400))
        rating[a] += k * (score - expected)
        rating[b] -= k * (score - expected)
    return {n: round(r) for n, r in rating.items()}


def blind_pair(run_id: str, seed: int, path=None) -> dict:
    """Two answers to one case, identities hidden and order randomised, for a person to judge."""
    _, attempts = _rows(run_id, path)
    rng = random.Random(seed)
    cases = sorted({a["case_id"] for a in attempts})
    case = rng.choice(cases)
    pair = rng.sample([a for a in attempts if a["case_id"] == case], 2)
    return {"run_id": run_id, "case_id": case, "A": {"answer": pair[0]["parsed"], "raw": pair[0]["raw"][:1500]},
            "B": {"answer": pair[1]["parsed"], "raw": pair[1]["raw"][:1500]},
            "_sealed": {"A": pair[0]["contestant"], "B": pair[1]["contestant"]}}


def vote(pair: dict, choice: str, voter: str, path=None) -> dict:
    """A person's blind preference. It becomes a labelled judgement with the voter as its provenance."""
    if choice not in ("A", "B", "TIE", "NEITHER"):
        raise ValueError("vote A, B, TIE or NEITHER")
    voter = require_person(voter, "a vote needs the name of the person casting it")
    return store(path).append("ArenaHumanVote", {
        "run_id": pair["run_id"], "case_id": pair["case_id"], "choice": choice, "voter": voter,
        "revealed_after_vote": pair["_sealed"], "provenance": "governance owner (blind); not an independent labeller",
        "at": datetime.now(timezone.utc).isoformat()})["payload"]
