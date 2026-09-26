#!/usr/bin/env python3
"""The digital twin: a constructed bank (Meranti Bank) that produces fresh weekly change evidence with planted,
sealed violations. It exercises the pipeline; it is not independent ground truth.

    python tools/gaar_twin.py bench [--weeks 500]                  property run: the checks against random plants
    python tools/gaar_twin.py inbox --config ~/gaar-twin/operations.json --week 5 --seed 42
    python tools/gaar_twin.py score --config ~/gaar-twin/operations.json          the series' own records vs the keys
    python tools/gaar_twin.py adjudication [--confirm A-001 --by "Your Name"]    key/check disagreements, settled

A twin series is an ordinary constructed-demonstration series with more periods:
    python tools/gaar_recurring.py authorise --constructed-demo --workspace ~/gaar-twin --periods 12 ...
Keys are sealed in <workspace>/twin_keys, outside the evidence inbox; no procedure reads them.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.twin.generator import KNOWN_BLIND, VIOLATIONS, generate_period, load_key, run_checks, score, seal  # noqa: E402


def bench(args):
    planted = detected = fps = codes = incidental = 0
    by_kind, missed_by_kind, blind = Counter(), Counter(), Counter()
    ends = ["2026-09-29T00:00:00+08:00", "2026-10-06T00:00:00+08:00"]
    for seed in range(args.weeks):
        g = generate_period(seed, ends[seed % 2])
        r = score(run_checks(g), g["answer_key"], [c["event_id"] for c in g["changes"]["changes"]])
        planted, detected, fps = planted + r["planted"], detected + r["detected"], fps + len(r["false_positives"])
        codes, incidental = codes + r["planted_codes"], incidental + r["incidental_codes"]
        blind.update(r["known_blind"])
        by_kind.update(p["violation"] for p in g["answer_key"]["planted"])
        missed_by_kind.update(m["violation"] for m in r["missed"])
    return {"weeks": args.weeks, "planted": planted, "detected": detected, "false_positives": fps,
            "detection_rate": round(detected / planted, 4) if planted else None,
            "planted_codes": codes, "incidental_codes": incidental,
            "by_violation": {k: {"planted": by_kind[k], "missed": missed_by_kind[k]} for k in VIOLATIONS
                             if k not in KNOWN_BLIND},
            "known_blind": {k: {"planted": blind["planted"], "detected": blind["detected"], "why": why}
                            for k, why in KNOWN_BLIND.items()},
            "scope": f"Robustness across randomised placement, count and form of {len(VIOLATIONS) - len(KNOWN_BLIND)} "
                     "self-authored violation classes. Not coverage of novel classes (external packs own that) and "
                     "not independent ground truth.",
            "meaning": "Regression robustness of the deterministic checks against randomly placed, self-authored "
                       "violations. Not independent ground truth."}


def inbox(args):
    from governance.operations.runtime import load
    from governance.production import recurring
    config, root = load(Path(args.config).expanduser())
    payload = recurring.verify(config, root)
    if not payload.get("constructed_demo"):
        raise ValueError("twin evidence goes only into a signed constructed-demonstration series, never a real one")
    if not 1 <= args.week <= len(payload["periods"]):
        raise ValueError(f"the series has periods 1 to {len(payload['periods'])}")
    period = payload["periods"][args.week - 1]
    g = generate_period(args.seed, period["as_of"], scope=payload["system_id"], cadence_days=payload["cadence_days"])
    folder = root / config["periodic_evidence"]["inbox"] / period["label"]
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / "changes.json").write_text(json.dumps(g["changes"], indent=1))
    (folder / "population.json").write_text(json.dumps(g["population"], indent=1))
    sealed = seal(g["answer_key"], root / "twin_keys")
    return {"status": "TWIN_EXPORTS_ARRIVED", "period": period["label"], "changes": g["answer_key"]["changes"],
            "folder": str(folder), "key_sealed": sealed["key"], "commitment": sealed["sha256"],
            "note": "the planted count is in the sealed key; read it after scoring, not before reviewing"}


def score_series(args):
    from governance.operations.runtime import load
    from governance.production import recurring
    config, root = load(Path(args.config).expanduser())
    payload = recurring.load(config, root)["payload"]
    out, totals = [], Counter()
    for period in payload["periods"]:
        keys = sorted((root / "twin_keys").glob(f"key-{period['as_of'][:10]}-seed*.json"))
        journal = recurring._journal(config, root, period["investigation_id"])
        if not keys or not journal or not journal.latest("obligation_reconciliation"):
            continue
        key = load_key(keys[-1])
        rec = journal.latest("obligation_reconciliation")["payload"]
        found = {}
        for issue in rec["issues"]:
            detail = issue.get("detail") or {}
            for eid in ([issue.get("event_id")] if issue.get("event_id") else
                        detail.get("missing_primary", []) + detail.get("missing_independent", [])):
                found.setdefault(eid, set()).add(issue["code"])
        changes = json.loads((root / config["periodic_evidence"]["inbox"] / period["label"] / "changes.json").read_text())
        r = score(found, key, [c["event_id"] for c in changes["changes"]])
        totals.update(planted=r["planted"], detected=r["detected"], false_positives=len(r["false_positives"]),
                      known_blind_planted=r["known_blind"]["planted"], known_blind_detected=r["known_blind"]["detected"])
        out.append({"period": period["label"], **{k: r[k] for k in ("planted", "detected", "detection_rate")},
                    "missed": r["missed"], "false_positives": r["false_positives"]})
    return {"periods": out, "totals": dict(totals),
            "provenance": "constructed twin; self-authored truth, sealed from the code but not from its authors"}


def adjudications(args):
    from governance.twin import adjudication
    if args.confirm:
        return {"confirmed": adjudication.confirm(args.confirm, args.by, args.note)}
    return {"adjudications": adjudication.status(), "log": str(adjudication.LOG)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("bench")
    b.add_argument("--weeks", type=int, default=500)
    i = sub.add_parser("inbox")
    i.add_argument("--config", required=True)
    i.add_argument("--week", type=int, required=True)
    i.add_argument("--seed", type=int, required=True)
    s = sub.add_parser("score")
    s.add_argument("--config", required=True)
    a = sub.add_parser("adjudication", help="the key/check disagreements and who settled them")
    a.add_argument("--confirm", help="an adjudication id you have checked against the generated data")
    a.add_argument("--by", default="")
    a.add_argument("--note", default="")
    args = parser.parse_args()
    result = {"bench": bench, "inbox": inbox, "score": score_series, "adjudication": adjudications}[args.command](args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
