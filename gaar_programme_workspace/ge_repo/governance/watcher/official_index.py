"""WB-135/136: opt-in, bounded official publication-index observation.

Observes validated HTML indexes or an authority-specific official JSON index. It does
NOT download, classify for legal applicability, or attest full instruments.
First successful scan establishes a baseline. A failed/empty/blocked fetch is NEVER no-update.
Existing governance basis and ISO document intake are independent of this sensor.
"""
from __future__ import annotations
import hashlib, json, os, re, uuid
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests, yaml
from .store import HashChainStore
from .models import utcnow

DEFAULT_MANIFEST=Path(__file__).resolve().parents[2]/'config'/'official_publication_indexes.yaml'

class IndexErrorSafe(ValueError): pass

def safe_url(url: str, hosts: list[str]|tuple[str,...]) -> bool:
    try:
        p=urlparse(url)
        return p.scheme=='https' and p.hostname in hosts and p.port in (None,443) and not p.username and not p.password and not p.fragment
    except ValueError: return False

class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.links=[];self.href=None;self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a' and self.href is None:
            self.href=dict(attrs).get('href');self.text=[]
    def handle_data(self,data):
        if self.href is not None:self.text.append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.href is not None:
            self.links.append((self.href,' '.join(' '.join(self.text).split())))
            self.href=None;self.text=[]

def parse_index(html: bytes,*,page_url:str,approved_hosts:list[str],path_prefixes:list[str],limit:int=100)->list[dict]:
    if not html or len(html)>5*1024*1024:raise IndexErrorSafe('empty or oversized publication index')
    if re.search(rb'(cloudflare|captcha|turnstile|access denied|service unavailable|<title[^>]*>\s*maintenance\b|temporarily unavailable)', html[:40000], re.I):
        raise IndexErrorSafe('challenge or maintenance page; not a successful scan')
    parser=_Links();parser.feed(html.decode('utf-8',errors='replace'))
    results={}
    for href,title in parser.links:
        if not href or not title:continue
        url=urljoin(page_url,href).split('#',1)[0]
        if not safe_url(url,approved_hosts):continue
        path=urlparse(url).path
        if not any(path.startswith(prefix) for prefix in path_prefixes):continue
        if url.rstrip('/')==page_url.rstrip('/'):continue
        if url not in results:results[url]={'url':url,'title':title[:400]}
        if len(results)>=limit:break
    if not results:raise IndexErrorSafe('no qualifying official publication links; coverage unverified')
    return sorted(results.values(),key=lambda r:r['url'])

def retrieve_index(row:dict,*,get=None)->tuple[bytes,str]:
    """Validate every redirect, enforce host allowlist and HTTP error handling."""
    get=get or requests.get
    hosts=list(row['approved_hosts']);url=str(row['url'])
    for _ in range(6):
        if not safe_url(url,hosts):raise IndexErrorSafe('unapproved source/redirect URL')
        response=get(url,timeout=20,allow_redirects=False,headers={'User-Agent':'GaaR-RegulatoryWatcher/1.0 (official publication index)'})
        if response.status_code in (301,302,303,307,308):
            dest=response.headers.get('Location')
            if not dest:raise IndexErrorSafe('redirect without Location')
            url=urljoin(url,dest);continue
        response.raise_for_status()
        ctype=str(response.headers.get('Content-Type','')).lower()
        if 'text/html' not in ctype:raise IndexErrorSafe('index response is not HTML')
        body=response.content
        if not body:raise IndexErrorSafe('empty index response')
        return body,url
    raise IndexErrorSafe('too many redirects')

class OfficialIndexMonitor:
    def __init__(self,path:Path|str|None=None):
        self.store=HashChainStore(path or os.environ.get('WB_GAAR_OFFICIAL_INDEX_STORE') or Path(__file__).resolve().parents[1]/'watcher_official_indexes.jsonl','gaar.official-index.v1')
    def latest(self,source_id:str,*,successful_only=False):
        rows=[r['payload'] for r in self.store.read() if r['payload']['source_id']==source_id and (not successful_only or r['payload']['status'] in ('BASELINE_ESTABLISHED','UP_TO_DATE','UPDATES_AVAILABLE'))]
        return rows[-1] if rows else None
    def scan(self,row:dict,*,get=None):
        sid=str(row['source_id']);before=self.latest(sid,successful_only=True)
        try:
            if not row.get('enabled'):raise IndexErrorSafe('source not enabled')
            authority=str(row.get('authority') or '').upper()
            if authority=='NFRA':
                from .asia_sources import retrieve_nfra_api
                body,final_url,items=retrieve_nfra_api(row,get=get)
                coverage='bounded_official_JSON_API_only'
            else:
                body,final_url=retrieve_index(row,get=get)
                items=parse_index(body,page_url=final_url,approved_hosts=row['approved_hosts'],path_prefixes=row['path_prefixes'],limit=int(row.get('max_items',100)))
                coverage='bounded_HTML_publication_index_only'
                # HKMA enrichment is review-only; the validated generic parser remains authoritative.
                if authority=='HKMA':
                    try:
                        from .asia_sources import parse_hkma_brdr
                        items=parse_hkma_brdr(body,page_url=final_url,limit=int(row.get('max_items',100)))
                    except Exception:
                        pass
            current={r['url']:r['title'] for r in items}
            previous=before['inventory'] if before else {}
            new=[] if before is None else [r for r in items if r['url'] not in previous]
            changed=[] if before is None else [r for r in items if r['url'] in previous and previous[r['url']]!=r['title']]
            status='BASELINE_ESTABLISHED' if before is None else 'UPDATES_AVAILABLE' if new or changed else 'UP_TO_DATE'
            payload={'source_id':sid,'status':status,'checked_at':utcnow(),'final_url':final_url,
                     'index_sha256':hashlib.sha256(body).hexdigest(),'inventory':current,
                     'new':new,'changed_listing':changed,'not_seen_on_current_page':[] if before is None else sorted(set(previous)-set(current)),
                     'coverage':coverage,'error':None}
        except Exception as exc:
            payload={'source_id':sid,'status':'UNABLE_TO_CHECK','checked_at':utcnow(),'error':str(exc),
                     'coverage':'unverified','last_successful_check':before['checked_at'] if before else None}
        self.store.append('OfficialIndexScan',payload)
        return payload
    def status(self,row:dict,*,now:datetime|None=None):
        if not row.get('enabled'):return {'source_id':row['source_id'],'status':'NOT_CONFIGURED'}
        last=self.latest(row['source_id'])
        if not last:return {'source_id':row['source_id'],'status':'NEVER_CHECKED'}
        if last['status']=='UNABLE_TO_CHECK':return last
        checked=datetime.fromisoformat(last['checked_at'].replace('Z','+00:00'))
        if (now or datetime.now(timezone.utc))-checked>timedelta(minutes=2*int(row.get('interval_minutes',360))):
            return {**last,'status':'CHECK_OVERDUE'}
        return last

def load_manifest(path=None):
    manifest=Path(path or os.environ.get('WB_GAAR_OFFICIAL_INDEX_CONFIG') or DEFAULT_MANIFEST)
    raw=yaml.safe_load(manifest.read_text(encoding='utf-8')) or {}
    return list(raw.get('sources') or [])

def scan_due(*,manifest=None,monitor=None,force=False,get=None):
    if os.environ.get('WB_GAAR_OFFICIAL_INDEX_ENABLED')!='1' and not force:
        raise IndexErrorSafe('Official monitoring is opt-in; set WB_GAAR_OFFICIAL_INDEX_ENABLED=1')
    monitor=monitor or OfficialIndexMonitor();out=[]
    for row in load_manifest(manifest):
        if not row.get('enabled'):
            out.append({'source_id':row['source_id'],'status':'NOT_CONFIGURED'});continue
        last=monitor.latest(row['source_id'])
        if last and not force and last['status']!='UNABLE_TO_CHECK':
            t=datetime.fromisoformat(last['checked_at'].replace('Z','+00:00'))
            if datetime.now(timezone.utc)-t<timedelta(minutes=int(row.get('interval_minutes',360))):
                out.append({**last,'skipped_not_due':True});continue
        out.append(monitor.scan(row,get=get))
    return out
