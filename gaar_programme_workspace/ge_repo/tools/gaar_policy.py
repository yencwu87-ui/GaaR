#!/usr/bin/env python3
"""Approve the governing quality policy — a signed, recorded act on one exact version.

    python tools/gaar_policy.py show
    python tools/gaar_policy.py approve --key ~/.gaar-keys/governance.key --name "Your Name" --confirm <first 12 of the hash>

`--confirm` must repeat the first 12 characters of the policy hash that `show` prints, so an approval is
always given on a text the approver has identified, not on whatever the file happens to contain.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from governance.production import policy_approval as pa  # noqa: E402
from governance.investigation.store import canonical  # noqa: E402


def show(args):
    identity = pa.policy_identity(pa.POLICY)
    approvals = sorted(pa.APPROVALS.glob("*.approval.json")) if pa.APPROVALS.is_dir() else []
    covering = []
    for path in approvals:
        try:
            covering.append((path.name, pa.verify(pa.load(path))["approver"]))
        except Exception:
            continue
    return {**identity, "confirm_with": identity["policy_sha256"][:12],
            "approved": bool(covering),
            "approvals_covering_this_text": [{"file": f, "approver": a} for f, a in covering]}


def approve(args):
    import gaar_pilot
    identity = pa.policy_identity(pa.POLICY)
    if args.confirm != identity["policy_sha256"][:12]:
        raise ValueError(f"--confirm must repeat the first 12 characters of the policy hash "
                         f"({identity['policy_sha256'][:12]}); run 'show' and read the text you are approving")
    _, signer = gaar_pilot.load_human(args.key, args.name, "governance", ROOT / ".no-workspace")
    payload = {**identity, "statement": pa.STATEMENT, "approver": args.name.strip(),
               "approver_key_id": signer.key_id, "approver_public_key": signer.public_key_b64,
               "approved_at": __import__("datetime").datetime.now().astimezone().isoformat()}
    document = {"payload": payload, "signature": signer.sign(canonical(payload).encode())}
    pa.APPROVALS.mkdir(parents=True, exist_ok=True)
    target = pa.APPROVALS / (f"policy-{identity['policy_version']}-{identity['policy_sha256'][:12]}"
                             f"-{signer.key_id[-8:]}.approval.json")
    if target.exists():
        raise ValueError(f"{target.name} already exists; this approver has already approved this text")
    target.write_text(json.dumps(document, indent=2) + "\n")
    pa.verify(document)
    return {"status": "POLICY_APPROVED", "approval": str(target), "policy_version": identity["policy_version"],
            "policy_sha256": identity["policy_sha256"], "approver": payload["approver"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show").set_defaults(func=show)
    a = sub.add_parser("approve")
    a.add_argument("--key", required=True, help="the governance owner's private key file")
    a.add_argument("--name", required=True)
    a.add_argument("--confirm", required=True, help="the first 12 characters of the policy hash, from 'show'")
    a.set_defaults(func=approve)
    args = parser.parse_args()
    print(json.dumps(args.func(args), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
