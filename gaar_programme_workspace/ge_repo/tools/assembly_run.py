#!/usr/bin/env python3
"""Build a PROPOSED_ONLY evidence dossier from an existing WB-120R acquisition receipt."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from governance.evidence_scout.refresh import AcquisitionStore
from governance.evidence_scout.dossier import DossierStore, EvidenceAssemblyAgent, ImmutableBlobStore, render_markdown

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--acquisition-id',required=True)
    p.add_argument('--source',action='append',required=True,help='Approved source mapping source_id=/absolute/path (repeatable)')
    p.add_argument('--assertion',required=True)
    p.add_argument('--element',action='append',default=[])
    p.add_argument('--template',default='threshold_approval')
    p.add_argument('--acquisition-ledger',type=Path)
    p.add_argument('--dossier-ledger',type=Path)
    p.add_argument('--blob-root',type=Path)
    p.add_argument('--output',type=Path,help='Optional Markdown dossier file')
    args=p.parse_args()
    sources={}
    for item in args.source:
        if '=' not in item: p.error('--source requires source_id=/absolute/path')
        key, value=item.split('=',1)
        if not key or not Path(value).is_absolute(): p.error('source_id and absolute path required')
        if key in sources: p.error('duplicate source ID')
        sources[key]=value
    rows=AcquisitionStore(args.acquisition_ledger).read()
    found=[row['payload'] for row in rows if row['payload'].get('acquisition_id')==args.acquisition_id]
    if len(found)!=1: p.error('expected exactly one matching acquisition receipt')
    result=EvidenceAssemblyAgent(sources,
        blobs=ImmutableBlobStore(args.blob_root or ROOT/'governance'/'evidence_blobs'),
        dossiers=DossierStore(args.dossier_ledger)).assemble(found[0],
            assertion=args.assertion,required_elements=tuple(args.element),template=args.template)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(render_markdown(result),encoding='utf-8')
    print(json.dumps({'dossier_id':result['dossier_id'],'content_hash':result['content_hash'],
        'binding_status':result['binding_status'],'anchors':len(result['anchors']),
        'challenge_points':len(result['challenge_surface']),'gaps':result['gaps'],
        'dossier_ledger':str((args.dossier_ledger or ROOT/'governance'/'evidence_dossiers.jsonl').resolve()),
        'markdown':str(args.output) if args.output else None},indent=2))

if __name__=='__main__':main()
