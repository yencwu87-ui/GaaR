#!/usr/bin/env python3
"""WB-131 Watcher Git-style staging, review, commit and impact-review push.

Use ``--help`` on each subcommand. A commit is local human attribution signed
with the configured workspace key; it is not enterprise identity authentication.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.watcher.gitflow import CLASS_RULES, LIFECYCLES, WatcherGitflow, WatcherGitError
from governance.watcher.store import EmissionStore
from governance.watcher.policy import load_sources


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="source registry YAML (enabled sources only)")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="List staged, committed, pushed and pending items")
    add = sub.add_parser("add", help="Stage a discovered snapshot or a local official-file snapshot")
    src = add.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshot-id", help="source_snapshot_id from Watcher emission")
    src.add_argument("--change-id", help="change_id from Watcher emission; uses its recorded snapshot")
    src.add_argument("--file", help="manual local file; no HTTP authenticity attested by GaaR")
    for field in ("source-id", "document-id", "source-url", "title", "published-at"):
        add.add_argument("--" + field, required=False, help="required with --file")
    for field in ("issuer", "landing-url", "assessment", "framework", "actor", "reason", "attestation"):
        add.add_argument("--" + field, required=True)
    add.add_argument("--control", action="append", default=[], help="affected control; repeat")
    add.add_argument("--document-class", required=True, choices=sorted(CLASS_RULES))
    add.add_argument("--lifecycle", required=True, choices=sorted(LIFECYCLES))
    add.add_argument("--effective-at")
    diff = sub.add_parser("diff", help="Read-only diff against the last committed version")
    diff.add_argument("stage_id")
    commit = sub.add_parser("commit", help="Human review + signed immutable version approval")
    commit.add_argument("stage_id")
    commit.add_argument("--reviewer", required=True)
    commit.add_argument("--note", required=True)
    reject = sub.add_parser("reject", help="Record not-applicable / rejected stage without a governance trigger")
    reject.add_argument("stage_id")
    reject.add_argument("--reviewer", required=True)
    reject.add_argument("--reason", required=True)
    push = sub.add_parser("push", help="Link approved version to assessment; route eligible impact-review request")
    push.add_argument("commit_id")
    verify = sub.add_parser("verify", help="Read-only validation of signed commit and source blob")
    verify.add_argument("commit_id")
    return ap


def main() -> int:
    args = parser().parse_args()
    try:
        repo = WatcherGitflow(registry=load_sources(args.config))
        if args.command == "status":
            output = repo.status()
        elif args.command == "diff":
            output = repo.diff(args.stage_id)
        elif args.command == "commit":
            output = repo.commit(args.stage_id, reviewer=args.reviewer, decision_note=args.note)
        elif args.command == "reject":
            output = repo.reject(args.stage_id, reviewer=args.reviewer, reason=args.reason)
        elif args.command == "push":
            output = repo.push(args.commit_id)
        elif args.command == "verify":
            commit = repo._latest("COMMIT", "commit_id", args.commit_id)
            repo._verify_commit(commit)
            output = {"commit_id": args.commit_id, "signature": "VALID", "CAS_hash": "VALID", "authority_link": "LOCAL_SIGNED_ATTRIBUTION"}
        else:
            common = {"issuer": args.issuer, "doc_class": args.document_class,
                      "lifecycle": args.lifecycle, "landing_url": args.landing_url,
                      "assessment_id": args.assessment, "controls": tuple(args.control),
                      "framework": args.framework, "actor": args.actor, "rationale": args.reason,
                      "origin_attestation": args.attestation}
            if args.file:
                fields = ("source_id", "document_id", "source_url", "title", "published_at")
                missing = [name.replace("_", "-") for name in fields if not getattr(args, name)]
                if missing:
                    raise WatcherGitError("--file also requires: " + ", ".join("--" + n for n in missing))
                output = repo.add_file(file=args.file,
                     **{name: getattr(args, name) for name in fields},
                     effective_at=args.effective_at, **common)
            else:
                sid = args.snapshot_id
                if args.change_id:
                    rows = [r["payload"] for r in EmissionStore().read() if (r.get("payload") or {}).get("change_id") == args.change_id]
                    if not rows or not rows[-1].get("source_snapshot_id"):
                        raise WatcherGitError("no captured source snapshot for change id; do not reconstruct an unverified source")
                    sid = rows[-1]["source_snapshot_id"]
                output = repo.add_from_snapshot(snapshot_id=sid, **common)
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True, default=str))
        return 0
    except (WatcherGitError, ValueError, RuntimeError, KeyError, OSError) as err:
        print(json.dumps({"status":"BLOCKED", "reason": str(err)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
