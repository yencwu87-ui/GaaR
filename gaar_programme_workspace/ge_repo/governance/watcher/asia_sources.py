"""WB-136: Asia official-publication parsing helpers.

These adapters parse bounded official HTML indexes and the official NFRA JSON index.
They do not determine legal
applicability and never write governance results. HKMA BRDR and NFRA sources remain
opt-in until a deployment validates their page structure and network access.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse
import requests
from .update_centre import domain_suggestions

HKMA_HOSTS={"brdr.hkma.gov.hk"}
NFRA_HOSTS={"www.nfra.gov.cn","nfra.gov.cn","big5.nfra.gov.cn"}
NFRA_API_URL="https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
NFRA_DETAIL_URL="https://www.nfra.gov.cn/en/view/pages/ItemDetail.html"
NFRA_DEFAULT_ITEM_ID=981
NFRA_PAGE_SIZE=18
NFRA_MAX_ITEMS=100

@dataclass(frozen=True)
class PublicationCandidate:
    authority: str
    jurisdiction: str
    title: str
    url: str
    publication_category: str
    language: str
    lifecycle: str
    domains: tuple[str,...]
    source_scope: str

    def to_dict(self):
        row=asdict(self);row['domains']=list(self.domains);return row

class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.current=None;self.text=[];self.rows=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            href=dict(attrs).get('href')
            if href:self.current=href;self.text=[]
    def handle_data(self,data):
        if self.current is not None:self.text.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=='a' and self.current is not None:
            title=' '.join(' '.join(self.text).split())
            self.rows.append((self.current,title));self.current=None;self.text=[]

def _category_from_hkma(title:str,url:str)->str:
    up=title.upper()
    if 'CONSULT' in up or '/CPR' in up:return 'consultation'
    if 'GUIDELINE' in up:return 'guideline'
    if 'CODE OF PRACTICE' in up:return 'code_of_practice'
    return 'circular_or_regulatory_document'

def parse_hkma_brdr(html:bytes|str,*,page_url:str='https://brdr.hkma.gov.hk/eng/main',limit:int=100)->list[dict]:
    raw=html.decode('utf-8','replace') if isinstance(html,bytes) else html
    if re.search(r'(captcha|access denied|service unavailable)',raw[:40000],re.I):
        raise ValueError('HKMA index challenged/unavailable')
    p=_AnchorParser();p.feed(raw)
    out={}
    for href,title in p.rows:
        if not title:continue
        url=urljoin(page_url,href).split('#',1)[0]
        u=urlparse(url)
        if u.scheme!='https' or u.hostname not in HKMA_HOSTS:continue
        if not u.path.startswith(('/eng/doc-ldg/current/','/eng/doc-ldg/docId/',)):continue
        docid=u.path.rsplit('/',1)[-1]
        language='English' if docid.endswith('-EN') else 'Chinese/Other'
        lifecycle='consultation' if 'consult' in title.lower() else 'classification_pending'
        cand=PublicationCandidate('HKMA','Hong Kong',title,url,_category_from_hkma(title,url),language,lifecycle,
                                  tuple(domain_suggestions(title)),'HKMA BRDR bounded listing')
        out[url]=cand.to_dict()
        if len(out)>=limit:break
    if not out:raise ValueError('no HKMA BRDR document candidates found')
    return list(out.values())

def _nfra_language(url:str,title:str)->str:
    if '/cn/' in url:return 'Simplified Chinese'
    if '/en/' in url:return 'English'
    if re.search(r'[\u4e00-\u9fff]',title):return 'Simplified Chinese'
    return 'Unknown'

def _nfra_category(title:str,url:str)->str:
    low=title.lower()
    if '草案' in title or ('征求' in title and '意见' in title):return 'consultation_or_draft'
    if any(k in low for k in ('consultation','draft for comment','draft for comments','solicits public opinion','solicits public opinions')):return 'consultation_or_draft'
    if any(k in title for k in ('指导意见','指引')):return 'guidance'
    if any(k in low for k in ('guidance','guideline','guiding opinion')):return 'guidance'
    if any(k in title for k in ('通知','公告')):return 'notice_or_announcement'
    if any(k in low for k in ('notice','announcement')):return 'notice_or_announcement'
    if '/rulesDetail.html' in url or '规章' in title:return 'rule'
    if any(k in low for k in (' rules',' rules for','measures for','provisions on','regulation')):return 'rule'
    return 'policy_or_regulatory_publication'

def _positive_int(value,field:str)->int:
    if isinstance(value,bool):raise ValueError(f'NFRA {field} must be a positive integer')
    try: parsed=int(value)
    except (TypeError,ValueError) as exc:raise ValueError(f'NFRA {field} must be a positive integer') from exc
    if parsed<=0:raise ValueError(f'NFRA {field} must be a positive integer')
    return parsed

def parse_nfra_api(payload:dict,*,item_id:int=NFRA_DEFAULT_ITEM_ID,limit:int=NFRA_MAX_ITEMS)->list[dict]:
    """Validate one official NFRA API page and return review-only candidates."""
    if not isinstance(payload,dict) or payload.get('rptCode')!=200:
        raise ValueError('NFRA API response is not successful')
    data=payload.get('data')
    if not isinstance(data,dict) or not isinstance(data.get('rows'),list):
        raise ValueError('NFRA API response has no rows list')
    item_id=_positive_int(item_id,'itemId')
    bounded=max(1,min(_positive_int(limit,'limit'),NFRA_MAX_ITEMS))
    out={}
    for row in data['rows'][:bounded]:
        if not isinstance(row,dict):raise ValueError('NFRA API row is not an object')
        doc_id=_positive_int(row.get('docId'),'docId')
        title=' '.join(str(row.get('docTitle') or row.get('docSubtitle') or '').split())
        published=' '.join(str(row.get('publishDate') or '').split())
        if not title:raise ValueError('NFRA API row has no title')
        if not published:raise ValueError('NFRA API row has no publication date')
        if not re.match(r'^\d{4}-\d{2}-\d{2}(?:[ T].*)?$',published):raise ValueError('NFRA API row has an invalid publication date')
        supplied_item=row.get('itemId')
        if supplied_item not in (None,'') and _positive_int(supplied_item,'row itemId')!=item_id:
            raise ValueError('NFRA API row itemId does not match the requested index')
        detail=f'{NFRA_DETAIL_URL}?{urlencode({"docId":doc_id,"itemId":item_id})}'
        title_link_raw=str(row.get('titleLink') or '')
        title_link=urljoin('https://www.nfra.gov.cn/',title_link_raw) if title_link_raw else None
        if title_link and (urlparse(title_link).scheme!='https' or urlparse(title_link).hostname not in NFRA_HOSTS):
            raise ValueError('NFRA API row has an unapproved title link')
        pdf_raw=str(row.get('pdfFileUrl') or '')
        pdf_url=urljoin('https://www.nfra.gov.cn/',pdf_raw) if pdf_raw else None
        if pdf_url and (urlparse(pdf_url).scheme!='https' or urlparse(pdf_url).hostname not in NFRA_HOSTS):
            raise ValueError('NFRA API row has an unapproved PDF URL')
        lifecycle='consultation' if _nfra_category(title,detail)=='consultation_or_draft' else 'classification_pending'
        cand=PublicationCandidate('NFRA','China',title[:400],detail,_nfra_category(title,detail),'English',lifecycle,
                                  tuple(domain_suggestions(title)),'NFRA bounded official JSON API')
        item=cand.to_dict();item['published_at']=published;item['document_id']=str(doc_id);item['pdf_url']=pdf_url;item['official_title_link']=title_link
        out[detail]=item
    return list(out.values())

def retrieve_nfra_api(row:dict,*,get=None)->tuple[bytes,str,list[dict]]:
    """Retrieve bounded NFRA JSON pages with strict schema and origin validation."""
    get=get or requests.get
    endpoint=str(row.get('api_url') or NFRA_API_URL)
    parsed=urlparse(endpoint)
    if parsed.scheme!='https' or parsed.hostname not in NFRA_HOSTS or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('unapproved NFRA API URL')
    item_id=_positive_int(row.get('item_id',NFRA_DEFAULT_ITEM_ID),'itemId')
    limit=max(1,min(_positive_int(row.get('max_items',NFRA_MAX_ITEMS),'max_items'),NFRA_MAX_ITEMS))
    pages=[];items=[];seen=set();page_index=1
    while len(items)<limit:
        response=get(endpoint,params={'itemId':item_id,'pageSize':NFRA_PAGE_SIZE,'pageIndex':page_index},timeout=20,
                     allow_redirects=False,headers={'User-Agent':'GaaR-RegulatoryWatcher/1.0 (official NFRA publication API)','Accept':'application/json'})
        if getattr(response,'status_code',None) in (301,302,303,307,308):raise ValueError('NFRA API redirect rejected')
        response.raise_for_status()
        ctype=str(response.headers.get('Content-Type','')).lower()
        if 'application/json' not in ctype:raise ValueError('NFRA API response is not JSON')
        body=response.content
        if not body or len(body)>2*1024*1024:raise ValueError('empty or oversized NFRA API response')
        try:payload=json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise ValueError('invalid NFRA API JSON') from exc
        page_items=parse_nfra_api(payload,item_id=item_id,limit=min(NFRA_PAGE_SIZE,limit-len(items)))
        if page_index==1 and not page_items:raise ValueError('NFRA API returned no publications')
        fresh=[item for item in page_items if item['url'] not in seen]
        if page_index>1 and page_items and not fresh:raise ValueError('NFRA API pagination repeated a page')
        pages.append(payload);items.extend(fresh);seen.update(item['url'] for item in fresh)
        total=payload.get('data',{}).get('total')
        if isinstance(total,bool) or not isinstance(total,int) or total<0:raise ValueError('NFRA API total is invalid')
        if not page_items or len(items)>=limit or len(items)>=total:break
        page_index+=1
    canonical=json.dumps({'endpoint':endpoint,'item_id':item_id,'pages':pages},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return canonical,endpoint,items[:limit]

def parse_nfra_index(html:bytes|str,*,page_url:str='https://www.nfra.gov.cn/cn/view/pages/zhengwuxinxi/zhengfuxinxi.html',limit:int=100)->list[dict]:
    raw=html.decode('utf-8','replace') if isinstance(html,bytes) else html
    if re.search(r'(captcha|access denied|service unavailable)',raw[:40000],re.I):
        raise ValueError('NFRA index challenged/unavailable')
    p=_AnchorParser();p.feed(raw)
    out={}
    for href,title in p.rows:
        if not title:continue
        url=urljoin(page_url,href).split('#',1)[0]
        u=urlparse(url)
        if u.scheme!='https' or u.hostname not in NFRA_HOSTS:continue
        if not (u.path.endswith('/ItemDetail.html') or u.path.endswith('/rulesDetail.html')):continue
        if 'docId=' not in u.query:continue
        language=_nfra_language(url,title)
        lifecycle='consultation' if ('草案' in title or ('征求' in title and '意见' in title)) else 'classification_pending'
        cand=PublicationCandidate('NFRA','China',title,url,_nfra_category(title,url),language,lifecycle,
                                  tuple(domain_suggestions(title)),'NFRA bounded policy/rules listing')
        out[url]=cand.to_dict()
        if len(out)>=limit:break
    if not out:raise ValueError('no NFRA regulatory publication candidates found')
    return list(out.values())
