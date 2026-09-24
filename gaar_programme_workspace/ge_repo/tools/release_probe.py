#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.release_readiness import evaluate_release_readiness
if __name__=='__main__':
    r=evaluate_release_readiness(); print(json.dumps(r.to_dict(),indent=2)); raise SystemExit(0 if r.ready else 2)
