from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os, yaml
from .models import SourceType, WatcherAuthority, WatcherConfig

DEFAULT_CONFIG=Path(__file__).resolve().parents[2]/"config"/"watcher_sources.yaml"

def _config(row:dict[str,Any])->WatcherConfig:
    return WatcherConfig(
        source_id=str(row["source_id"]),source_type=SourceType(str(row.get("source_type","background"))),authority=WatcherAuthority(str(row.get("authority","background"))),
        jurisdiction=str(row.get("jurisdiction") or "GLOBAL"),connector=dict(row.get("connector") or {}),schedule=dict(row.get("schedule") or {}),filters=dict(row.get("filters") or {}),
        dedup_window_hours=int(row.get("dedup_window_hours",24)),max_items_per_run=int(row.get("max_items_per_run",100)),cursor_field=str(row.get("cursor_field","last_modified")),
        min_confidence=float(row.get("min_confidence",0.85)),materiality_threshold=float(row.get("materiality_threshold",0.60)),max_consecutive_failures=int(row.get("max_consecutive_failures",3)),
        requests_per_minute=int(row.get("requests_per_minute",30)),backoff_multiplier=float(row.get("backoff_multiplier",2.0)),enabled=bool(row.get("enabled",True)))

def load_sources(path:str|Path|None=None)->tuple[WatcherConfig,...]:
    p=Path(path or os.environ.get("WB_GAAR_WATCHER_CONFIG",DEFAULT_CONFIG))
    if not p.exists(): return ()
    raw=yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out=[]
    for row in raw.get("sources") or []:
        cfg=_config(row); cfg.validate()
        if cfg.enabled: out.append(cfg)
    return tuple(out)
