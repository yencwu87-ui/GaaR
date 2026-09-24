#!/usr/bin/env python3
"""Verify and record deterministic replay proof for one sealed GovernanceResult."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.replay_verifier import append_proof, verify
from governance.result_store import ResultStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-id", required=True)
    parser.add_argument("--control-id", required=True)
    parser.add_argument("--framework", required=True)
    parser.add_argument("--result-store", default=os.environ.get("WB_GAAR_RESULT_STORE") or str(ROOT / "governance" / "result_store.jsonl"))
    parser.add_argument("--proof-store", default=os.environ.get("WB_GAAR_REPLAY_PROOF_STORE") or str(ROOT / "governance" / "replay_proofs.jsonl"))
    args = parser.parse_args()

    result = ResultStore(args.result_store).get(args.result_id)
    if result is None:
        parser.error(f"result not found: {args.result_id}")
    proof = verify(result, control_id=args.control_id, framework=args.framework)
    if proof["status"] == "PASS":
        append_proof(proof, args.proof_store)
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
