import hashlib
import json
from pathlib import Path
from email.message import Message
import pytest
from governance.watcher.regulator_fetch import (fetch_bytes, approved_url, candidate_pdfs, record_receipt, Fetched, IntakeError)

class Response:
    def __init__(self,url,body,ctype='application/pdf'):
        self.url=url; self.body=body; self.headers=Message(); self.headers['Content-Type']=ctype
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def geturl(self): return self.url
    def read(self,n): return self.body[:n]
class Opener:
    def __init__(self,response): self.response=response
    def open(self,*args,**kwargs): return self.response
MAS='https://www.mas.gov.sg/regulation/notices/demo.pdf'
FCA='https://www.fca.org.uk/publication/policy/ps24-4.pdf'

def test_reject_bad_domain_and_userinfo():
    for url in ('http://www.mas.gov.sg/x.pdf','https://www.mas.gov.sg.evil/x.pdf',
                'https://evil@www.mas.gov.sg/x.pdf','https://www.mas.gov.sg:444/x.pdf'):
        assert not approved_url(url,'MAS')
        with pytest.raises(IntakeError): fetch_bytes(url,'MAS',opener=Opener(Response(url,b'%PDF-a')))

def test_raw_pdf_preserved_even_wrong_content_type():
    raw=b'%PDF-1.7\noriginal bytes\n'
    got=fetch_bytes(MAS,'MAS',opener=Opener(Response(MAS,raw,'application/octet-stream')))
    assert got.data==raw and got.content_type=='application/pdf'

def test_reject_redirect_outside_allowlist():
    with pytest.raises(IntakeError,match='outside official domain'):
        fetch_bytes(MAS,'MAS',opener=Opener(Response('https://cdn.evil.test/file.pdf',b'%PDF-x')))

def test_detect_challenge_and_bad_payload():
    with pytest.raises(IntakeError,match='DEGRADED'):
        fetch_bytes(MAS,'MAS',opener=Opener(Response(MAS,b'<html>Cloudflare Turnstile</html>','text/html')))
    with pytest.raises(IntakeError,match='INVALID_DOCUMENT'):
        fetch_bytes(MAS,'MAS',opener=Opener(Response(MAS,b'{"error":"forbidden"}','application/json')))

def test_size_cap():
    with pytest.raises(IntakeError,match='oversized'):
        fetch_bytes(MAS,'MAS',opener=Opener(Response(MAS,b'%PDF-'+b'a'*(12*1024*1024))))

def test_pdf_discovery_restricts_source_and_match():
    html='<a href="/publication/policy/ps24-4.pdf">Read</a><a href="https://evil.test/ps24-4.pdf">X</a><a href="/publication/policy/other.pdf">Y</a>'
    assert candidate_pdfs(html,'https://www.fca.org.uk/publications/x','FCA',match='ps24-4')==[FCA]

def test_receipt_preserves_binary_and_no_authority(tmp_path):
    raw=b'%PDF-1.4\ncompliance record'; got=Fetched(MAS,raw,'application/pdf','etag-1','Mon, 1 Jan 2024 00:00:00 GMT')
    receipt=record_receipt(tmp_path,'MAS',None,got,method='http_original_response')
    assert Path(receipt['source_file']).read_bytes()==raw
    assert receipt['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert not receipt['authority_verified'] and not receipt['signed_commit'] and not receipt['impact_review_queued']
    assert record_receipt(tmp_path,'MAS',None,got,method='http_original_response')['source_sha256']==receipt['source_sha256']

def test_tampered_local_intake_fails_closed(tmp_path):
    got=Fetched(MAS,b'%PDF-x','application/pdf',None,None)
    r=record_receipt(tmp_path,'MAS',None,got,method='http_original_response')
    Path(r['source_file']).write_bytes(b'tampered')
    with pytest.raises(IntakeError,match='does not match hash'): record_receipt(tmp_path,'MAS',None,got,method='http_original_response')

def test_landing_keeps_original_bytes(tmp_path):
    got=Fetched(FCA,b'%PDF-1','application/pdf',None,None)
    page=Fetched('https://www.fca.org.uk/publications/policy-statements/ps24-4',b'<html>original</html>','text/html',None,None)
    r=record_receipt(tmp_path,'FCA',page,got,method='http_original_response')
    assert (tmp_path/(r['landing_sha256']+'.landing.html')).read_bytes()==page.data
