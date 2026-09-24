#!/usr/bin/env python3
"""Read-only live probe for HKMA BRDR HTML or the NFRA official publication API.
No Watcher state, quarantine, Git staging, assessment, or result files are written.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from governance.watcher.asia_sources import parse_hkma_brdr,retrieve_nfra_api

URLS={
 'HKMA':'https://brdr.hkma.gov.hk/eng/main',
 'NFRA':'https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild',
}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--authority',choices=tuple(URLS),required=True);p.add_argument('--url');p.add_argument('--limit',type=int,default=20);a=p.parse_args()
 url=a.url or URLS[a.authority]
 try:
  if a.authority=='HKMA':
   r=requests.get(url,timeout=25,headers={'User-Agent':'GaaR-RegulatoryWatcher/1.0 (read-only official publication probe)'});r.raise_for_status()
   final_url=r.url;rows=parse_hkma_brdr(r.content,page_url=final_url,limit=a.limit)
  else:
   _,final_url,rows=retrieve_nfra_api({'api_url':url,'max_items':a.limit},get=requests.get)
  print(json.dumps({'status':'OK','authority':a.authority,'requested_url':url,'final_url':final_url,'count':len(rows),'publications':rows},ensure_ascii=False,indent=2));return 0
 except Exception as exc:
  print(json.dumps({'status':'UNABLE_TO_CHECK','authority':a.authority,'url':url,'reason':str(exc)},ensure_ascii=False,indent=2),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
