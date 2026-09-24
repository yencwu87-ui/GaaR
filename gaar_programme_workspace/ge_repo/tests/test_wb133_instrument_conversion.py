import hashlib, json
from pathlib import Path
import pytest
from governance.watcher.regulator_fetch import Fetched, record_receipt
from governance.watcher.instrument_conversion import convert_receipt, import_local_pdf, ConversionError

MAS='https://www.mas.gov.sg/regulation/notices/example.pdf'

def pdf_bytes(text='Notice on technology risk management. The institution shall retain approval records for review.'):
    fitz = pytest.importorskip("fitz", reason="PyMuPDF is optional; PDF conversion tests need it")
    d=fitz.open(); page=d.new_page();page.insert_text((54,65),text)
    content=d.tobytes();d.close();return content

def make_receipt(tmp_path,raw=None,kind='application/pdf'):
    b=raw if raw is not None else pdf_bytes()
    f=Fetched(MAS,b,kind,None,None)
    r=record_receipt(tmp_path/'intake','MAS',None,f,method='http_original_response')
    return tmp_path/'intake'/(r['source_sha256']+'.receipt.json'),r

def test_original_is_unchanged_and_txt_versioned(tmp_path):
    rp,r=make_receipt(tmp_path)
    out=convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST',title='Example')
    assert Path(r['source_file']).read_bytes().startswith(b'%PDF-')
    assert hashlib.sha256(Path(r['source_file']).read_bytes()).hexdigest()==r['source_sha256']
    txt=Path(out['text_file']).read_text();assert 'SOURCE PAGE 1' in txt
    assert 'approval records' in txt and 'NOT AN OFFICIAL SOURCE' in txt
    assert out['not_authoritative'] and out['classification_review_required']
    assert out['source_sha256'] in out['text_file']
    assert convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST',title='Example')['text_sha256']==out['text_sha256']

def test_different_originals_different_versions(tmp_path):
    rp,_=make_receipt(tmp_path/'a',pdf_bytes('First version of regulatory notice with approval record monitoring requirements.'))
    rp2,_=make_receipt(tmp_path/'a',pdf_bytes('Second revised regulatory notice with new approval record monitoring requirements.'))
    a=convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST')
    b=convert_receipt(rp2,tmp_path/'instruments',instrument_id='MAS-TEST')
    assert a['source_sha256']!=b['source_sha256']
    assert Path(a['text_file']).exists() and Path(b['text_file']).exists()

def test_source_tamper_rejected(tmp_path):
    rp,r=make_receipt(tmp_path)
    Path(r['source_file']).write_bytes(pdf_bytes('Altered records are different and must fail conversion verification.'))
    with pytest.raises(ConversionError,match='SOURCE_HASH_MISMATCH'):
        convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST')

def test_filename_traversal_rejected(tmp_path):
    rp,_=make_receipt(tmp_path)
    with pytest.raises(ConversionError,match='instrument identifier'):
        convert_receipt(rp,tmp_path/'instruments',instrument_id='../../outside')

def test_scanned_pdf_fail_closed(tmp_path):
    fitz = pytest.importorskip("fitz", reason="PyMuPDF is optional; PDF conversion tests need it")
    d=fitz.open();d.new_page();raw=d.tobytes();d.close()
    rp,_=make_receipt(tmp_path,raw)
    with pytest.raises(ConversionError,match='TEXT_EXTRACTION_INCOMPLETE'):
        convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-SCAN')

def test_local_pdf_is_never_labeled_live(tmp_path):
    f=tmp_path/'manual.pdf';raw=pdf_bytes();f.write_bytes(raw)
    rp=import_local_pdf(f,tmp_path/'intake',regulator='MAS',url=MAS)
    r=json.loads(rp.read_text());assert r['retrieval_method']=='OPERATOR_SUPPLIED_LOCAL_PDF_NOT_LIVE_FETCH'
    assert r['live_retrieval_verified'] is False
    out=convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-MANUAL')
    assert out['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert out['retrieval_state']=='QUARANTINED_FOR_HUMAN_REVIEW'

def test_existing_txt_tamper_rejected(tmp_path):
    rp,_=make_receipt(tmp_path)
    out=convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST')
    Path(out['text_file']).write_text('changed')
    with pytest.raises(ConversionError,match='derivative was modified'):
        convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST')

def test_html_conversion(tmp_path):
    raw=b'<html><body><h1>Official rule heading</h1><p>This is a publication about regulation with enough descriptive text about oversight duties and committee approvals.</p><script>bad ignored</script></body></html>'
    rp,_=make_receipt(tmp_path,raw,'text/html')
    out=convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-HTML')
    txt=Path(out['text_file']).read_text()
    assert 'Official rule heading' in txt and 'bad ignored' not in txt

def test_receipt_cannot_escape_intake(tmp_path):
    rp,r=make_receipt(tmp_path)
    data=json.loads(rp.read_text());data['source_file']=str(tmp_path/'elsewhere.pdf')
    rp.write_text(json.dumps(data)); (tmp_path/'elsewhere.pdf').write_bytes(pdf_bytes())
    with pytest.raises(ConversionError,match='outside receipt intake'):
        convert_receipt(rp,tmp_path/'instruments',instrument_id='MAS-TEST')
