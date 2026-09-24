#!/usr/bin/env python3
"""Explicitly create a FRESH legacy review cycle for a governed admission; writes one start event."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from core import cycle

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control',required=True,help='EXACT control ID from the currently loaded playbook')
    p.add_argument('--framework',required=True)
    p.add_argument('--requirement-version',required=True)
    p.add_argument('--actor',required=True,help='Identified local operator (not authenticated RBAC)')
    p.add_argument('--risk-tier',choices=('unknown','low','medium','high','critical'),
                   help='Governed risk classification (operator attribution only; validate independently)')
    p.add_argument('--assessment-confidence',type=float,
                   help='Governed assessment confidence [0,1], do not invent')
    p.add_argument('--assert-no-material-change',action='store_true')
    p.add_argument('--assert-no-evidence-contradiction',action='store_true')
    p.add_argument('--assert-no-unresolved-strong-challenge',action='store_true')
    p.add_argument('--assert-no-quality-blocker',action='store_true')
    p.add_argument('--assert-no-governance-exception',action='store_true')
    p.add_argument('--assert-no-independent-review-required',action='store_true')
    args=p.parse_args()
    if args.assessment_confidence is not None and not 0<=args.assessment_confidence<=1:
        p.error('--assessment-confidence must be within [0,1]')
    context={'requirement_version_id':args.requirement_version}
    if args.risk_tier:context['risk_tier']=args.risk_tier
    if args.assessment_confidence is not None:context['assessment_confidence']=args.assessment_confidence
    for cli,field in (('assert_no_material_change','material_change'),
                      ('assert_no_evidence_contradiction','evidence_contradiction'),
                      ('assert_no_unresolved_strong_challenge','unresolved_strong_challenge'),
                      ('assert_no_quality_blocker','quality_blocked'),
                      ('assert_no_governance_exception','governance_exception'),
                      ('assert_no_independent_review_required','independent_review_required')):
        if getattr(args,cli):context[field]=False
    cid=cycle.start(args.control,framework=args.framework,actor=args.actor,
        governance_context=context)
    print(json.dumps({'status':'CYCLE_STARTED','cycle_id':cid,'control_id':args.control,
        'framework':args.framework,'requirement_version_id':args.requirement_version,
        'risk_context':context,'risk_context_origin':'LOCAL_OPERATOR_ASSERTION_NOT_RBAC'},indent=2))
if __name__=='__main__':main()
