from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    REGULATION = "regulation"
    GUIDANCE = "guidance"
    STANDARD = "standard"
    THREAT = "threat"
    BUSINESS = "business"
    BACKGROUND = "background"


class WatcherAuthority(str, Enum):
    BINDING = "binding"
    MANDATORY = "mandatory"
    EXPECTATION = "expectation"
    INDUSTRY = "industry"
    THREAT = "threat"
    BUSINESS = "business"
    BACKGROUND = "background"

    @property
    def governance_impact_eligible(self) -> bool:
        return self in {self.BINDING, self.MANDATORY, self.EXPECTATION}


@dataclass(frozen=True)
class WatcherConfig:
    source_id: str
    source_type: SourceType
    authority: WatcherAuthority
    jurisdiction: str
    connector: dict[str, Any]
    schedule: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)
    dedup_window_hours: int = 24
    max_items_per_run: int = 100
    cursor_field: str = "last_modified"
    min_confidence: float = 0.85
    materiality_threshold: float = 0.60
    max_consecutive_failures: int = 3
    requests_per_minute: int = 30
    backoff_multiplier: float = 2.0
    enabled: bool = True

    def validate(self) -> None:
        if not self.source_id.strip(): raise ValueError("source_id is required")
        if not self.jurisdiction.strip(): raise ValueError("jurisdiction is required")
        if not isinstance(self.connector, dict) or not self.connector.get("type"):
            raise ValueError("connector.type is required")
        if not 0 <= self.min_confidence <= 1: raise ValueError("min_confidence must be within [0,1]")
        if not 0 <= self.materiality_threshold <= 1: raise ValueError("materiality_threshold must be within [0,1]")
        if self.max_items_per_run < 1: raise ValueError("max_items_per_run must be positive")


@dataclass(frozen=True)
class RawDocument:
    document_id: str
    title: str
    url: str
    content: str
    published_at: str | None = None
    effective_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedRequirement:
    control_id: str
    requirement_text: str
    section: str | None = None
    change_type: str = "CHANGED"


@dataclass(frozen=True)
class Classification:
    authority: WatcherAuthority
    jurisdiction: str
    materiality: float
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplicabilityAssessment:
    applicable: bool
    controls: tuple[str, ...]
    framework: str | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernanceChangeEvent:
    change_id: str
    source_id: str
    source_type: str
    authority: str
    jurisdiction: str
    document_title: str
    document_url: str
    publication_date: str | None
    effective_date: str | None
    content_hash: str
    previous_version_hash: str | None
    changed_sections: tuple[str, ...]
    extracted_requirements: tuple[dict[str, Any], ...]
    applicability: dict[str, Any]
    materiality_score: float
    classification_confidence: float
    raw_content_ref: str
    emitted_at: str
    emitted_by: str = "regulatory-watcher-agent"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmissionReceipt:
    change_id: str
    source_id: str
    emitted: bool
    reason: str


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
