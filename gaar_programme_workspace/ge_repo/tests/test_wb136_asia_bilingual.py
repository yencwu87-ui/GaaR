from pathlib import Path
import json
import pytest
from governance.watcher.asia_sources import parse_hkma_brdr,parse_nfra_api,parse_nfra_index
from governance.watcher.bilingual import segments_from_instrument,translate_instrument,TranslationError
from governance.watcher.regulator_fetch import approved_url

HKMA='''<html><body>
<a href="/eng/doc-ldg/docId/20260827-3-EN">Consultation on revised SPM module CA-B-2 Systemically Important Banks</a>
<a href="/eng/doc-ldg/docId/20260622-1-EN">Supporting Adoption of Artificial Intelligence in Fighting Financial Crime</a>
<a href="https://evil.example/x">Bad</a></body></html>'''
NFRA='''<html><body>
<a href="/cn/view/pages/ItemDetail.html?docId=12345&itemId=928">国家金融监督管理总局关于银行业保险业人工智能安全开发应用的指导意见</a>
<a href="/cn/view/pages/ItemDetail.html?docId=23456&itemId=928">关于公开征求某某办法意见的公告</a>
<a href="https://evil.example/x">Bad</a></body></html>'''

def test_hkma_parser_bounded_and_domains():
    rows=parse_hkma_brdr(HKMA)
    assert len(rows)==2
    ai=next(r for r in rows if 'Artificial Intelligence' in r['title'])
    assert ai['authority']=='HKMA' and ai['language']=='English'
    assert 'AI and model governance' in ai['domains']
    assert all(r['url'].startswith('https://brdr.hkma.gov.hk/') for r in rows)

def test_hkma_consultation_not_binding_classification():
    row=next(r for r in parse_hkma_brdr(HKMA) if 'Consultation' in r['title'])
    assert row['publication_category']=='consultation'
    assert row['lifecycle']=='consultation'

def test_nfra_parser_chinese_and_category():
    rows=parse_nfra_index(NFRA)
    assert len(rows)==2
    assert all(r['authority']=='NFRA' for r in rows)
    assert all(r['language']=='Simplified Chinese' for r in rows)
    assert any(r['publication_category']=='guidance' for r in rows)
    assert any(r['publication_category']=='consultation_or_draft' for r in rows)

def test_nfra_api_parser_preserves_provenance_and_classifies_english():
    payload={'rptCode':200,'data':{'total':2,'rows':[
        {'docId':1264488,'docTitle':'Guiding Opinions on Safe Development of Artificial Intelligence','publishDate':'2026-06-18 15:57:00','pdfFileUrl':'/chinese/OFFICE/PDF/1264488.pdf'},
        {'docId':1255840,'docTitle':'NFRA Solicits Public Opinions on Licensing Rules (Draft for Comments)','publishDate':'2026-04-10 17:05:00','pdfFileUrl':'/chinese/OFFICE/PDF/1255840.pdf'},
    ]}}
    rows=parse_nfra_api(payload,item_id=981)
    assert [r['document_id'] for r in rows]==['1264488','1255840']
    assert rows[0]['publication_category']=='guidance'
    assert rows[1]['publication_category']=='consultation_or_draft' and rows[1]['lifecycle']=='consultation'
    assert all(r['language']=='English' and r['source_scope']=='NFRA bounded official JSON API' for r in rows)
    assert all(r['url'].startswith('https://www.nfra.gov.cn/en/view/pages/ItemDetail.html?') for r in rows)

@pytest.mark.parametrize('row',[
    {'docId':0,'docTitle':'Bad','publishDate':'2026-01-01'},
    {'docId':1,'docTitle':'','publishDate':'2026-01-01'},
    {'docId':1,'docTitle':'Missing date'},
    {'docId':1,'docTitle':'Bad date','publishDate':'yesterday'},
    {'docId':1,'docTitle':'Wrong item','publishDate':'2026-01-01','itemId':999},
    {'docId':1,'docTitle':'Bad PDF','publishDate':'2026-01-01','pdfFileUrl':'https://evil.example/a.pdf'},
    {'docId':1,'docTitle':'Bad link','publishDate':'2026-01-01','titleLink':'https://evil.example/a'},
])
def test_nfra_api_parser_rejects_malformed_rows(row):
    with pytest.raises(ValueError):parse_nfra_api({'rptCode':200,'data':{'total':1,'rows':[row]}})

def test_official_domain_allowlist_extended():
    assert approved_url('https://brdr.hkma.gov.hk/eng/main','HKMA')
    assert approved_url('https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=1','NFRA')
    assert not approved_url('https://nfra.example.com/x','NFRA')

def test_translation_segments_preserve_page_anchor():
    src='HEADER\n===== SOURCE PAGE 1 =====\n第一条 本办法适用于银行机构。\n\n第二条 应建立风险管理制度。\n===== SOURCE PAGE 2 =====\n第三条 应保存记录。'
    seg=segments_from_instrument(src,max_chars=100)
    assert seg and seg[0]['page']==1 and seg[-1]['page']==2

def test_non_chinese_translation_rejected():
    with pytest.raises(TranslationError):segments_from_instrument('English only regulatory text here with no Chinese content.')

def test_bilingual_output_is_review_only_and_immutable_source(tmp_path):
    src=tmp_path/'instrument.txt'
    src.write_text('===== SOURCE PAGE 1 =====\n第一条 银行应建立人工智能风险管理制度。\n\n第二条 应保存审计记录。',encoding='utf-8')
    before=src.read_bytes()
    out=translate_instrument(src,tmp_path/'out',authority='NFRA',instrument_id='NFRA-AI-2026',provider_name='test-local',model_name='fixture-v1',translate=lambda zh:'EN:'+zh)
    assert src.read_bytes()==before
    data=json.loads(Path(out['json_file']).read_text(encoding='utf-8'))
    assert data['translation_authoritative'] is False
    assert data['human_verification_required'] is True
    assert data['auto_add'] is False and data['auto_commit'] is False and data['auto_push'] is False
    assert all('zh' in s and 'en' in s for s in data['segments'])

def test_translation_failure_blocks_no_partial_artifact(tmp_path):
    src=tmp_path/'instrument.txt';src.write_text('===== SOURCE PAGE 1 =====\n第一条 银行应建立治理制度。',encoding='utf-8')
    with pytest.raises(TranslationError):
        translate_instrument(src,tmp_path/'out',authority='NFRA',instrument_id='X',provider_name='x',model_name='x',translate=lambda z:'')
    assert not list((tmp_path/'out').rglob('instrument.bilingual.json'))
