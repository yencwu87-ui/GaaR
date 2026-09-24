#!/usr/bin/env python3
"""Fetch an official MAS/FCA/HKMA/NFRA document into QUARANTINE; no automatic Git commit/push.

Examples:
 python tools/regulator_fetch.py --regulator MAS --url https://www.mas.gov.sg/...pdf
 python tools/regulator_fetch.py --regulator FCA --landing https://www.fca.org.uk/publications/... --pdf-match ps24-4
For JS-heavy landing pages add --browser; installs Playwright separately.
"""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from governance.watcher.regulator_fetch import (fetch_bytes, browser_landing, candidate_pdfs,
                                                  record_receipt, Fetched, IntakeError)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--regulator',required=True,choices=['MAS','FCA','HKMA','NFRA'])
    ap.add_argument('--url',help='exact official PDF/HTML document URL')
    ap.add_argument('--landing',help='official HTML publication landing page')
    ap.add_argument('--pdf-match',default='',help='required substring to select PDF candidate')
    ap.add_argument('--browser',action='store_true',help='use Playwright for JS-rendered link discovery only')
    ap.add_argument('--output',default=str(ROOT/'governance'/'regulator_intake'))
    ap.add_argument('--convert-txt',action='store_true',help='extract searchable TXT derivative into instruments/regulatory after verified quarantine')
    ap.add_argument('--instrument-id',help='stable instrument identifier for --convert-txt')
    ap.add_argument('--instrument-title',default='',help='display title for TXT derivative')
    ap.add_argument('--instruments',type=Path,default=ROOT/'instruments')
    ap.add_argument('--stage',action='store_true',help='explicit ADD only; requires all --stage-* metadata; never COMMIT/PUSH')
    ap.add_argument('--config',help='enabled, operator-approved Watcher registry YAML for --stage')
    for flag in ('source-id','document-id','title','published-at','document-class','lifecycle',
                 'assessment','framework','control','actor','reason','attestation'):
        ap.add_argument('--stage-'+flag)

    args=ap.parse_args()
    if bool(args.url)==bool(args.landing): ap.error('specify exactly one of --url or --landing')
    try:
        landing=None
        if args.landing:
            if args.browser:
                raw, final, links=browser_landing(args.landing,args.regulator)
                landing=Fetched(final,raw,'text/html',None,None)
                urls=sorted({x for x in links if x.lower().split('?')[0].endswith('.pdf') and args.pdf_match.lower() in x.lower()})
            else:
                landing=fetch_bytes(args.landing,args.regulator)
                if landing.content_type!='text/html': raise IntakeError('landing page is not HTML')
                urls=candidate_pdfs(landing.data.decode('utf-8','replace'),landing.url,args.regulator,match=args.pdf_match)
            if len(urls)!=1:
                raise IntakeError(f'PDF selection ambiguous ({len(urls)} candidates). Use --pdf-match or an exact --url; no guessing.')
            doc=fetch_bytes(urls[0],args.regulator)
            if doc.content_type!='application/pdf': raise IntakeError('INVALID_DOCUMENT: target was not an original PDF')
        else:
            doc=fetch_bytes(args.url,args.regulator)
        receipt=record_receipt(Path(args.output),args.regulator,landing,doc,method='browser_landing_http_document' if args.browser else 'http_original_response')
        if args.convert_txt:
            if not args.instrument_id: raise IntakeError('--convert-txt requires --instrument-id')
            from governance.watcher.instrument_conversion import convert_receipt,ConversionError
            rp=Path(args.output)/(receipt['source_sha256']+'.receipt.json')
            converted=convert_receipt(rp,args.instruments,instrument_id=args.instrument_id,title=args.instrument_title,regulator=args.regulator)
            receipt['text_derivative']=converted
        if args.stage:
            required=('source_id','document_id','title','published_at','document_class','lifecycle',
                      'assessment','framework','control','actor','reason','attestation')
            missing=[x for x in required if not getattr(args,'stage_'+x)]
            if missing or not args.config or not landing and not args.url:
                raise IntakeError('STAGE requires --config and all --stage-* metadata: '+', '.join(missing))
            from governance.watcher.gitflow import WatcherGitflow, WatcherGitError
            from governance.watcher.policy import load_sources
            reg=load_sources(args.config)
            if not reg: raise IntakeError('No enabled, approved sources in --config')
            flow=WatcherGitflow(registry=reg)
            stage=flow.add_file(source_id=args.stage_source_id,file=receipt['source_file'],
                document_id=args.stage_document_id,source_url=receipt['document_url'],
                landing_url=receipt['landing_url'] or receipt['document_url'],
                title=args.stage_title,issuer=args.regulator,published_at=args.stage_published_at,
                doc_class=args.stage_document_class,lifecycle=args.stage_lifecycle,
                assessment_id=args.stage_assessment,controls=(args.stage_control,),
                framework=args.stage_framework,actor=args.stage_actor,
                rationale=args.stage_reason,origin_attestation=args.stage_attestation)
            receipt['stage_id']=stage['stage_id']
            receipt['state']='STAGED_NOT_COMMITTED_NOT_PUSHED'
        print(json.dumps(receipt,indent=2)); return 0
    except (IntakeError, ValueError, OSError) as exc:
        print(json.dumps({'status':'DEGRADED_OR_BLOCKED','reason':str(exc)}),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
