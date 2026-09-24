"""Deterministic, keyless replay verification for a sealed GovernanceResult."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from governance.result_contract import (
    GovernanceResult, merkle_root, result_id_for, seal_message, sha256_json, verify_signature,
)


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verify(result: GovernanceResult, *, control_id: str, framework: str) -> dict[str, Any]:
    """Recompute all deterministic material without private-key access."""
    checks = {
        "result_identity": result_id_for(result.identity_payload()) == result.result_id,
        "content_hash": sha256_json(result.immutable_payload()) == result.content_hash,
        "merkle_root": merkle_root(result.immutable_payload()) == result.sealed_record.merkle_root,
        "ed25519_signature": verify_signature(
            result.sealed_record.public_key_b64,
            result.sealed_record.signature,
            seal_message(result.sealed_record.key_id, result.content_hash, result.sealed_record.merkle_root),
        ),
    }
    identity = {
        "result_id": result.result_id,
        "content_hash": result.content_hash,
        "control_id": control_id,
        "framework": framework,
        "checks": checks,
    }
    return {
        "schema": "gaar.replay-proof.v1",
        "proof_id": "REPLAY-" + hashlib.sha256(_canon(identity).encode("utf-8")).hexdigest()[:32],
        **identity,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def append_proof(proof: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(_canon(proof) + "\n")

