from __future__ import annotations
import fcntl, hashlib, json, os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GENESIS = "0" * 64


def _canon(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def _sha(v: Any) -> str:
    return hashlib.sha256(_canon(v).encode()).hexdigest()

@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lp = path.with_name(path.name + ".lock")
    with lp.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

class HashChainStore:
    def __init__(self, path: str | Path, schema: str): self.path=Path(path); self.schema=schema
    def read(self) -> list[dict[str,Any]]:
        if not self.path.exists(): return []
        out=[]; prev=GENESIS
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            row=json.loads(line)
            if row.get("prev_hash") != prev: raise ValueError(f"{self.schema} chain is broken")
            exp=_sha({k:v for k,v in row.items() if k!="record_hash"})
            if row.get("record_hash") != exp: raise ValueError(f"{self.schema} record hash is invalid")
            out.append(row); prev=row["record_hash"]
        return out
    def append(self, record_type: str, payload: dict[str,Any]) -> dict[str,Any]:
        with _lock(self.path):
            rows=self.read(); prev=rows[-1]["record_hash"] if rows else GENESIS
            row={"schema_version":self.schema,"record_type":record_type,"prev_hash":prev,"payload":payload}
            row["record_hash"]=_sha(row)
            with self.path.open("a",encoding="utf-8") as fh:
                fh.write(_canon(row)+"\n"); fh.flush(); os.fsync(fh.fileno())
            return row

class CursorStore:
    def __init__(self,path: str|Path|None=None):
        self.store=HashChainStore(path or os.environ.get("WB_GAAR_WATCHER_CURSOR_STORE",ROOT/"watcher_cursors.jsonl"),"gaar.watcher-cursor.v1")
    def get(self,source_id:str) -> str|None:
        value=None
        for row in self.store.read():
            p=row["payload"]
            if p.get("source_id")==source_id: value=p.get("cursor")
        return value
    def update(self,source_id:str,cursor:str,*,run_id:str) -> dict[str,Any]:
        return self.store.append("CursorAdvanced",{"source_id":source_id,"cursor":cursor,"run_id":run_id})

class EmissionStore:
    def __init__(self,path: str|Path|None=None):
        self.store=HashChainStore(path or os.environ.get("WB_GAAR_WATCHER_EMISSION_STORE",ROOT/"watcher_emissions.jsonl"),"gaar.watcher-emission.v1")
    def read(self): return self.store.read()
    def has_content(self,source_id:str,content_hash:str)->bool:
        return any((r.get("payload") or {}).get("source_id")==source_id and (r.get("payload") or {}).get("content_hash")==content_hash for r in self.read())
    def append(self,payload:dict[str,Any]): return self.store.append("WatcherEmissionEvent",payload)

class HealthStore:
    def __init__(self,path: str|Path|None=None):
        self.store=HashChainStore(path or os.environ.get("WB_GAAR_WATCHER_HEALTH_STORE",ROOT/"watcher_health.jsonl"),"gaar.watcher-health.v1")
    def record(self,payload:dict[str,Any]): return self.store.append("WatcherHealth",payload)
    def latest(self,source_id:str)->dict[str,Any]|None:
        hit=None
        for r in self.store.read():
            if (r.get("payload") or {}).get("source_id")==source_id: hit=r["payload"]
        return hit
