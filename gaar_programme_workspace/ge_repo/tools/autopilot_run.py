#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.autopilot import AutopilotScheduler, load_policy

def main():
    ap=argparse.ArgumentParser(description='Claim queued GaaR autopilot work. This CLI does not invent regulatory-change context.')
    ap.add_argument('--claim',action='store_true'); args=ap.parse_args()
    sched=AutopilotScheduler(policy=load_policy())
    if args.claim:
        claimed=sched.claim(); print(f'claimed: {len(claimed)}')
        for j in claimed: print(json.dumps(j.to_dict(),sort_keys=True,default=str))
        if claimed:
            print('NOTE: claimed jobs require their typed trigger adapter/context before execution; no human decision is synthesized.')
    else:
        st=sched.status(); print(json.dumps({k:v for k,v in st.items() if k!='jobs'},indent=2,default=str))
if __name__=='__main__': main()
