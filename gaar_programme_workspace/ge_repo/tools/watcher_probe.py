#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.watcher import EmissionStore, CursorStore, HealthStore, RegulatoryWatcherAgent, load_sources

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config"); ap.add_argument("--source-id"); ap.add_argument("--run",action="store_true"); args=ap.parse_args()
    sources=list(load_sources(args.config));
    if args.source_id: sources=[s for s in sources if s.source_id==args.source_id]
    print(json.dumps({"sources":[{"source_id":s.source_id,"authority":s.authority.value,"jurisdiction":s.jurisdiction,"connector":s.connector.get("type")} for s in sources],"emissions":len(EmissionStore().read())},indent=2))
    if args.run:
        agent=RegulatoryWatcherAgent()
        for s in sources: print(json.dumps(agent.run_source(s).__dict__,indent=2,default=str))
if __name__=="__main__": main()
