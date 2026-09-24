#!/usr/bin/env python3
"""Read-only signed admission and bound-cycle verifier; never transitions a result."""
from __future__ import annotations
import argparse,base64,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.admission import AdmissionStore
from governance.evidence_scout.dossier import canonical,sha256,ImmutableBlobStore
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import events

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cycle-id',required=True)
    p.add_argument('--admission-ledger',type=Path)
    p.add_argument('--blob-root',type=Path)
    a=p.parse_args()
    rows=AdmissionStore(a.admission_ledger).read()
    prepared=[r['payload'] for r in rows if r['record_type']=='EvidenceAdmissionPrepared' and r['payload']['cycle_id']==a.cycle_id]
    committed=[r['payload'] for r in rows if r['record_type']=='EvidenceCycleBound' and r['payload']['cycle_id']==a.cycle_id]
    state=events.state(a.cycle_id)
    verdict={'cycle_id':a.cycle_id,'prepared':len(prepared),'committed':len(committed),
             'event_chain':events.verify()['intact'],'cycle_evidence_bound':bool(state.get('evidence')),
             'read_only':True,'results_created':0}
    good=len(prepared)==len(committed)==1 and verdict['event_chain'] and bool(state.get('evidence'))
    if good:
        ev=state['evidence'];pre=prepared[0];commit=committed[0]
        try:
            seal=pre['seal']
            Ed25519PublicKey.from_public_bytes(base64.b64decode(seal['public_key_b64'],validate=True)).verify(
                base64.b64decode(seal['signature'],validate=True),canonical({k:v for k,v in pre.items() if k!='seal'}))
            if sha256(canonical(ev))!=pre['bundle_hash'] or ev['evidence_set_id']!=commit['evidence_set_id']:
                raise ValueError('bound bundle mismatch')
            blobs=ImmutableBlobStore(a.blob_root or ROOT/'governance'/'evidence_blobs')
            for anchor in pre['evidence_items']:blobs.read(anchor['sha256'])
            verdict.update({'signature':'OK','blobs_verified':len(pre['evidence_items']),
                           'evidence_set_id':ev['evidence_set_id'],'binding':'AUTHORITATIVE_CYCLE_EVIDENCE'})
        except Exception as exc:
            verdict['error']=str(exc);good=False
    verdict['status']='PASS' if good else 'BLOCKED'
    print(json.dumps(verdict,indent=2));return 0 if good else 2
if __name__=='__main__':raise SystemExit(main())
