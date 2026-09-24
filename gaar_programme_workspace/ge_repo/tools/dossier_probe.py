#!/usr/bin/env python3
"""Read-only WB-122 dossier chain/hash/blob proof; does not admit evidence."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.evidence_scout.dossier import DossierStore,ImmutableBlobStore,canonical,sha256

def main():
    p=argparse.ArgumentParser();p.add_argument('--dossier-ledger',type=Path)
    p.add_argument('--blob-root',type=Path);args=p.parse_args()
    dossiers=DossierStore(args.dossier_ledger).read()
    blobs=ImmutableBlobStore(args.blob_root or ROOT/'governance'/'evidence_blobs')
    count=0
    for row in dossiers:
        payload=dict(row['payload']);claimed=payload.pop('content_hash')
        if sha256(canonical(payload))!=claimed:raise ValueError('dossier hash mismatch')
        if payload['binding_status']!='PROPOSED_ONLY':raise ValueError('unexpected dossier binding')
        for anchor in payload['anchors']:
            blobs.read(anchor['content_hash']);count+=1
    print(json.dumps({'ledger_chain':'OK','dossiers':len(dossiers),'anchors_verified':count,
                      'binding':'PROPOSED_ONLY'},indent=2))
if __name__=='__main__':main()
