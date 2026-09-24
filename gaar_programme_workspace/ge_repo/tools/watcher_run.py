#!/usr/bin/env python3
from __future__ import annotations
import argparse,time,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.watcher import RegulatoryWatcherAgent, load_sources

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config"); ap.add_argument("--duration",type=int,default=60); ap.add_argument("--interval",type=int,default=30); ap.add_argument("--max-runs",type=int,default=0); args=ap.parse_args()
    agent=RegulatoryWatcherAgent(); sources=load_sources(args.config); start=time.time(); runs=0
    while time.time()-start < args.duration:
        for s in sources:
            result=agent.run_source(s); print(json.dumps(result.__dict__,sort_keys=True,default=str),flush=True)
        runs+=1
        if args.max_runs and runs>=args.max_runs: break
        time.sleep(max(1,args.interval))
if __name__=="__main__": main()
