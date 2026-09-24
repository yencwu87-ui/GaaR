"""WB-131 governed Watcher repository: ADD -> DIFF -> COMMIT -> PUSH.

ADD snapshots an exact source payload and records proposed document classification.
COMMIT is a human-attributed, Ed25519-signed approval of that immutable version and
its assessment/control relationship. PUSH writes an immutable assessment link;
only approved, in-scope law/rule/guidance is eligible for an Autopilot impact-review
trigger. No step modifies a GovernanceResult, binds organisational evidence, or
asserts that a proposed obligation is legally applicable without human review.

A signing key authenticates the local signing key, not the human at the keyboard;
enterprise human authentication/RBAC is a separate gate.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from governance.autopilot.monitor import ChangeMonitor, TriggerType, AutopilotTrigger
from governance.autopilot.scheduler import AutopilotScheduler
from governance.result_integration import signer_from_env
from .models import WatcherAuthority, WatcherConfig
from .policy import load_sources
from .store import ROOT, HashChainStore


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WatcherGitError(ValueError):
    pass


class ImmutableWatcherBlobs:
    """Local CAS: O_EXCL creation, no symlink follows, verify on every read.

    The filesystem remains a local trust boundary; an external WORM/backup system
    is needed for production-grade tamper resistance.
    """
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("WB_GAAR_WATCHER_BLOBS", ROOT / "watcher_blobs"))

    def _path(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            raise WatcherGitError("invalid SHA-256 reference")
        return self.root / digest[:2] / digest

    def put(self, payload: bytes) -> str:
        if not payload or len(payload) > 12 * 1024 * 1024:
            raise WatcherGitError("empty document or document exceeds 12 MiB local snapshot quota")
        digest = sha(payload)
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise WatcherGitError("symlink blob is forbidden")
        if path.exists():
            self.read(digest)
            return digest
        fd = None
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            self.read(digest)
        finally:
            if fd is not None:
                os.close(fd)
        self.read(digest)
        return digest

    def read(self, digest: str) -> bytes:
        path = self._path(digest)
        if path.is_symlink():
            raise WatcherGitError("CAS blob symlink is forbidden")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise WatcherGitError("CAS blob is not a regular file")
            payload = stream.read(12 * 1024 * 1024 + 1)
        if sha(payload) != digest:
            raise WatcherGitError("CAS blob hash mismatch; quarantined/invalid")
        return payload


CLASS_RULES = {
    # class: (normative status, allowed source authority, push treatment)
    "binding_law": ("binding", {"binding"}, "IMPACT_REVIEW"),
    "binding_rule": ("binding", {"binding"}, "IMPACT_REVIEW"),
    "regulatory_guidance": ("guidance", {"binding", "mandatory", "expectation"}, "IMPACT_REVIEW"),
    "consultation": ("consultation", {"binding", "mandatory", "expectation", "industry", "background"}, "HORIZON_SCAN"),
    "policy": ("informational", {"binding", "mandatory", "expectation", "industry", "background"}, "BACKGROUND_LINK"),
    "regulatory_information": ("informational", {"binding", "mandatory", "expectation", "industry", "background"}, "BACKGROUND_LINK"),
    "standard": ("guidance", {"binding", "mandatory", "expectation", "industry", "background"}, "BENCHMARK_LINK"),
    "research": ("informational", {"binding", "mandatory", "expectation", "industry", "background"}, "BACKGROUND_LINK"),
    "threat": ("informational", {"threat"}, "THREAT_EXPOSURE_REVIEW"),
}

LIFECYCLES = {"draft", "open_consultation", "closed_pending_final", "future_effective", "effective", "amended", "superseded", "withdrawn"}


def allowed_domains(cfg: WatcherConfig) -> set[str]:
    domains = {str(d).strip().lower() for d in cfg.filters.get("approved_domains", []) if str(d).strip()}
    # A verified connector host can be used when no explicit allowlist exists;
    # never infer authority from an arbitrary URL in an individual feed item.
    if not domains:
        host = urlparse(str(cfg.connector.get("url") or "")).hostname
        if host:
            domains.add(host.lower())
    return domains


def url_on_allowlist(value: str, domains: set[str]) -> bool:
    u = urlparse(value)
    return (u.scheme == "https" and bool(u.hostname) and not u.username and not u.password
            and u.port in (None, 443) and u.hostname.lower() in domains)


def validate_date(value: str, label: str) -> str:
    if not value:
        raise WatcherGitError(f"{label} is required")
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise WatcherGitError(f"{label} must be ISO date/time") from exc
    return str(value)


class WatcherSourceSnapshots:
    """Raw fetch snapshots. These are discovery receipts, not approved publications."""
    def __init__(self, *, blobs=None, path=None):
        self.blobs = blobs or ImmutableWatcherBlobs()
        self.store = HashChainStore(path or os.environ.get("WB_GAAR_WATCHER_SNAPSHOTS", ROOT / "watcher_snapshots.jsonl"), "gaar.watcher-source-snapshot.v1")

    def capture(self, source_id: str, doc, *, run_id: str, connector_type: str) -> dict:
        raw = doc.content.encode("utf-8")
        digest = self.blobs.put(raw)
        payload = {"snapshot_id": "WS-" + uuid.uuid4().hex[:24], "source_id": source_id,
                   "document_id": doc.document_id, "title": doc.title, "source_url": doc.url,
                   "published_at": doc.published_at, "effective_at": doc.effective_at,
                   "blob_hash": digest, "bytes": len(raw), "run_id": run_id, "retrieved_at": now(),
                   "extraction_scope": "connector_extracted_text_or_feed_excerpt",
                   "connector_type": connector_type, "origin_assurance": "CONNECTOR_FETCH_NOT_INDEPENDENTLY_ATTESTED"}
        self.store.append("WatcherSourceSnapshot", payload)
        return payload

    def find(self, snapshot_id: str) -> dict:
        for row in reversed(self.store.read()):
            p = row["payload"]
            if p["snapshot_id"] == snapshot_id:
                return p
        raise WatcherGitError(f"unknown snapshot: {snapshot_id}")


class WatcherGitflow:
    def __init__(self, *, registry: tuple[WatcherConfig, ...] | None = None, blobs=None,
                 snapshots=None, path=None, monitor=None, scheduler=None, signer=None):
        self.registry = tuple(registry) if registry is not None else load_sources()
        self.blobs = blobs or ImmutableWatcherBlobs()
        self.snapshots = snapshots or WatcherSourceSnapshots(blobs=self.blobs)
        self.store = HashChainStore(path or os.environ.get("WB_GAAR_WATCHER_GIT_STORE", ROOT / "watcher_git_events.jsonl"), "gaar.watcher-git.v1")
        self.monitor = monitor or ChangeMonitor()
        self.scheduler = scheduler or AutopilotScheduler()
        self.signer = signer  # signer_from_env() is called only on explicit commit/push

    def _signer(self):
        return self.signer or signer_from_env()

    def _source(self, source_id: str) -> WatcherConfig:
        for item in self.registry:
            if item.source_id == source_id:
                return item
        raise WatcherGitError(f"source {source_id!r} is not enabled in approved watcher source registry")

    def _events(self, kind: str | None = None) -> list[dict]:
        payloads = [{**row["payload"], "_record_hash": row["record_hash"]} for row in self.store.read()]
        return [p for p in payloads if p.get("kind") == kind] if kind else payloads

    def _latest(self, kind: str, key: str, value: str) -> dict:
        for item in reversed(self._events(kind)):
            if item.get(key) == value:
                return item
        raise WatcherGitError(f"{kind} not found: {value}")

    def status(self) -> dict:
        events = self._events()
        rejected = {p["stage_id"] for p in events if p["kind"] == "REJECT"}
        committed = {p["stage_id"] for p in events if p["kind"] == "COMMIT"}
        return {"staged": [p for p in events if p["kind"] == "ADD" and p["stage_id"] not in rejected and p["stage_id"] not in committed],
                "committed": [p for p in events if p["kind"] == "COMMIT"],
                "pushed": [p for p in events if p["kind"] == "PUSH_DELIVERED"],
                "pending_delivery": [p for p in events if p["kind"] == "PUSH_PENDING" and not any(
                    q.get("commit_id") == p.get("commit_id") and q["kind"] == "PUSH_DELIVERED" for q in events)],
                "rejected": [p for p in events if p["kind"] == "REJECT"]}

    def add_from_snapshot(self, *, snapshot_id: str, issuer: str, doc_class: str, lifecycle: str,
                          landing_url: str, assessment_id: str, controls: tuple[str, ...],
                          framework: str, actor: str, rationale: str, origin_attestation: str = "") -> dict:
        snap = self.snapshots.find(snapshot_id)
        data = self.blobs.read(snap["blob_hash"])
        return self._add(data=data, source_id=snap["source_id"], document_id=snap["document_id"],
                         source_url=snap["source_url"], landing_url=landing_url, title=snap["title"],
                         issuer=issuer, published_at=snap["published_at"], effective_at=snap["effective_at"],
                         doc_class=doc_class, lifecycle=lifecycle, assessment_id=assessment_id,
                         controls=controls, framework=framework, actor=actor, rationale=rationale,
                         origin_attestation=origin_attestation, source_snapshot_id=snapshot_id,
                         origin_assurance=snap["origin_assurance"])

    def add_file(self, *, source_id: str, file: str | Path, document_id: str,
                 source_url: str, landing_url: str, title: str, issuer: str, published_at: str,
                 doc_class: str, lifecycle: str, assessment_id: str, controls: tuple[str, ...],
                 framework: str, actor: str, rationale: str, effective_at: str | None = None,
                 origin_attestation: str = "") -> dict:
        file = Path(file)
        if file.is_symlink():
            raise WatcherGitError("input must be a regular, non-symlink local file")
        fd = os.open(str(file), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise WatcherGitError("input must be a regular local file")
            payload = stream.read(12 * 1024 * 1024 + 1)
            stream.seek(0)
            if payload != stream.read(12 * 1024 * 1024 + 1):
                raise WatcherGitError("input file changed during snapshot (TOCTOU)")
        return self._add(data=payload, source_id=source_id, document_id=document_id,
                         source_url=source_url, landing_url=landing_url, title=title, issuer=issuer,
                         published_at=published_at, effective_at=effective_at, doc_class=doc_class,
                         lifecycle=lifecycle, assessment_id=assessment_id, controls=controls,
                         framework=framework, actor=actor, rationale=rationale,
                         origin_attestation=origin_attestation, source_snapshot_id=None,
                         origin_assurance="HUMAN_ASSERTED_OFFICIAL_LINK_NOT_HTTP_VERIFIED")

    def _add(self, *, data: bytes, source_id: str, document_id: str, source_url: str,
             landing_url: str, title: str, issuer: str, published_at: str, effective_at: str | None,
             doc_class: str, lifecycle: str, assessment_id: str, controls: tuple[str, ...], framework: str,
             actor: str, rationale: str, origin_attestation: str, source_snapshot_id: str | None,
             origin_assurance: str) -> dict:
        cfg = self._source(source_id)
        if doc_class not in CLASS_RULES:
            raise WatcherGitError(f"unknown document class {doc_class!r}")
        normative, authorities, treatment = CLASS_RULES[doc_class]
        if cfg.authority.value not in authorities:
            raise WatcherGitError("document class exceeds source registry maximum authority")
        if lifecycle not in LIFECYCLES:
            raise WatcherGitError("unknown lifecycle status")
        if treatment == "IMPACT_REVIEW" and lifecycle in {"draft", "open_consultation", "closed_pending_final", "withdrawn", "superseded"}:
            raise WatcherGitError("draft/superseded/withdrawn item cannot be staged as a current rule or guidance")
        if doc_class == "consultation" and lifecycle not in {"draft", "open_consultation", "closed_pending_final", "superseded", "withdrawn"}:
            raise WatcherGitError("consultations must have an appropriate consultation lifecycle")
        domains = allowed_domains(cfg)
        if not domains or not url_on_allowlist(source_url, domains) or not url_on_allowlist(landing_url, domains):
            raise WatcherGitError("both source and landing URLs must be HTTPS URLs on an approved source domain")
        for label, value in (("title", title), ("issuer", issuer), ("document_id", document_id),
                             ("actor", actor), ("rationale", rationale), ("assessment_id", assessment_id),
                             ("framework", framework), ("origin_attestation", origin_attestation)):
            if not str(value or "").strip():
                raise WatcherGitError(f"{label} is required; unknown authority/origin cannot be admitted")
        if title.strip().lower() == "untitled":
            raise WatcherGitError("Untitled documents are quarantined")
        validate_date(published_at, "publication date")
        if effective_at:
            validate_date(effective_at, "effective date")
        controls = tuple(sorted({str(x).strip() for x in controls if str(x).strip()}))
        if not controls and treatment == "IMPACT_REVIEW":
            raise WatcherGitError("an impact-review stage requires explicit affected control IDs")
        digest = self.blobs.put(data)
        history = [p for p in self._events("COMMIT") if p["source_id"] == source_id and p["document_id"] == document_id]
        if any(p["blob_hash"] == digest and p["assessment_id"] == assessment_id and
               p["controls"] == list(controls) for p in history):
            raise WatcherGitError("this exact document version is already committed for these controls and assessment")
        previous = history[-1]["blob_hash"] if history else None
        row = {"kind": "ADD", "stage_id": "WST-" + uuid.uuid4().hex[:24],
               "source_id": source_id, "source_authority_ceiling": cfg.authority.value,
               "document_id": document_id, "title": title, "issuer": issuer,
               "jurisdiction": cfg.jurisdiction, "document_class": doc_class, "authority_level": cfg.authority.value,
               "normative_status": normative, "lifecycle_status": lifecycle, "treatment": treatment,
               "source_url": source_url, "landing_url": landing_url, "published_at": published_at,
               "effective_at": effective_at, "retrieved_at": now(), "source_snapshot_id": source_snapshot_id,
               "origin_assurance": origin_assurance, "origin_attestation": origin_attestation,
               "blob_hash": digest, "previous_version_hash": previous, "bytes": len(data),
               "assessment_id": assessment_id, "controls": list(controls), "framework": framework,
               "actor": actor, "rationale": rationale, "added_at": now(), "binding_status": "PROPOSED_ONLY"}
        self.store.append("WatcherGitAdd", row)
        return row

    def diff(self, stage_id: str) -> dict:
        stage = self._latest("ADD", "stage_id", stage_id)
        new_data = self.blobs.read(stage["blob_hash"])
        prior_hash = stage.get("previous_version_hash")
        old_data = self.blobs.read(prior_hash) if prior_hash else b""
        if new_data.startswith(b"%PDF") or old_data.startswith(b"%PDF") or b"\x00" in new_data + old_data:
            lines = ["Binary/PDF snapshot: textual diff unavailable. Compare official versions manually."]
        else:
            old = old_data.decode("utf-8", "replace").splitlines()
            new = new_data.decode("utf-8", "replace").splitlines()
            lines = list(difflib.unified_diff(old, new, fromfile=prior_hash or "new", tofile=stage["blob_hash"], lineterm=""))[:200]
        return {"stage_id": stage_id, "previous_version_hash": prior_hash,
                "current_version_hash": stage["blob_hash"], "same_content": prior_hash == stage["blob_hash"],
                "diff_lines": lines, "diff_truncated": len(lines) == 200}

    def reject(self, stage_id: str, *, reviewer: str, reason: str) -> dict:
        stage = self._latest("ADD", "stage_id", stage_id)
        if any(p["stage_id"] == stage_id for p in self._events("COMMIT")):
            raise WatcherGitError("committed version cannot be rejected retroactively")
        if any(p["stage_id"] == stage_id for p in self._events("REJECT")):
            raise WatcherGitError("stage already rejected")
        if not reviewer.strip() or not reason.strip():
            raise WatcherGitError("reviewer attribution and rejection reason required")
        row = {"kind": "REJECT", "stage_id": stage_id, "blob_hash": stage["blob_hash"],
               "source_id": stage["source_id"], "reviewer": reviewer.strip(),
               "reason": reason.strip(), "rejected_at": now(), "governance_trigger_emitted": False}
        self.store.append("WatcherGitRejected", row)
        return row

    def current_use(self) -> list[dict]:
        commits = self._events("COMMIT")
        latest = {(p["source_id"], p["document_id"]): p["blob_hash"] for p in commits}
        staged = {}
        for p in self.status()["staged"]:
            staged.setdefault((p["source_id"], p["document_id"]), set()).add(p["blob_hash"])
        output = []
        for row in self._events("PUSH_DELIVERED"):
            key = row["source_id"], row["document_id"]
            current_hash = latest.get(key)
            version_status = ("OLDER_VERSION_IMPACT_REVIEW_REQUIRED"
                              if current_hash and current_hash != row["blob_hash"] else "LATEST_COMMITTED_VERSION")
            if version_status == "LATEST_COMMITTED_VERSION" and any(v != row["blob_hash"] for v in staged.get(key, ())):
                version_status = "NEW_VERSION_STAGED_REVIEW_REQUIRED"
            output.append({**row, "version_status": version_status})
        return output

    def _verify_commit(self, commit: dict) -> None:
        payload = {k: v for k, v in commit.items() if k not in {"kind", "signature", "key_id", "public_key_b64", "_record_hash"}}
        signer = self._signer()
        if signer.key_id != commit["key_id"] or signer.public_key_b64 != commit["public_key_b64"]:
            raise WatcherGitError("commit signing key not trusted by this local workspace")
        if not signer.verify(canon(payload), commit["signature"]):
            raise WatcherGitError("invalid Ed25519 commit signature")
        self.blobs.read(commit["blob_hash"])

    def commit(self, stage_id: str, *, reviewer: str, decision_note: str) -> dict:
        stage = self._latest("ADD", "stage_id", stage_id)
        if any(p["stage_id"] == stage_id for p in self._events("COMMIT")):
            raise WatcherGitError("stage already committed; create a new add for a new version")
        if any(p["stage_id"] == stage_id for p in self._events("REJECT")):
            raise WatcherGitError("rejected stage cannot be committed")
        if not reviewer.strip() or not decision_note.strip():
            raise WatcherGitError("human reviewer attribution and review rationale required")
        self._source(stage["source_id"])
        self.blobs.read(stage["blob_hash"])
        signer = self._signer()
        unsigned = {k: v for k, v in stage.items() if k not in {"kind", "_record_hash"}}
        unsigned.update({"commit_id": "WCM-" + uuid.uuid4().hex[:24], "stage_record_hash": stage["_record_hash"],
                         "reviewer": reviewer.strip(), "decision_note": decision_note.strip(),
                         "committed_at": now(), "identity_assurance": "LOCAL_ATTRIBUTION_ONLY_NOT_AUTHENTICATED"})
        result = {"kind": "COMMIT", **unsigned, "key_id": signer.key_id,
                  "public_key_b64": signer.public_key_b64, "signature": signer.sign(canon(unsigned))}
        self.store.append("WatcherGitCommit", result)
        return result

    def push(self, commit_id: str) -> dict:
        commit = self._latest("COMMIT", "commit_id", commit_id)
        self._verify_commit(commit)
        cfg = self._source(commit["source_id"])
        normative, authorities, treatment = CLASS_RULES[commit["document_class"]]
        if cfg.authority.value not in authorities or cfg.authority.value != commit["source_authority_ceiling"]:
            raise WatcherGitError("source authority changed; re-stage and reapprove")
        domains = allowed_domains(cfg)
        if not domains or not url_on_allowlist(commit["source_url"], domains) or not url_on_allowlist(commit["landing_url"], domains):
            raise WatcherGitError("approved source domain changed since commit; re-stage and review")
        same_document = [p for p in self._events("COMMIT") if p["source_id"] == commit["source_id"] and p["document_id"] == commit["document_id"]]
        if same_document[-1]["commit_id"] != commit_id:
            raise WatcherGitError("a newer document version is committed; push latest or review historical handling")
        if commit["lifecycle_status"] in {"withdrawn", "superseded"} and treatment == "IMPACT_REVIEW":
            raise WatcherGitError("document no longer current")
        if any(p["commit_id"] == commit_id for p in self._events("PUSH_DELIVERED")):
            return self._latest("PUSH_DELIVERED", "commit_id", commit_id)
        try:
            pending = self._latest("PUSH_PENDING", "commit_id", commit_id)
        except WatcherGitError:
            pending = {"kind": "PUSH_PENDING", "push_id": "WPS-" + uuid.uuid4().hex[:24],
                       "commit_id": commit_id, "stage_id": commit["stage_id"],
                       "assessment_id": commit["assessment_id"], "controls": commit["controls"],
                       "framework": commit["framework"], "source_id": commit["source_id"],
                       "document_id": commit["document_id"], "document_class": commit["document_class"],
                       "normative_status": normative, "lifecycle_status": commit["lifecycle_status"],
                       "blob_hash": commit["blob_hash"], "relationship_status": treatment,
                       "requested_at": now(), "binding_status": "STAGED_FOR_ASSESSMENT_NOT_AUTHORITY_BOUND"}
            self.store.append("WatcherGitPushPending", pending)
        triggers = []
        if treatment == "IMPACT_REVIEW":
            for cid in commit["controls"]:
                trigger = self.monitor.emit(trigger_type=TriggerType.GOVERNANCE_CHANGE,
                    control_id=cid, framework=commit["framework"],
                    reason=f"Human-reviewed Watcher impact review: {commit['commit_id']}", material=True,
                    source_id=commit["source_id"], change_id=commit["commit_id"],
                    payload={"commit_id": commit["commit_id"], "document_hash": commit["blob_hash"],
                             "assessment_id": commit["assessment_id"], "control_id": cid,
                             "normative_status": normative, "document_class": commit["document_class"]},
                    metadata={"watcher_push_id": pending["push_id"],
                              "normative_status": normative, "document_class": commit["document_class"],
                              "human_approval_attribution": commit["reviewer"],
                              "identity_assurance": commit["identity_assurance"],
                              "intended_action": "IMPACT_REVIEW_ONLY"})
                # Crash recovery: ChangeMonitor has a stable dedup payload; if a
                # prior attempt wrote its trigger but not its job/push receipt,
                # find that same trigger and enqueue idempotently on retry.
                if trigger is None:
                    for event in self.monitor.store.read():
                        t = event["trigger"]
                        if t.get("change_id") == commit["commit_id"] and t.get("control_id") == cid:
                            from governance.autopilot.monitor import TriggerType as _TT
                            trigger = AutopilotTrigger(**{**t, "trigger_type": _TT(t["trigger_type"])})
                            break
                if trigger is None:
                    raise WatcherGitError("impact-review trigger was neither emitted nor recovered")
                self.scheduler.enqueue(trigger)
                triggers.append(trigger.trigger_id)
        delivered = {**pending, "kind": "PUSH_DELIVERED", "delivered_at": now(),
                     "trigger_ids": triggers, "queued_jobs": len(triggers), "impact_review_only": True,
                     "message": ("Governed impact-review trigger(s) emitted; not a binding legal determination"
                                 if treatment == "IMPACT_REVIEW" else
                                 "Version linked for research/planning/exposure review; no regulatory-change trigger")}
        self.store.append("WatcherGitPushDelivered", delivered)
        return delivered
