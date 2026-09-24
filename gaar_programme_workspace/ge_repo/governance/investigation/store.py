"""Append-only SQLite journal; Ed25519 stage signatures pinned to external policy.

No self-declared signer is trusted. SQLite serializes concurrent appends. Database
triggers reject UPDATE/DELETE; signatures detect tampering. An externally retained
head is required to detect rollback/truncation by an administrator with file access.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from governance.result_contract import verify_signature
from .contracts import MODELS, ROLES, STAGES


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class InvestigationStore:
    def __init__(self, path, trust):
        self.path = Path(path)
        # Copy: changes to the caller's dictionary cannot change this store's policy.
        self.trust = json.loads(canonical(trust))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS stages (
                    investigation_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    envelope TEXT NOT NULL, PRIMARY KEY(investigation_id, sequence));
                CREATE TRIGGER IF NOT EXISTS stages_no_update BEFORE UPDATE ON stages
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS stages_no_delete BEFORE DELETE ON stages
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
            ''')

    def _connection(self):
        return sqlite3.connect(self.path, timeout=10)

    def _verify(self, rows, expected_head=None):
        head = "0" * 64
        actors = {}
        keys = {}
        for i, row in enumerate(rows):
            if i >= len(STAGES) or row["sequence"] != i or row["stage"] != STAGES[i] or row["previous"] != head:
                raise ValueError("broken investigation stage chain")
            if row["policy_sha256"] != digest(self.trust):
                raise ValueError("investigation policy changed; explicit migration required")
            policy = self.trust.get(row["key_id"], {})
            if policy.get("actor") != row["actor"] or ROLES[row["stage"]] not in policy.get("roles", []):
                raise ValueError("unauthorized stage signer")
            unsigned = {k: v for k, v in row.items() if k not in ("signature", "record_hash")}
            if not verify_signature(policy.get("public_key", ""), row["signature"], canonical(unsigned).encode()):
                raise ValueError("invalid stage signature")
            if digest({**unsigned, "signature": row["signature"]}) != row["record_hash"]:
                raise ValueError("stage hash mismatch")
            MODELS[row["stage"]].model_validate(row["payload"])
            if row["stage"] == "understand":
                if row["payload"]["owner"] != row["actor"] or row["payload"]["investigation_id"] != row["investigation_id"]:
                    raise ValueError("context owner/identity does not match signed record")
            if row["stage"] == "challenge":
                if row["payload"]["input_head"] != head:
                    raise ValueError("challenge did not review current investigation head")
                if row["actor"] in {actors.get("examine"), actors.get("explain")} or policy.get("public_key") in {keys.get("examine"), keys.get("explain")}:
                    raise ValueError("challenger must have a separate principal and signing key")
            actors[row["stage"]] = row["actor"]
            keys[row["stage"]] = policy.get("public_key")
            head = row["record_hash"]
        if expected_head is not None and head != expected_head:
            raise ValueError("investigation head differs from externally bound head")
        return rows

    def read(self, investigation_id, expected_head=None):
        with self._connection() as con:
            rows = [json.loads(x[0]) for x in con.execute(
                "SELECT envelope FROM stages WHERE investigation_id=? ORDER BY sequence", (investigation_id,))]
        if any(r["investigation_id"] != investigation_id for r in rows):
            raise ValueError("journal investigation identity mismatch")
        return self._verify(rows, expected_head)

    def append(self, investigation_id, stage, payload, signer):
        value = MODELS[stage].model_validate(payload).model_dump(mode="json")
        with self._connection() as con:
            con.execute("BEGIN IMMEDIATE")
            rows = [json.loads(x[0]) for x in con.execute(
                "SELECT envelope FROM stages WHERE investigation_id=? ORDER BY sequence", (investigation_id,))]
            self._verify(rows)
            i = len(rows)
            if i >= len(STAGES) or stage != STAGES[i]:
                raise ValueError("stage order violation; start a new investigation for revision")
            policy = self.trust.get(signer.key_id, {})
            if signer.public_key_b64 != policy.get("public_key"):
                raise ValueError("signer is not pinned by policy")
            envelope = {"schema": "investigation-stage.1", "investigation_id": investigation_id,
                        "sequence": i, "stage": stage, "payload": value,
                        "previous": rows[-1]["record_hash"] if rows else "0" * 64,
                        "actor": policy.get("actor"), "key_id": signer.key_id,
                        "policy_sha256": digest(self.trust),
                        "at": datetime.now(timezone.utc).isoformat()}
            envelope["signature"] = signer.sign(canonical(envelope).encode())
            envelope["record_hash"] = digest(envelope)
            self._verify(rows + [envelope])
            con.execute("INSERT INTO stages VALUES (?, ?, ?)", (investigation_id, i, canonical(envelope)))
        return envelope
