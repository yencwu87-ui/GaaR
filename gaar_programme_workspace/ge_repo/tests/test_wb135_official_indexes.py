from __future__ import annotations
import json
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import pytest
from governance.watcher.official_index import (OfficialIndexMonitor,IndexErrorSafe,parse_index,retrieve_index,scan_due)
from governance.watcher.asia_sources import retrieve_nfra_api

ROW=dict(source_id='MAS-test',enabled=True,url='https://www.mas.gov.sg/publications/consultations',approved_hosts=['www.mas.gov.sg'],path_prefixes=['/publications/consultations/'],interval_minutes=360)
NFRA_ROW=dict(source_id='NFRA-test',authority='NFRA',enabled=True,url='https://www.nfra.gov.cn/en/view/pages/ItemList.html',approved_hosts=['www.nfra.gov.cn'],path_prefixes=['/en/view/pages/ItemDetail.html'],interval_minutes=360,max_items=20)

def page(*links):
    return ('<html>'+''.join(f'<a href="{u}">{t}</a>' for u,t in links)+'</html>').encode()

class Response:
    def __init__(self,body=b'',status=200,content_type='text/html',location=None):
        self.content=body;self.status_code=status;self.headers={'Content-Type':content_type}
        if location:self.headers['Location']=location
    def raise_for_status(self):
        if self.status_code>=400:raise RuntimeError(f'HTTP {self.status_code}')

def api_response(rows,total=None,status=200,content_type='application/json'):
    body=json.dumps({'rptCode':200,'msg':'Success','data':{'total':len(rows) if total is None else total,'rows':rows}}).encode()
    return Response(body,status,content_type)

def nfra_doc(doc_id,title='NFRA rule',date='2026-01-01 00:00:00'):
    return {'docId':doc_id,'docTitle':title,'publishDate':date,'pdfFileUrl':f'/chinese/OFFICE/PDF/{doc_id}.pdf'}

def fake(body):return lambda u,**kw:Response(body)

def test_first_scan_baseline_second_no_update_then_new_link():
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        a=page(('/publications/consultations/a','Consultation A'))
        b=page(('/publications/consultations/a','Consultation A'),('/publications/consultations/b','Consultation B'))
        assert m.scan(ROW,get=fake(a))['status']=='BASELINE_ESTABLISHED'
        assert m.scan(ROW,get=fake(a))['status']=='UP_TO_DATE'
        last=m.scan(ROW,get=fake(b));assert last['status']=='UPDATES_AVAILABLE'
        assert len(last['new'])==1 and last['new'][0]['title']=='Consultation B'
        assert m.latest('MAS-test')['index_sha256']

def test_first_baseline_never_floods_existing_documents_as_new():
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        first=m.scan(ROW,get=fake(page(('/publications/consultations/a','Consultation A'))))
        assert first['status']=='BASELINE_ESTABLISHED' and first['new']==[] and first['changed_listing']==[]

def test_changed_title_is_not_verified_pdf_change():
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        m.scan(ROW,get=fake(page(('/publications/consultations/a','old title'))))
        row=m.scan(ROW,get=fake(page(('/publications/consultations/a','new title'))))
        assert len(row['changed_listing'])==1 and not row['new']
        assert row['coverage']=='bounded_HTML_publication_index_only'

def test_failures_not_no_update_and_last_success_kept():
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        m.scan(ROW,get=fake(page(('/publications/consultations/a','A'))))
        broken=m.scan(ROW,get=lambda *a,**k:Response(b'blocked',403))
        assert broken['status']=='UNABLE_TO_CHECK'
        assert m.latest('MAS-test',successful_only=True)['status']=='BASELINE_ESTABLISHED'
        assert m.status(ROW)['status']=='UNABLE_TO_CHECK'

def test_challenge_page_and_empty_rejected():
    for body in (b'<html>Cloudflare Turnstile</html>',b'<html><title>Maintenance</title></html>',b'<html>just home</html>',b''):
        with pytest.raises(IndexErrorSafe):parse_index(body,page_url=ROW['url'],approved_hosts=ROW['approved_hosts'],path_prefixes=ROW['path_prefixes'])

def test_nfra_api_baseline_then_update_and_bounded_pagination():
    calls=[]
    initial={1:[nfra_doc(i,f'Rule {i}') for i in range(1,19)],2:[nfra_doc(19,'Rule 19')]}
    def get_initial(url,**kwargs):
        page_no=kwargs['params']['pageIndex'];calls.append(page_no)
        return api_response(initial.get(page_no,[]),total=19)
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        first=m.scan(NFRA_ROW,get=get_initial)
        assert first['status']=='BASELINE_ESTABLISHED' and first['new']==[]
        assert first['coverage']=='bounded_official_JSON_API_only' and len(first['inventory'])==19
        assert calls==[1,2]
        calls.clear();assert m.scan(NFRA_ROW,get=get_initial)['status']=='UP_TO_DATE'
        assert calls==[1,2]
        changed={1:initial[1],2:[nfra_doc(19,'Rule 19'),nfra_doc(20,'New rule')]}
        def get_changed(url,**kwargs):return api_response(changed.get(kwargs['params']['pageIndex'],[]),total=20)
        update=m.scan(NFRA_ROW,get=get_changed)
        assert update['status']=='UPDATES_AVAILABLE' and [r['document_id'] for r in update['new']]==['20']

@pytest.mark.parametrize('response,match',[
    (Response(b'not-json',content_type='application/json'),'invalid NFRA API JSON'),
    (Response(b'{}',content_type='text/html'),'not JSON'),
    (api_response([],total=0),'no publications'),
])
def test_nfra_api_failures_are_fail_closed(response,match):
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        out=m.scan(NFRA_ROW,get=lambda *a,**k:response)
        assert out['status']=='UNABLE_TO_CHECK' and match in out['error']

def test_nfra_api_rejects_unapproved_endpoint_without_network():
    with pytest.raises(ValueError,match='unapproved'):
        retrieve_nfra_api({**NFRA_ROW,'api_url':'https://nfra.example.com/api'},get=lambda *a,**k:pytest.fail('network accessed'))

def test_offsite_links_and_lookalike_domain_excluded():
    doc=page(('https://www.mas.gov.sg.evil.com/publications/consultations/a','bad'),('/publications/consultations/good','Good'))
    out=parse_index(doc,page_url=ROW['url'],approved_hosts=ROW['approved_hosts'],path_prefixes=ROW['path_prefixes'])
    assert len(out)==1 and out[0]['title']=='Good'

def test_unapproved_redirect_fails():
    with pytest.raises(IndexErrorSafe):retrieve_index(ROW,get=lambda *a,**k:Response(status=302,location='https://bad.com/hijack'))

def test_disabled_status_and_no_network():
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        assert m.status({**ROW,'enabled':False})['status']=='NOT_CONFIGURED'
        assert m.scan({**ROW,'enabled':False},get=lambda *a,**k:pytest.fail('network accessed'))['status']=='UNABLE_TO_CHECK'

def test_scan_due_opt_in_gate(tmp_path,monkeypatch):
    monkeypatch.delenv('WB_GAAR_OFFICIAL_INDEX_ENABLED',raising=False)
    with pytest.raises(IndexErrorSafe,match='opt-in'):
        scan_due(manifest=tmp_path/'irrelevant.yaml')

def test_overdue_is_distinct():
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        m.scan(ROW,get=fake(page(('/publications/consultations/a','A'))))
        later=datetime.now(timezone.utc)+timedelta(days=3)
        assert m.status(ROW,now=later)['status']=='CHECK_OVERDUE'

def test_no_binding_reassessment_from_scan(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        m=OfficialIndexMonitor(Path(d)/'s.jsonl')
        r=m.scan(ROW,get=fake(page(('/publications/consultations/a','A'))))
        assert 'assessment_id' not in r and 'commit_id' not in r and 'governance_result' not in r
