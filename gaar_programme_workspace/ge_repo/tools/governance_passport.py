#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.passport import governance_passport,verify_passport
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('result_id'); ap.add_argument('--verify',action='store_true'); a=ap.parse_args(); p=governance_passport(a.result_id); print(json.dumps(verify_passport(p) if a.verify else p,indent=2))
