from __future__ import annotations
from pathlib import Path
import os
from governance.watcher.store import HashChainStore
ROOT=Path(__file__).resolve().parents[1]
class ScoutStore:
    def __init__(self,path=None): self.store=HashChainStore(path or os.environ.get("WB_GAAR_SCOUT_STORE",ROOT/"evidence_scout.jsonl"),"gaar.evidence-scout.v1")
    def append(self,payload): return self.store.append("EvidenceScoutRun",payload)
    def read(self): return self.store.read()
