"""Policy approval — the quality policy's own §2 gate, "a signed approval event by a named governance owner".

An approval signs the exact bytes of the policy file (by hash), its version, and a fixed statement. It is
verified against the public key it carries, and against the policy file as it is now: if the text has
changed since approval, the approval no longer covers it. A standing authorisation pins the approved policy
by hash, so changing the policy after a series is authorised stops that series (runbook U1).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from governance.investigation.store import canonical, digest
from governance.result_contract import verify_signature

PACKAGE = Path(__file__).resolve().parents[2]
POLICY = PACKAGE / "docs/quality/quality_policy.md"
APPROVALS = PACKAGE / "docs/quality/approvals"
STATEMENT = ("I approve this exact policy text as the governing policy for standing authorisations signed after "
             "this approval. I have reviewed what it claims, what it does not claim, and how each gate is held.")


def policy_identity(path: Path | None = None) -> dict:
    path = Path(path or POLICY)
    raw = path.read_bytes()
    block = re.search(r"```policy\n(.*?)```", raw.decode("utf-8"), re.S)
    version = json.loads(block.group(1))["policy_version"] if block else None
    shown = str(path.relative_to(PACKAGE)) if path.is_relative_to(PACKAGE) else str(path)
    return {"policy_path": shown, "policy_version": version,
            "policy_sha256": hashlib.sha256(raw).hexdigest()}


def verify(document: dict, path: Path | None = None) -> dict:
    """The approval is genuine and covers the policy text as it is now."""
    payload = document["payload"]
    if not verify_signature(payload["approver_public_key"], document["signature"], canonical(payload).encode()):
        raise ValueError("the policy approval signature is invalid")
    if payload.get("statement") != STATEMENT:
        raise ValueError("the policy approval does not carry the required statement")
    current = policy_identity(path)
    if payload["policy_sha256"] != current["policy_sha256"]:
        raise ValueError("the policy text has changed since it was approved; the approval does not cover it "
                         "(runbook U1)")
    return payload


def load(path) -> dict:
    return json.loads(Path(path).expanduser().read_text())


def approval_sha256(document: dict) -> str:
    return digest(document)
