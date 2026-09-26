"""A period pack sealed with its own passport (block 1, B1-6), verifiable offline with the tenant's public key.

A period pack is not a GovernanceResult, so it is not forced into that schema. It is sealed with the same primitives:
a SHA-256 content hash over the canonical pack, a Merkle root over its sections (each section a leaf, so a reader can
tell which part changed), and an Ed25519 signature over GaaR's seal message. The passport carries the public key; a
verifier who holds the tenant's key from its key register passes it as `expected_public_key`, so a pack re-signed with
another key does not verify.

The tenant's signing key is created on first use in the RaaS home (0600), recorded in the key register by its public
key and id, and never written into a pack.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone

from governance.result_contract import CanonicalSigner, merkle_root, seal_message, sha256_json, verify_signature

from . import home, store

SCHEMA = "gaar.raas.pack-passport.v1"


def _canon(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def signer(path=None) -> CanonicalSigner:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    key_file = home(path) / "keys" / "pack-signing.key"
    if not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(base64.b64encode(raw).decode("ascii"))
        created = True
    else:
        created = False
    private_b64 = key_file.read_text().strip()
    probe = CanonicalSigner.from_base64("probe", private_b64)
    key_id = "raas-" + hashlib.sha256(probe.public_key_b64.encode()).hexdigest()[:12]
    key = CanonicalSigner.from_base64(key_id, private_b64)
    if created:
        store("keys", path).append("RaaSSigningKeyCreated", {"key_id": key_id, "public_key_b64": key.public_key_b64,
                                                            "at": datetime.now(timezone.utc).isoformat()})
    return key


def key_register(path=None) -> list[dict]:
    return [r["payload"] for r in store("keys", path).read()]


def seal(pack: dict, path=None) -> dict:
    key = signer(path)
    content_hash, root = sha256_json(pack), merkle_root(pack)
    passport = {"passport_schema": SCHEMA, "pack_id": pack["pack_id"], "order_id": pack["order_id"],
                "period": pack["period"], "headline": pack["status"]["headline"], "content_hash": content_hash,
                "merkle_root": root, "sections": sorted(pack), "algorithm": "Ed25519", "key_id": key.key_id,
                "public_key_b64": key.public_key_b64,
                "signature": key.sign(seal_message(key.key_id, content_hash, root)),
                "sealed_at": datetime.now(timezone.utc).isoformat()}
    passport["passport_digest"] = hashlib.sha256(_canon(passport).encode()).hexdigest()
    return passport


def verify(pack: dict, passport: dict, expected_public_key: str | None = None) -> dict:
    """Offline: the pack and its passport, and optionally the tenant's public key from its key register."""
    supplied = dict(passport)
    digest = supplied.pop("passport_digest", None)
    checks = {
        "passport_digest_valid": digest == hashlib.sha256(_canon(supplied).encode()).hexdigest(),
        "content_matches": sha256_json(pack) == passport.get("content_hash"),
        "merkle_root_matches": merkle_root(pack) == passport.get("merkle_root"),
        "signature_valid": verify_signature(passport.get("public_key_b64", ""), passport.get("signature", ""),
                                            seal_message(passport.get("key_id", ""), passport.get("content_hash", ""),
                                                         passport.get("merkle_root", ""))),
        "key_is_the_tenants": expected_public_key is None or passport.get("public_key_b64") == expected_public_key,
    }
    changed = [s for s in sorted(set(pack) | set(passport.get("sections") or []))
               if s not in pack or s not in (passport.get("sections") or [])]
    return {"valid": all(checks.values()), **checks, "sections_added_or_removed": changed}
