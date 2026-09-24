#!/usr/bin/env python3
"""WB-134 optional source polling/status. No ADD, COMMIT, PUSH or decision writes."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.watcher.policy import load_sources, DEFAULT_CONFIG
from governance.watcher.update_centre import ScanReceipts
from governance.watcher.continuous import scan_once
import yaml

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('status','scan'))
    p.add_argument('--config',default=None)
    p.add_argument('--force',action='store_true',help='Run one explicitly requested scan even if background scheduler disabled')
    a=p.parse_args()
    if a.action=='scan':
        rows=scan_once(config=a.config,force=a.force)
    else:
        registry=yaml.safe_load(Path(a.config or DEFAULT_CONFIG).read_text(encoding='utf-8')) or {}
        receipts=ScanReceipts()
        rows=[receipts.status(str(r['source_id']),enabled=bool(r.get('enabled',True))) for r in registry.get('sources',[])]
    print(json.dumps(rows,indent=2,ensure_ascii=False,default=str))
if __name__=='__main__':main()
