#!/usr/bin/env python3
"""Operator/API adapter to the shared investigation service. No GUI required.

Signing keys come from an environment variable named by --signing-key-env; never
from evidence or an untrusted model response. The config pins public identities.
"""
import argparse
import os
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.investigation.bridge import configured_engine
from governance.result_contract import CanonicalSigner


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("append", "execute", "explain", "plan", "challenge", "block", "gate", "record"))
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--stage")
    p.add_argument("--payload", type=Path)
    p.add_argument("--key-id")
    p.add_argument("--signing-key-env")
    a = p.parse_args()
    os.environ["WB_INVESTIGATION_CONFIG"] = str(a.config.resolve())
    engine = configured_engine()
    if a.action == "gate":
        result = engine.gate(a.id)
    elif a.action == "record":
        result = engine.snapshot(a.id)[0]
    else:
        if not a.key_id or not a.signing_key_env:
            p.error("a trusted --key-id and --signing-key-env are required for signed writes")
        signer = CanonicalSigner.from_base64(a.key_id, os.environ[a.signing_key_env])
        if a.action == "append":
            if not a.stage or not a.payload:
                p.error("append requires --stage and --payload")
            result = engine.append(a.id, a.stage, json.loads(a.payload.read_text()), signer)
        elif a.action == "execute":
            result = engine.execute_plan(a.id, signer)
        else:
            from governance.investigation import agents
            fn = {"explain": agents.explain, "plan": agents.plan, "challenge": agents.challenge,
                  "block": agents.conclude_blocked_by_policy}[a.action]
            result = fn(engine, a.id, signer)
    print(json.dumps(result, indent=2))
    if a.action == "gate" and not result["assessment_finalizable"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
