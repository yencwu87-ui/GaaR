from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    root: str
    source_class: str = "internal"
    trusted: bool = True
    allowed_extensions: tuple[str,...] = (".md",".txt",".json",".csv",".yaml",".yml")
    max_file_bytes: int = 2_000_000

@dataclass(frozen=True)
class EvidenceCandidate:
    candidate_id: str
    source_id: str
    path: str
    locator: str
    content_hash: str
    score: float
    matched_terms: tuple[str,...]
    excerpt: str
    mtime: float
    source_class: str
    trusted: bool
    detected_framework: str = ""
    detected_control_id: str = ""
    control_match: str = "UNCLASSIFIED"
    def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class ScoutRequest:
    control_id: str
    framework: str
    requirement: str
    element_texts: tuple[str,...]
    max_candidates: int = 12
    min_score: float = 0.05

@dataclass(frozen=True)
class ScoutResult:
    scout_run_id: str
    control_id: str
    framework: str
    candidates: tuple[EvidenceCandidate,...]
    source_count: int
    gaps: tuple[str,...]
    recommended_action: str
    def to_dict(self):
        return {"scout_run_id":self.scout_run_id,"control_id":self.control_id,"framework":self.framework,
                "candidates":[x.to_dict() for x in self.candidates],"source_count":self.source_count,
                "gaps":list(self.gaps),"recommended_action":self.recommended_action}
