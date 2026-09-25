#!/usr/bin/env python3
"""Real-records pilot: change controls on a public repository's own history (kit v31).

    python tools/gaar_realrecords.py plan     --repo python-poetry/poetry --from 2026-03-01 --to 2026-09-01
    python tools/gaar_realrecords.py approve  --repo python-poetry/poetry --by "Your Name"
    python tools/gaar_realrecords.py collect  --repo python-poetry/poetry      (rerun to resume after a stop)
    python tools/gaar_realrecords.py evaluate --repo python-poetry/poetry
    python tools/gaar_realrecords.py sample   --repo python-poetry/poetry
    python tools/gaar_realrecords.py label    --repo ... --item E01 --label TRUE_EXCEPTION --by "Your Name" \\
                                              --provenance self [--note "what you saw"]
    python tools/gaar_realrecords.py score    --repo python-poetry/poetry
    python tools/gaar_realrecords.py status   --repo python-poetry/poetry

Collection needs a fine-grained GitHub token with read-only access to public repositories and no other permission.
On a Mac it is read from the Keychain entry the plan names (gaar-github) at the moment of use, so it is never in any
shell's environment. Elsewhere, set GAAR_GITHUB_TOKEN for the one collect command. Only names are ever written down.
The plan also pins git's own history of the window, which the API collection must cover (git must be installed).
The labelling protocol is docs/pilot/labeling_protocol.md. Everything is kept in ~/gaar-realrecords/<owner>__<repo>/.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance import realrecords as rr  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "approve", "collect", "evaluate", "sample", "packet", "review-rubric", "label", "score",
                 "status"):
        s = sub.add_parser(name)
        s.add_argument("--repo", required=True)
        if name == "plan":
            s.add_argument("--from", dest="start", required=True)
            s.add_argument("--to", dest="end", required=True)
            s.add_argument("--token-env", default="GAAR_GITHUB_TOKEN")
            s.add_argument("--max-requests", type=int, default=2000)
            s.add_argument("--keychain-service", default="gaar-github")
        if name in ("approve", "label", "review-rubric"):
            s.add_argument("--by", required=True)
        if name == "label":
            s.add_argument("--item", required=True)
            s.add_argument("--label", required=True)
            s.add_argument("--provenance", required=True, choices=rr.PROVENANCE)
            s.add_argument("--note", default="")
        if name == "review-rubric":
            s.add_argument("--provenance", required=True, choices=rr.PROVENANCE)
            s.add_argument("--verdict", required=True, choices=rr.RUBRIC_VERDICTS)
            s.add_argument("--note", default="")
    args = parser.parse_args(argv)
    if args.command == "plan":
        result = rr.make_plan(args.repo, args.start, args.end, args.token_env, args.max_requests,
                              keychain_service=args.keychain_service)
    elif args.command == "approve":
        result = rr.approve(args.repo, args.by)
    elif args.command == "collect":
        result = rr.collect(args.repo)
    elif args.command == "evaluate":
        full = rr.evaluate(args.repo)
        result = {"coverage": full["coverage"], "counts": full["counts"], "identity": full["identity"],
                  "linked_by_lookup": len(full["linked_by_lookup"]),
                  "exceptions": [{"change": c["id"], "url": c["url"], "identity": c["identity"],
                                  "rules": {k: v[1] for k, v in c["results"].items() if v[0] == "EXCEPTION"}}
                                 for c in full["changes"] if c["exception"]]}
    elif args.command == "sample":
        result = rr.sample(args.repo)
    elif args.command == "packet":
        result = {"packet": str(rr.packet(args.repo))}
    elif args.command == "review-rubric":
        result = rr.review_rubric(args.repo, args.by, args.provenance, args.verdict, args.note)
    elif args.command == "label":
        result = rr.label(args.repo, args.item, args.label, args.by, args.provenance, args.note)
    elif args.command == "score":
        result = rr.score(args.repo)
    else:
        result = rr.status(args.repo)
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    try:
        main()
    except (rr.PilotRefused, rr.CollectionStopped) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(2)
