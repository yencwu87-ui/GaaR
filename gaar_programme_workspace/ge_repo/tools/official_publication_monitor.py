#!/usr/bin/env python3
"""WB-135 official index status/scan; never ADD/COMMIT/PUSH."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.watcher.official_index import OfficialIndexMonitor,load_manifest,scan_due

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('status','scan'))
    p.add_argument('--config',default=None)
    p.add_argument('--force',action='store_true',help='Explicit one-time scan (bypasses enable environment and due timer, but not disabled source flags)')
    a=p.parse_args()
    rows=scan_due(manifest=a.config,force=a.force) if a.action=='scan' else [OfficialIndexMonitor().status(row) for row in load_manifest(a.config)]
    print(json.dumps(rows,ensure_ascii=False,indent=2,default=str))
if __name__=='__main__':main()
