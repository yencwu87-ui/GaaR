#!/usr/bin/env python3
"""Model arena: blind battles on labelled twin cases. Winning earns an advisory seat, never a signature.

    python tools/gaar_arena.py check  ollama:qwen2.5:14b ollama:mistral-nemo:12b colibri mlx:muse-glimmer-30b jev
    python tools/gaar_arena.py run    ollama:qwen2.5:14b ollama:mistral-nemo:12b baseline:rules --cases 40
    python tools/gaar_arena.py board  [--run ARENA-...]
    python tools/gaar_arena.py vote   --run ARENA-... --voter "Your Name"
    python tools/gaar_arena.py judge  --run ARENA-... --judge ollama:qwen2.5:14b --a baseline:rules --b ollama:mistral-nemo:12b
    python tools/gaar_arena.py judges --run ARENA-...        each judge: consistency under order swap, agreement with truth

`run --blind-spot` adds the classes the deterministic checks cannot see (two people sharing a name): the one round where
a model can beat the rules. In the standard round the rules baseline is a calibration fixture, not a contestant.

Models run one at a time, so a 16-32 GB laptop only ever holds one. Parameters: config/arena.yaml. Results and every
attempt: ~/gaar-arena (GAAR_ARENA_HOME).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.arena import arena  # noqa: E402
from governance.arena.cases import draw  # noqa: E402
from governance.arena.contestants import NotConfigured, build  # noqa: E402


def check(specs):
    """Can each contestant answer one case? Reports reachability, the parsed answer and seconds per case."""
    case = draw(1, 1)[0]
    out = []
    for spec in specs:
        try:
            c = build(spec)
            r = c.ask(case)
            out.append({"contestant": spec, "reachable": r["error"] is None, "local": c.local, "error": r["error"],
                        "answer": r["parsed"], "seconds_per_case": r["seconds"]})
        except NotConfigured as exc:
            out.append({"contestant": spec, "reachable": False, "error": str(exc)})
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check"); c.add_argument("contestants", nargs="+")
    r = sub.add_parser("run"); r.add_argument("contestants", nargs="+")
    r.add_argument("--cases", type=int, default=40); r.add_argument("--seed", type=int, default=7)
    r.add_argument("--blind-spot", action="store_true", help="include classes the deterministic checks cannot see")
    j = sub.add_parser("judge"); j.add_argument("--run", required=True); j.add_argument("--judge", required=True)
    j.add_argument("--a", required=True); j.add_argument("--b", required=True)
    j.add_argument("--cases", type=int, default=10, help="how many shared cases to judge")
    js = sub.add_parser("judges"); js.add_argument("--run", required=True)
    b = sub.add_parser("board"); b.add_argument("--run")
    v = sub.add_parser("vote"); v.add_argument("--run", required=True); v.add_argument("--voter", required=True)
    v.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    if a.command == "check":
        print(json.dumps(check(a.contestants), indent=2))
    elif a.command == "run":
        board = arena.run(a.contestants, a.cases, a.seed, include_known_blind=a.blind_spot,
                          progress=lambda n, i, t, ans: print(f"  {n}: {i}/{t} {ans}", file=sys.stderr, flush=True))
        print(json.dumps(board, indent=2))
    elif a.command == "board":
        run_id = a.run or (arena.runs() or [{}])[-1].get("run_id")
        if not run_id:
            raise SystemExit("no arena run yet")
        print(json.dumps(arena.leaderboard(run_id), indent=2))
    elif a.command == "judge":
        from governance.arena.judge import judge_battle, judge_quality
        _, attempts = arena._rows(a.run)
        shared = sorted({x["case_id"] for x in attempts if x["contestant"] == a.a} &
                        {x["case_id"] for x in attempts if x["contestant"] == a.b})[:a.cases]
        for case in shared:
            j = judge_battle(a.judge, a.run, case, a.a, a.b)
            print(f"  {case}: {j['status']} {j['verdict'] or ''}", file=sys.stderr, flush=True)
        print(json.dumps(judge_quality(a.run), indent=2))
    elif a.command == "judges":
        from governance.arena.judge import judge_quality
        print(json.dumps(judge_quality(a.run), indent=2))
    else:
        pair = arena.blind_pair(a.run, a.seed)
        print(json.dumps({k: pair[k] for k in ("case_id", "A", "B")}, indent=2))
        choice = input("Which answer is better? A / B / TIE / NEITHER: ").strip().upper()
        print(json.dumps(arena.vote(pair, choice, a.voter), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
