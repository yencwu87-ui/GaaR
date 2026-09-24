from __future__ import annotations

import hashlib, json, os, fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = ROOT / 'autopilot_triggers.jsonl'
GENESIS = '0' * 64

class TriggerType(str, Enum):
    GOVERNANCE_CHANGE = 'GOVERNANCE_CHANGE'
    EVIDENCE_FRESHNESS = 'EVIDENCE_FRESHNESS'
    SCHEDULED_REVIEW = 'SCHEDULED_REVIEW'
    MANUAL = 'MANUAL'

@dataclass(frozen=True)
class AutopilotTrigger:
    trigger_id: str
    trigger_type: TriggerType
    control_id: str
    framework: str
    detected_at: str
    reason: str
    material: bool
    source_id: str | None = None
    change_id: str | None = None
    payload_hash: str = ''
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self); raw['trigger_type'] = self.trigger_type.value
        return raw


def _canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)

def _sha(v: Any) -> str:
    return hashlib.sha256(_canon(v).encode()).hexdigest()

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lp = path.with_name(path.name + '.lock')
    with lp.open('a+') as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

class TriggerStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get('WB_GAAR_AUTOPILOT_TRIGGER_STORE', DEFAULT_STORE))

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists(): return []
        out=[]; prev=GENESIS
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            row=json.loads(line)
            if row.get('prev_hash') != prev: raise ValueError('autopilot trigger chain is broken')
            expected=_sha({k:v for k,v in row.items() if k!='record_hash'})
            if row.get('record_hash') != expected: raise ValueError('autopilot trigger record hash is invalid')
            out.append(row); prev=row['record_hash']
        return out

    def last_hash(self) -> str:
        rows=self.read(); return rows[-1]['record_hash'] if rows else GENESIS

    def seen_payload_hash(self, payload_hash: str) -> bool:
        return any((r.get('trigger') or {}).get('payload_hash') == payload_hash for r in self.read())

    def append(self, trigger: AutopilotTrigger) -> AutopilotTrigger:
        with _lock(self.path):
            prev=self.last_hash()
            row={'schema_version':'gaar.autopilot-trigger.v1','prev_hash':prev,'trigger':trigger.to_dict()}
            row['record_hash']=_sha(row)
            with self.path.open('a',encoding='utf-8') as fh:
                fh.write(_canon(row)+'\n'); fh.flush(); os.fsync(fh.fileno())
        return trigger

class ChangeMonitor:
    def __init__(self, store: TriggerStore | None = None): self.store=store or TriggerStore()

    def emit(self, *, trigger_type: TriggerType | str, control_id: str, framework: str, reason: str,
             material: bool, source_id: str | None = None, change_id: str | None = None,
             payload: Any = None, metadata: dict[str, Any] | None = None, detected_at: str | None = None) -> AutopilotTrigger | None:
        tt=TriggerType(trigger_type)
        body={'trigger_type':tt.value,'control_id':str(control_id),'framework':str(framework),'reason':str(reason),
              'material':bool(material),'source_id':source_id,'change_id':change_id,'payload':payload}
        ph=_sha(body)
        if self.store.seen_payload_hash(ph): return None
        trig=AutopilotTrigger(trigger_id='AT-'+_sha({'payload_hash':ph,'detected_at':detected_at or _now()})[:24],
            trigger_type=tt, control_id=str(control_id), framework=str(framework), detected_at=detected_at or _now(),
            reason=str(reason), material=bool(material), source_id=source_id, change_id=change_id,
            payload_hash=ph, metadata=dict(metadata or {}))
        return self.store.append(trig)
