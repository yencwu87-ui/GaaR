#!/usr/bin/env python3
"""WB-123 honest STP preparation; --run advances existing machine stages only."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.audit_package import ReviewContext, prepare_package
from governance.evidence_scout.dossier import DossierStore


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cycle-id')
    p.add_argument('--dossier-id')
    p.add_argument('--risk-tier',choices=['low','medium','high','critical','unknown'],default='unknown')
    p.add_argument('--not-first-assessment',action='store_true')
    p.add_argument('--admitted-evidence',action='store_true',help='Assert existing CYCLE evidence admitted by governed pipeline; never applies to a Scout dossier')
    p.add_argument('--freshness-verified',action='store_true')
    p.add_argument('--material-change',action='store_true')
    p.add_argument('--strong-challenge',action='store_true')
    p.add_argument('--governance-exception',action='store_true')
    p.add_argument('--confidence',type=float)
    p.add_argument('--run',action='store_true',help='Execute only existing Conductor machine steps; MAY WRITE review events / call LLM')
    p.add_argument('--dossier-ledger',type=Path)
    args=p.parse_args()
    if not args.cycle_id and not args.dossier_id:p.error('--cycle-id or --dossier-id required')
    if args.run and not args.cycle_id:p.error('--run requires --cycle-id')
    dossier=None
    if args.dossier_id:
        hits=[r['payload'] for r in DossierStore(args.dossier_ledger).read() if r['payload'].get('dossier_id')==args.dossier_id]
        if len(hits)!=1:p.error('expected exactly one dossier ID')
        dossier=hits[0]
    context=ReviewContext(risk_tier=args.risk_tier,first_assessment=not args.not_first_assessment,
        admitted_evidence=args.admitted_evidence and not dossier,
        freshness_verified=args.freshness_verified and not dossier,
        material_change=args.material_change,unresolved_strong_challenge=args.strong_challenge,
        governance_exception=args.governance_exception,assessment_confidence=args.confidence)
    result=prepare_package(cycle_id=args.cycle_id,dossier=dossier,context=context,
                           run_machine_steps=args.run)
    print(json.dumps(result,indent=2,default=str))
    return 0 if result['status']=='READY_FOR_HUMAN_REVIEW' else 2
if __name__=='__main__':raise SystemExit(main())
