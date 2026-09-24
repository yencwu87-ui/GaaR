#!/usr/bin/env python3
"""One-command approved-root Scout → source-verified dossier → human checkpoint.

STP preparation, not STP publication: no binding of proposed evidence, reviewer
impersonation, policy override or CURRENT result transition.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.evidence_scout import EvidenceSource
from governance.evidence_scout.refresh import RefreshAgent,RefreshPolicy
from governance.evidence_scout.dossier import EvidenceAssemblyAgent,ImmutableBlobStore,DossierStore,render_markdown
from governance.audit_package import ReviewContext,prepare_package

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',action='append',required=True,help='Approved absolute local evidence directory (repeatable)')
    p.add_argument('--control',required=True)
    p.add_argument('--framework',required=True)
    p.add_argument('--requirement-version',required=True)
    p.add_argument('--requirement',required=True)
    p.add_argument('--assertion',required=True)
    p.add_argument('--element',action='append',default=[])
    p.add_argument('--output',type=Path,help='Optional dossier markdown output')
    p.add_argument('--risk-tier',choices=['low','medium','high','critical','unknown'],default='unknown')
    p.add_argument('--max-age-days',type=int,default=90)
    a=p.parse_args()
    roots=[Path(s).expanduser().resolve(strict=True) for s in a.root]
    if any(not r.is_dir() for r in roots) or len(set(roots))!=len(roots):p.error('distinct approved directories required')
    source_ids={f'root{i+1}':str(path) for i,path in enumerate(roots)}
    receipt=RefreshAgent([EvidenceSource(sid,path) for sid,path in source_ids.items()],
                         policy=RefreshPolicy(max_age_days=a.max_age_days)).run(
        a.control,a.framework,a.requirement,tuple(a.element),requirement_version_id=a.requirement_version)
    result={'acquisition_id':receipt['acquisition_id'],
            'scout_recommended_action':receipt['recommended_action'],
            'binding_status':receipt['evidence_binding_status'],
            'acquired_candidates':len(receipt['candidates'])}
    if receipt['recommended_action']!='REVIEW_CANDIDATES' or not receipt['candidates']:
        result['status']='EVIDENCE_REQUIRED';result['gaps']=receipt.get('gaps',[])
        print(json.dumps(result,indent=2));return 2
    dossier=EvidenceAssemblyAgent(source_ids,
        blobs=ImmutableBlobStore(ROOT/'governance'/'evidence_blobs'),
        dossiers=DossierStore()).assemble(receipt,assertion=a.assertion,
             required_elements=tuple(a.element))
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(render_markdown(dossier),encoding='utf-8')
    result['dossier_id']=dossier['dossier_id']
    result['anchors']=len(dossier['anchors'])
    result['scrutiny_questions']=len(dossier['challenge_surface'])
    result['dossier_path']=str(a.output) if a.output else None
    result['audit_package']=prepare_package(dossier=dossier,context=ReviewContext(risk_tier=a.risk_tier))
    result['status']=result['audit_package']['status']
    print(json.dumps(result,indent=2))
    return 2 if result['status']!='READY_FOR_HUMAN_REVIEW' else 0
if __name__=='__main__':raise SystemExit(main())
