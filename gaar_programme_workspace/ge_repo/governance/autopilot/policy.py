from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / 'config' / 'autopilot_policy.yaml'

@dataclass(frozen=True)
class AutopilotPolicy:
    enabled: bool = False
    max_concurrent_reassessments: int = 3
    regulatory_scan_seconds: int = 3600
    evidence_scan_seconds: int = 86400
    threat_scan_seconds: int = 300
    model_scan_seconds: int = 3600
    max_evidence_age_days: int = 90
    min_evidence_sources: int = 1
    evidence_sufficiency_threshold: float = 0.70
    human_checkpoint_triggers: tuple[str, ...] = ()
    colibri_enabled: bool = True
    colibri_policy: str = 'governed-v1'
    colibri_triggers: tuple[str, ...] = ()

    def requires_human(self, reasons: set[str] | list[str] | tuple[str, ...]) -> bool:
        policy = set(self.human_checkpoint_triggers)
        return bool(policy.intersection(set(reasons)))


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1','true','yes','on'}


def load_policy(path: str | Path | None = None) -> AutopilotPolicy:
    p = Path(path or os.environ.get('WB_GAAR_AUTOPILOT_POLICY', DEFAULT_POLICY))
    raw: dict[str, Any] = {}
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    ap = raw.get('autopilot') or {}
    scans = ap.get('scan_intervals') or {}
    reass = ap.get('reassessment') or {}
    col = ap.get('colibri_escalation') or {}
    enabled = _bool_env('WB_GAAR_AUTOPILOT', bool(ap.get('enabled', False)))
    concurrency = int(os.environ.get('WB_GAAR_AUTOPILOT_MAX_CONCURRENT', ap.get('max_concurrent_reassessments', 3)))
    if concurrency < 1:
        raise ValueError('max_concurrent_reassessments must be >= 1')
    threshold = float(os.environ.get('WB_GAAR_QUALITY_EVIDENCE_THRESHOLD', reass.get('evidence_sufficiency_threshold', 0.70)))
    if not (0.0 <= threshold <= 1.0):
        raise ValueError('evidence_sufficiency_threshold must be between 0 and 1')
    return AutopilotPolicy(
        enabled=enabled,
        max_concurrent_reassessments=concurrency,
        regulatory_scan_seconds=int(scans.get('regulatory', 3600)),
        evidence_scan_seconds=int(scans.get('evidence_freshness', 86400)),
        threat_scan_seconds=int(scans.get('threat_intel', 300)),
        model_scan_seconds=int(scans.get('model_updates', 3600)),
        max_evidence_age_days=int(reass.get('max_evidence_age_days', 90)),
        min_evidence_sources=int(os.environ.get('WB_GAAR_QUALITY_MIN_SOURCES', reass.get('min_evidence_sources', 1))),
        evidence_sufficiency_threshold=threshold,
        human_checkpoint_triggers=tuple(str(x) for x in (ap.get('human_checkpoint_triggers') or ())),
        colibri_enabled=bool(col.get('enabled', True)),
        colibri_policy=str(col.get('policy', 'governed-v1')),
        colibri_triggers=tuple(str(x) for x in (col.get('triggers') or ())),
    )
