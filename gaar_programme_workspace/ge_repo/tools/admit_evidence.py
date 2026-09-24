#!/usr/bin/env python3
"""WB-124 dossier admission preflight; --admit explicitly binds to an EXISTING cycle.

This local CLI identifies the claimed requester but is not an authenticated RBAC login.
Restrict filesystem/terminal access; human decisions and Quality Gate remain separate.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.admission import GovernedAdmissionService,AdmissionPolicy,AdmissionError
from governance.evidence_scout.dossier import ImmutableBlobStore

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dossier-id',required=True)
    p.add_argument('--cycle-id',required=True,help='An existing fresh cycle ID from core.cycle.start')
    p.add_argument('--actor-id',required=True,help='Named LOCAL OPERATOR, not verified identity')
    p.add_argument('--actor-type',choices=('human','service'),default='human')
    p.add_argument('--element',action='append',required=True,help='Exact required element as in dossier; repeat')
    p.add_argument('--max-age-days',type=int,default=90)
    p.add_argument('--blob-root',type=Path,help='Override immutable blob store root (isolated acceptance)')
    p.add_argument('--admit',action='store_true',help='Write signed admission and authoritative evidence-bound event')
    a=p.parse_args()
    service=GovernedAdmissionService(policy=AdmissionPolicy(max_age_days=a.max_age_days),
         blobs=ImmutableBlobStore(a.blob_root or ROOT/'governance'/'evidence_blobs'))
    try:
        outcome=service.admit(dossier_id=a.dossier_id,cycle_id=a.cycle_id,
            actor_id=a.actor_id,actor_type=a.actor_type,required_elements=tuple(a.element),dry_run=not a.admit)
        print(json.dumps(outcome,indent=2));return 0
    except (AdmissionError,ValueError,RuntimeError) as exc:
        print(json.dumps({'status':'ADMISSION_BLOCKED','reason':str(exc),
             'dossier_id':a.dossier_id,'cycle_id':a.cycle_id},indent=2));return 2
if __name__=='__main__':raise SystemExit(main())
