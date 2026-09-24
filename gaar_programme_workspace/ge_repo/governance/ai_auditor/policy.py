from __future__ import annotations

import os
from pathlib import Path
import yaml

from .schemas import HumanExceptionPolicy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "ai_auditor_policy.yaml"


def load_policy(path: str | Path | None = None) -> HumanExceptionPolicy:
    p = Path(path or os.environ.get("WB_GAAR_AI_AUDITOR_POLICY", DEFAULT_POLICY))
    if not p.exists():
        return HumanExceptionPolicy()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    policy = raw.get("human_exception_policy", raw)
    return HumanExceptionPolicy.model_validate(policy)


def enabled() -> bool:
    return os.environ.get("WB_GAAR_AI_AUDITOR", "0").strip().lower() in {"1", "true", "yes", "on"}
