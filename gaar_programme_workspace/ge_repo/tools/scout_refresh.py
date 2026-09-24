#!/usr/bin/env python3
"""Reproducible WB-120R approved local evidence refresh; no review-state mutation."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.evidence_scout import EvidenceSource
from governance.evidence_scout.refresh import RefreshAgent, RefreshPolicy

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',action='append',required=True,help='Explicitly approved local evidence root (repeatable)')
    p.add_argument('--control',required=True)
    p.add_argument('--framework',required=True)
    p.add_argument('--requirement',required=True)
    p.add_argument('--requirement-version',default='')
    p.add_argument('--element',action='append',default=[])
    p.add_argument('--max-age-days',type=int,default=90)
    p.add_argument('--min-sources',type=int,default=1)
    args=p.parse_args()
    sources=[EvidenceSource(f'root{i+1}',root) for i,root in enumerate(args.root)]
    policy=RefreshPolicy(max_age_days=args.max_age_days,min_sources=args.min_sources)
    result=RefreshAgent(sources,policy=policy).run(args.control,args.framework,args.requirement,
        tuple(args.element),requirement_version_id=args.requirement_version)
    print(json.dumps(result,indent=2))
    return 0 if result['recommended_action']=='REVIEW_CANDIDATES' else 2
if __name__=='__main__': raise SystemExit(main())
