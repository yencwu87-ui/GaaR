"""GaaR Workstream A — immutable GovernanceResult + append-only state events.

This module is deliberately additive. It does not alter the existing assessor, challenger,
reviewer, or retrieval paths. A GovernanceResult is an immutable artifact; validity is a
projection of append-only StateTransitionEvent records rather than a mutable field on the result.

Cryptographic sealing uses Ed25519 via ``cryptography``. The private key never belongs in a result
or repository; callers provide a signer backed by their key-management boundary.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "gaar.result.v1"
EVENT_SCHEMA_VERSION = "gaar.result-state.v1"
STATE_EVENT_LOG = Path(__file__).resolve().parent / "result_state_events.jsonl"


class Decision(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class ValidityState(str, Enum):
    FINALIZED = "FINALIZED"
    CURRENT = "CURRENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REASSESSING = "REASSESSING"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ActorType(str, Enum):
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    SERVICE = "SERVICE"


class TransitionTrigger(str, Enum):
    GOVERNANCE_APPROVAL = "GOVERNANCE_APPROVAL"
    GOVERNANCE_CHANGE = "GOVERNANCE_CHANGE"
    REQUIREMENT_EXPIRY = "REQUIREMENT_EXPIRY"
    REASSESSMENT = "REASSESSMENT"
    ADMINISTRATIVE = "ADMINISTRATIVE"


@dataclass(frozen=True)
class CanonicalSigner:
    """Ed25519 signer boundary.

    The private key may be loaded from an HSM/KMS/Vault by the caller. This object only holds the
    signing interface needed by the result compiler.
    """

    key_id: str
    private_key: Any
    public_key: Any

    @classmethod
    def from_base64(cls, key_id: str, private_key_b64: str) -> "CanonicalSigner":
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError as exc:  # pragma: no cover - dependency message path
            raise RuntimeError("Ed25519 sealing requires the 'cryptography' package") from exc

        raw = base64.b64decode(private_key_b64)
        private = Ed25519PrivateKey.from_private_bytes(raw)
        public = private.public_key()
        public_b64 = base64.b64encode(
            public.public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode("ascii")
        return cls(key_id=key_id, private_key=private, public_key=public)

    @property
    def public_key_b64(self) -> str:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

        raw = self.public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(raw).decode("ascii")

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.private_key.sign(message)).decode("ascii")

    def verify(self, message: bytes, signature_b64: str) -> bool:
        try:
            self.public_key.verify(base64.b64decode(signature_b64), message)
            return True
        except Exception:
            return False


class SealedRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    merkle_root: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature: str = Field(min_length=1)
    public_key_b64: str = Field(min_length=1)
    sealed_at: str


class ProvenanceTrail(BaseModel):
    """References to the immutable artifacts that produced a GovernanceResult."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_version_id: str = Field(min_length=1)
    evidence_set_id: str = Field(min_length=1)
    assessment_id: str = Field(min_length=1)
    challenge_set_id: str = Field(min_length=1)
    human_decision_id: str = Field(min_length=1)

    assessor_prompt_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    model_invocation_id: str = Field(min_length=1)
    human_decider_id: str = Field(min_length=1)
    human_decision_timestamp: str
    workflow_step_timestamps: dict[str, str] = Field(default_factory=dict)
    rule_versions: dict[str, str] = Field(default_factory=dict)
    retrieval_receipt_id: str | None = None
    retrieval_pipeline_version: str | None = None


class GovernanceResult(BaseModel):
    """Immutable governance conclusion.

    Validity is intentionally *not* stored here. Current validity is derived from the state-event
    stream, preventing an in-place mutation of a finalized artifact.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    requirement_version_id: str = Field(min_length=1)
    evidence_set_id: str = Field(min_length=1)
    assessment_id: str = Field(min_length=1)
    challenge_set_id: str = Field(min_length=1)
    human_decision_id: str = Field(min_length=1)

    decision: Decision
    rationale: str = Field(min_length=1)
    schema_version: str = SCHEMA_VERSION
    result_version: int = Field(default=1, ge=1)
    parent_result_id: str | None = None
    supersedes_result_id: str | None = None
    created_at: str

    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance: ProvenanceTrail
    sealed_record: SealedRecord

    @model_validator(mode="after")
    def validate_internal_consistency(self) -> "GovernanceResult":
        if self.provenance.requirement_version_id != self.requirement_version_id:
            raise ValueError("provenance.requirement_version_id does not match result")
        if self.provenance.evidence_set_id != self.evidence_set_id:
            raise ValueError("provenance.evidence_set_id does not match result")
        if self.provenance.assessment_id != self.assessment_id:
            raise ValueError("provenance.assessment_id does not match result")
        if self.provenance.challenge_set_id != self.challenge_set_id:
            raise ValueError("provenance.challenge_set_id does not match result")
        if self.provenance.human_decision_id != self.human_decision_id:
            raise ValueError("provenance.human_decision_id does not match result")

        payload = self.immutable_payload()
        expected_hash = sha256_json(payload)
        if self.content_hash != expected_hash:
            raise ValueError(f"content_hash mismatch: expected {expected_hash}, got {self.content_hash}")

        if self.sealed_record.content_hash != self.content_hash:
            raise ValueError("sealed_record.content_hash does not match result content_hash")

        expected_root = merkle_root(payload)
        if self.sealed_record.merkle_root != expected_root:
            raise ValueError("sealed_record.merkle_root does not match immutable payload")

        if not verify_signature(
            self.sealed_record.public_key_b64,
            self.sealed_record.signature,
            seal_message(self.sealed_record.key_id, self.content_hash, expected_root),
        ):
            raise ValueError("invalid GovernanceResult Ed25519 signature")

        return self

    def identity_payload(self) -> dict[str, Any]:
        """Stable semantic identity. Timestamps and signatures are excluded deliberately."""
        return {
            "requirement_version_id": self.requirement_version_id,
            "evidence_set_id": self.evidence_set_id,
            "assessment_id": self.assessment_id,
            "challenge_set_id": self.challenge_set_id,
            "human_decision_id": self.human_decision_id,
            "decision": self.decision.value,
            "rationale_hash": hashlib.sha256(self.rationale.encode("utf-8")).hexdigest(),
            "schema_version": self.schema_version,
            "result_version": self.result_version,
            "parent_result_id": self.parent_result_id,
            "supersedes_result_id": self.supersedes_result_id,
        }

    def immutable_payload(self) -> dict[str, Any]:
        """Canonical payload whose SHA-256 is sealed."""
        return {
            "result_id": self.result_id,
            "requirement_version_id": self.requirement_version_id,
            "evidence_set_id": self.evidence_set_id,
            "assessment_id": self.assessment_id,
            "challenge_set_id": self.challenge_set_id,
            "human_decision_id": self.human_decision_id,
            "decision": self.decision.value,
            "rationale": self.rationale,
            "schema_version": self.schema_version,
            "result_version": self.result_version,
            "parent_result_id": self.parent_result_id,
            "supersedes_result_id": self.supersedes_result_id,
            "created_at": self.created_at,
            "provenance": self.provenance.model_dump(mode="json"),
        }


class StateTransitionEvent(BaseModel):
    """Append-only validity-state event. It changes interpretation, not the result artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_schema_version: str = EVENT_SCHEMA_VERSION
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    result_id: str = Field(min_length=1)
    from_state: ValidityState
    to_state: ValidityState
    actor_type: ActorType
    actor_id: str = Field(min_length=1)
    decision_id: str | None = None
    trigger_id: str | None = None
    trigger: TransitionTrigger
    replacement_result_id: str | None = None
    timestamp: str
    reason: str = Field(min_length=1)
    prev_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_event(self) -> "StateTransitionEvent":
        validate_transition(
            self.from_state,
            self.to_state,
            self.actor_type,
            decision_id=self.decision_id,
            replacement_result_id=self.replacement_result_id,
        )
        expected_id = event_id_for(self)
        if self.event_id != expected_id:
            raise ValueError("event_id does not match canonical event identity")
        expected_hash = sha256_json(self.event_payload())
        if self.event_hash != expected_hash:
            raise ValueError("event_hash does not match event payload")
        return self

    def event_payload(self) -> dict[str, Any]:
        return {
            "event_schema_version": self.event_schema_version,
            "event_id": self.event_id,
            "result_id": self.result_id,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "actor_type": self.actor_type.value,
            "actor_id": self.actor_id,
            "decision_id": self.decision_id,
            "trigger_id": self.trigger_id,
            "trigger": self.trigger.value,
            "replacement_result_id": self.replacement_result_id,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "prev_hash": self.prev_hash,
        }


ALLOWED_TRANSITIONS: dict[ValidityState, set[ValidityState]] = {
    ValidityState.FINALIZED: {ValidityState.CURRENT},
    ValidityState.CURRENT: {ValidityState.REVIEW_REQUIRED, ValidityState.EXPIRED, ValidityState.SUPERSEDED},
    ValidityState.REVIEW_REQUIRED: {ValidityState.REASSESSING, ValidityState.EXPIRED},
    ValidityState.REASSESSING: {ValidityState.CURRENT, ValidityState.SUPERSEDED, ValidityState.EXPIRED},
    ValidityState.SUPERSEDED: set(),
    ValidityState.EXPIRED: set(),
}


HUMAN_REQUIRED_TRANSITIONS = {
    (ValidityState.FINALIZED, ValidityState.CURRENT),
    (ValidityState.CURRENT, ValidityState.SUPERSEDED),
    (ValidityState.REASSESSING, ValidityState.CURRENT),
    (ValidityState.REASSESSING, ValidityState.SUPERSEDED),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def result_id_for(identity_payload: dict[str, Any]) -> str:
    canonical = _canon(identity_payload)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"gaar:GovernanceResult:{canonical}"))


def _leaf_hash(name: str, value: Any) -> bytes:
    return hashlib.sha256(_canon({"field": name, "value": value}).encode("utf-8")).digest()


def merkle_root(payload: dict[str, Any]) -> str:
    leaves = [_leaf_hash(k, payload[k]) for k in sorted(payload)]
    if not leaves:
        return hashlib.sha256(b"").hexdigest()
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level = level + [level[-1]]
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    return level[0].hex()


def seal_message(key_id: str, content_hash: str, root: str) -> bytes:
    return f"gaar-seal-v1|{key_id}|{content_hash}|{root}".encode("utf-8")


def verify_signature(public_key_b64: str, signature_b64: str, message: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        raw_key = base64.b64decode(public_key_b64)
        signature = base64.b64decode(signature_b64)
        Ed25519PublicKey.from_public_bytes(raw_key).verify(signature, message)
        return True
    except Exception:
        return False


def _sign(key: CanonicalSigner, message: bytes) -> str:
    return key.sign(message)


def create_governance_result(
    *,
    requirement_version_id: str,
    evidence_set_id: str,
    assessment_id: str,
    challenge_set_id: str,
    human_decision_id: str,
    decision: Decision | str,
    rationale: str,
    provenance: ProvenanceTrail | dict[str, Any],
    signer: CanonicalSigner,
    result_version: int = 1,
    parent_result_id: str | None = None,
    supersedes_result_id: str | None = None,
    created_at: str | None = None,
) -> GovernanceResult:
    """Compile the existing engine's output into a sealed GovernanceResult.

    No existing assessor/challenger code is called or modified by this function.
    """
    d = Decision(decision)
    prov = provenance if isinstance(provenance, ProvenanceTrail) else ProvenanceTrail.model_validate(provenance)
    created = created_at or _now()

    identity_base = {
        "requirement_version_id": requirement_version_id,
        "evidence_set_id": evidence_set_id,
        "assessment_id": assessment_id,
        "challenge_set_id": challenge_set_id,
        "human_decision_id": human_decision_id,
        "decision": d.value,
        "rationale_hash": hashlib.sha256(rationale.encode("utf-8")).hexdigest(),
        "schema_version": SCHEMA_VERSION,
        "result_version": result_version,
        "parent_result_id": parent_result_id,
        "supersedes_result_id": supersedes_result_id,
    }
    result_id = result_id_for(identity_base)

    unsigned = GovernanceResult.model_construct(
        result_id=result_id,
        requirement_version_id=requirement_version_id,
        evidence_set_id=evidence_set_id,
        assessment_id=assessment_id,
        challenge_set_id=challenge_set_id,
        human_decision_id=human_decision_id,
        decision=d,
        rationale=rationale,
        schema_version=SCHEMA_VERSION,
        result_version=result_version,
        parent_result_id=parent_result_id,
        supersedes_result_id=supersedes_result_id,
        created_at=created,
        content_hash="0" * 64,
        provenance=prov,
        sealed_record=SealedRecord(
            key_id=signer.key_id,
            content_hash="0" * 64,
            merkle_root="0" * 64,
            signature="AA==",
            public_key_b64=signer.public_key_b64,
            sealed_at=_now(),
        ),
    )
    payload = unsigned.immutable_payload()
    content_hash = sha256_json(payload)
    root = merkle_root(payload)
    signature = _sign(signer, seal_message(signer.key_id, content_hash, root))
    sealed = SealedRecord(
        key_id=signer.key_id,
        content_hash=content_hash,
        merkle_root=root,
        signature=signature,
        public_key_b64=signer.public_key_b64,
        sealed_at=_now(),
    )
    return GovernanceResult(
        result_id=result_id,
        requirement_version_id=requirement_version_id,
        evidence_set_id=evidence_set_id,
        assessment_id=assessment_id,
        challenge_set_id=challenge_set_id,
        human_decision_id=human_decision_id,
        decision=d,
        rationale=rationale,
        schema_version=SCHEMA_VERSION,
        result_version=result_version,
        parent_result_id=parent_result_id,
        supersedes_result_id=supersedes_result_id,
        created_at=created,
        content_hash=content_hash,
        provenance=prov,
        sealed_record=sealed,
    )


# Backward-compatible naming for the proposed compiler call-site.
def compile_sealed_governance_result(**kwargs: Any) -> GovernanceResult:
    return create_governance_result(**kwargs)


def validate_transition(
    from_state: ValidityState,
    to_state: ValidityState,
    actor_type: ActorType,
    *,
    decision_id: str | None = None,
    replacement_result_id: str | None = None,
) -> None:
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, set()):
        raise ValueError(f"invalid GovernanceResult transition: {from_state.value} -> {to_state.value}")
    if (from_state, to_state) in HUMAN_REQUIRED_TRANSITIONS and actor_type != ActorType.HUMAN:
        raise ValueError(f"human governance is required for {from_state.value} -> {to_state.value}")
    if actor_type == ActorType.HUMAN and (from_state, to_state) in HUMAN_REQUIRED_TRANSITIONS and not decision_id:
        raise ValueError("decision_id is required for human-governed state transitions")
    if to_state == ValidityState.SUPERSEDED and not replacement_result_id:
        raise ValueError("replacement_result_id is required when superseding a result")


def event_id_for(event: StateTransitionEvent) -> str:
    identity = {
        "event_schema_version": event.event_schema_version,
        "result_id": event.result_id,
        "from_state": event.from_state.value,
        "to_state": event.to_state.value,
        "actor_type": event.actor_type.value,
        "actor_id": event.actor_id,
        "decision_id": event.decision_id,
        "trigger_id": event.trigger_id,
        "trigger": event.trigger.value,
        "replacement_result_id": event.replacement_result_id,
        "timestamp": event.timestamp,
        "reason": event.reason,
    }
    return uuid.uuid5(uuid.NAMESPACE_URL, f"gaar:GovernanceResultStateEvent:{_canon(identity)}").hex


def make_state_event(
    *,
    result: GovernanceResult,
    to_state: ValidityState,
    actor_type: ActorType,
    actor_id: str,
    trigger: TransitionTrigger,
    reason: str,
    current_state: ValidityState,
    decision_id: str | None = None,
    trigger_id: str | None = None,
    replacement_result_id: str | None = None,
    timestamp: str | None = None,
    prev_hash: str = "0" * 64,
) -> StateTransitionEvent:
    ts = timestamp or _now()
    raw = {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "result_id": result.result_id,
        "from_state": current_state.value,
        "to_state": to_state.value,
        "actor_type": actor_type.value,
        "actor_id": actor_id,
        "decision_id": decision_id,
        "trigger_id": trigger_id,
        "trigger": trigger.value,
        "replacement_result_id": replacement_result_id,
        "timestamp": ts,
        "reason": reason,
    }
    candidate_id = uuid.uuid5(uuid.NAMESPACE_URL, f"gaar:GovernanceResultStateEvent:{_canon({k: raw[k] for k in raw})}").hex
    payload = {
        **raw,
        "event_id": candidate_id,
        "prev_hash": prev_hash,
    }
    event_hash = sha256_json(payload)
    return StateTransitionEvent(
        event_schema_version=EVENT_SCHEMA_VERSION,
        event_id=candidate_id,
        result_id=result.result_id,
        from_state=current_state,
        to_state=to_state,
        actor_type=actor_type,
        actor_id=actor_id,
        decision_id=decision_id,
        trigger_id=trigger_id,
        trigger=trigger,
        replacement_result_id=replacement_result_id,
        timestamp=ts,
        reason=reason,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )


def approve_result(result: GovernanceResult, *, actor_id: str, decision_id: str, reason: str,
                   timestamp: str | None = None, prev_hash: str = "0" * 64) -> StateTransitionEvent:
    return make_state_event(
        result=result,
        to_state=ValidityState.CURRENT,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        trigger=TransitionTrigger.GOVERNANCE_APPROVAL,
        reason=reason,
        current_state=ValidityState.FINALIZED,
        decision_id=decision_id,
        timestamp=timestamp,
        prev_hash=prev_hash,
    )


def mark_review_required(result: GovernanceResult, *, actor_id: str, trigger_id: str, reason: str,
                         timestamp: str | None = None, prev_hash: str = "0" * 64) -> StateTransitionEvent:
    return make_state_event(
        result=result,
        to_state=ValidityState.REVIEW_REQUIRED,
        actor_type=ActorType.SYSTEM,
        actor_id=actor_id,
        trigger=TransitionTrigger.GOVERNANCE_CHANGE,
        reason=reason,
        current_state=ValidityState.CURRENT,
        trigger_id=trigger_id,
        timestamp=timestamp,
        prev_hash=prev_hash,
    )


def begin_reassessment(
    result: GovernanceResult, *, actor_id: str, case_id: str, reason: str,
    timestamp: str | None = None, prev_hash: str = "0" * 64,
) -> StateTransitionEvent:
    """SYSTEM opens the reassessment execution state after REVIEW_REQUIRED.

    No human decision is required to start the workflow; no governance conclusion is made.
    """
    return make_state_event(
        result=result,
        to_state=ValidityState.REASSESSING,
        actor_type=ActorType.SYSTEM,
        actor_id=actor_id,
        trigger=TransitionTrigger.REASSESSMENT,
        reason=reason,
        current_state=ValidityState.REVIEW_REQUIRED,
        trigger_id=case_id,
        timestamp=timestamp,
        prev_hash=prev_hash,
    )


def reconfirm_current(
    result: GovernanceResult, *, actor_id: str, decision_id: str, reason: str = "Reassessment confirmed current",
    timestamp: str | None = None, prev_hash: str = "0" * 64,
) -> StateTransitionEvent:
    """Human governance confirms the existing immutable result remains current after reassessment."""
    return make_state_event(
        result=result,
        to_state=ValidityState.CURRENT,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        trigger=TransitionTrigger.REASSESSMENT,
        reason=reason,
        current_state=ValidityState.REASSESSING,
        decision_id=decision_id,
        timestamp=timestamp,
        prev_hash=prev_hash,
    )


def supersede_reassessing_result(
    old_result: GovernanceResult,
    new_result: GovernanceResult,
    *,
    actor_id: str,
    decision_id: str,
    reason: str = "Reassessment approved with replacement result",
    old_prev_hash: str = "0" * 64,
    new_prev_hash: str = "0" * 64,
    timestamp: str | None = None,
) -> tuple[StateTransitionEvent, StateTransitionEvent]:
    """Human-governed supersession after the old result has entered REASSESSING."""
    ts = timestamp or _now()
    old_event = make_state_event(
        result=old_result,
        to_state=ValidityState.SUPERSEDED,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        trigger=TransitionTrigger.REASSESSMENT,
        reason=reason,
        current_state=ValidityState.REASSESSING,
        decision_id=decision_id,
        replacement_result_id=new_result.result_id,
        timestamp=ts,
        prev_hash=old_prev_hash,
    )
    new_event = make_state_event(
        result=new_result,
        to_state=ValidityState.CURRENT,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        trigger=TransitionTrigger.REASSESSMENT,
        reason=reason,
        current_state=ValidityState.FINALIZED,
        decision_id=decision_id,
        timestamp=ts,
        prev_hash=(old_event.event_hash if new_prev_hash == "0" * 64 else new_prev_hash),
    )
    return old_event, new_event


def supersede_result(
    old_result: GovernanceResult,
    new_result: GovernanceResult,
    *,
    actor_id: str,
    decision_id: str,
    reason: str = "Reassessment approved",
    old_prev_hash: str = "0" * 64,
    new_prev_hash: str = "0" * 64,
    timestamp: str | None = None,
) -> tuple[StateTransitionEvent, StateTransitionEvent]:
    ts = timestamp or _now()
    old_event = make_state_event(
        result=old_result,
        to_state=ValidityState.SUPERSEDED,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        trigger=TransitionTrigger.REASSESSMENT,
        reason=reason,
        current_state=ValidityState.CURRENT,
        decision_id=decision_id,
        replacement_result_id=new_result.result_id,
        timestamp=ts,
        prev_hash=old_prev_hash,
    )
    new_event = make_state_event(
        result=new_result,
        to_state=ValidityState.CURRENT,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        trigger=TransitionTrigger.REASSESSMENT,
        reason=reason,
        current_state=ValidityState.FINALIZED,
        decision_id=decision_id,
        timestamp=ts,
        prev_hash=(old_event.event_hash if new_prev_hash == "0" * 64 else new_prev_hash),
    )
    return old_event, new_event


class ResultStateLog:
    """Small append-only JSONL state-event store with a SHA-256 chain."""

    def __init__(self, path: str | Path = STATE_EVENT_LOG):
        self.path = Path(path)

    def append(self, event: StateTransitionEvent) -> StateTransitionEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous = self.last_hash()
        if event.prev_hash != previous:
            raise ValueError(f"state event prev_hash mismatch: expected {previous}, got {event.prev_hash}")
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+") as lock:
            try:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                previous = self.last_hash()
                if event.prev_hash != previous:
                    raise ValueError(f"state event prev_hash mismatch: expected {previous}, got {event.prev_hash}")
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(_canon(event.model_dump(mode="json")) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            finally:
                try:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass
        return event

    def last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = None
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        return (last or {}).get("event_hash", "0" * 64)

    def read(self) -> list[StateTransitionEvent]:
        if not self.path.exists():
            return []
        out = []
        prev = "0" * 64
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                e = StateTransitionEvent.model_validate(json.loads(line))
                if e.prev_hash != prev:
                    raise ValueError(f"state event chain broken at {e.event_id}")
                prev = e.event_hash
                out.append(e)
        return out

    def current_state(self, result_id: str) -> ValidityState | None:
        state = None
        for event in self.read():
            if event.result_id == result_id:
                state = event.to_state
        return state


__all__ = [
    "ActorType",
    "CanonicalSigner",
    "Decision",
    "GovernanceResult",
    "ProvenanceTrail",
    "ResultStateLog",
    "SealedRecord",
    "StateTransitionEvent",
    "TransitionTrigger",
    "ValidityState",
    "approve_result",
    "begin_reassessment",
    "reconfirm_current",
    "supersede_reassessing_result",
    "compile_sealed_governance_result",
    "create_governance_result",
    "mark_review_required",
    "merkle_root",
    "result_id_for",
    "supersede_result",
]
