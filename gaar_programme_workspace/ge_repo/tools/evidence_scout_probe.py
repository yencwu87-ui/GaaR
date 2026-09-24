#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.evidence_scout import EvidenceScoutAgent,EvidenceSource,ScoutRequest

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',action='append',required=True); ap.add_argument('--control',required=True); ap.add_argument('--framework',default=''); ap.add_argument('--requirement',required=True); ap.add_argument('--element',action='append',default=[]); ap.add_argument('--max',type=int,default=12); args=ap.parse_args()
    sources=[EvidenceSource(f'root{i+1}',r) for i,r in enumerate(args.root)]
    res=EvidenceScoutAgent(sources).run(ScoutRequest(args.control,args.framework,args.requirement,tuple(args.element),args.max))
    print(json.dumps(res.to_dict(),indent=2))
if __name__=='__main__': main()
