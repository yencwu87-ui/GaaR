"""Loss-aware, fail-closed conversion of quarantined source bytes into instrument TXT.

TXT is a derivative for search and review, never a substitute for original PDF/HTML.
No changes to evidence admission, regulatory classification or governance state.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

class ConversionError(ValueError):
    pass

class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.suppressed=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'): self.suppressed+=1
        elif tag in ('p','br','div','li','h1','h2','h3','tr'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript'): self.suppressed=max(0,self.suppressed-1)
        elif tag in ('p','div','li','h1','h2','h3','tr'): self.parts.append('\n')
    def handle_data(self,data):
        if not self.suppressed: self.parts.append(data)

def extract_text(raw:bytes,kind:str)->tuple[str,int]:
    if kind=='application/pdf':
        if not raw.startswith(b'%PDF-'): raise ConversionError('INVALID_DOCUMENT: missing PDF header')
        try:
            import fitz
        except ImportError as exc:
            raise ConversionError('PyMuPDF is required for PDF conversion: pip install pymupdf') from exc
        try:
            with fitz.open(stream=raw,filetype='pdf') as doc:
                if doc.is_encrypted: raise ConversionError('PDF encrypted: cannot extract text')
                pages=[]
                for idx,page in enumerate(doc):
                    pages.append(f'\n\n===== SOURCE PAGE {idx+1} =====\n'+page.get_text(sort=True))
                text=''.join(pages); count=len(doc)
        except ConversionError: raise
        except Exception as exc: raise ConversionError('INVALID_DOCUMENT: PDF cannot be parsed: '+str(exc)) from exc
    elif kind=='text/html':
        if not raw.lstrip().lower().startswith((b'<!doctype html',b'<html')):
            raise ConversionError('INVALID_DOCUMENT: not a complete HTML publication')
        parser=_TextHTML();parser.feed(raw.decode('utf-8','replace'))
        text=''.join(parser.parts); count=1
    else: raise ConversionError('unsupported source content type')
    text='\n'.join(re.sub(r'[ \t]+',' ',line).strip() for line in text.splitlines())
    text=re.sub(r'\n{4,}','\n\n\n',text).strip()
    if len(re.sub(r'\s+','',text))<40:
        raise ConversionError('TEXT_EXTRACTION_INCOMPLETE: scanned/empty document, no OCR performed')
    if any(s in text[:5000].lower() for s in ('verify you are human','enable javascript to continue','cloudflare turnstile')):
        raise ConversionError('DEGRADED: challenge page is not a regulatory instrument')
    return text,count

def _atomic_write(path:Path,data:bytes):
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.instrument-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as fh:
            fh.write(data);fh.flush();os.fsync(fh.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def convert_receipt(receipt_path:Path,instruments_root:Path,*,instrument_id:str, title:str='', regulator:str|None=None)->dict:
    """Convert a prior verified receipt, keeping TXT derivative versioned by PDF SHA-256."""
    receipt=json.loads(Path(receipt_path).read_text(encoding='utf-8'))
    if receipt.get('state') not in ('QUARANTINED_FOR_HUMAN_REVIEW','STAGED_NOT_COMMITTED_NOT_PUSHED'):
        raise ConversionError('receipt is not a quarantined/staged official intake')
    reg=regulator or receipt.get('regulator')
    if reg not in ('MAS','FCA','HKMA','NFRA'): raise ConversionError('unsupported regulator')
    from .regulator_fetch import approved_url
    if not approved_url(str(receipt.get('document_url','')),reg):
        raise ConversionError('receipt has unapproved document URL')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',instrument_id):
        raise ConversionError('invalid instrument identifier')
    p=Path(receipt['source_file']).resolve(strict=True)
    # Only accept an original content-addressed file in the same private intake folder as receipt.
    if p.parent != Path(receipt_path).resolve().parent:
        raise ConversionError('source file is outside receipt intake directory')
    if p.is_symlink() or Path(receipt['source_file']).is_symlink():
        raise ConversionError('source file is a symlink')
    raw=p.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    if digest!=receipt.get('source_sha256'):
        raise ConversionError('SOURCE_HASH_MISMATCH: original document changed')
    kind=receipt.get('source_content_type')
    suffix='.pdf' if kind=='application/pdf' else '.html' if kind=='text/html' else None
    if not suffix or p.name!=digest+suffix:
        raise ConversionError('source file must be the original content-addressed PDF/HTML')
    text,pages=extract_text(raw,kind)
    origin_label=('OPERATOR-SUPPLIED URL, NOT LIVE-VERIFIED'
                  if receipt.get('retrieval_method')=='OPERATOR_SUPPLIED_LOCAL_PDF_NOT_LIVE_FETCH'
                  else 'FETCH RECEIPT URL')
    header=(f'GAAR INSTRUMENT TEXT DERIVATIVE — NOT AN OFFICIAL SOURCE\n'
            f'Instrument: {instrument_id}\nTitle (operator-supplied): {title or "UNVERIFIED"}\n'
            f'Regulator: {reg}\nOfficial URL (receipt): {receipt.get("document_url", "")}\n'
            f'Original SHA-256: {digest}\n'
            f'Source type: {kind}\n'
            f'Classification/applicability: NOT VERIFIED BY CONVERSION\n'
            f'--- BEGIN EXTRACTED TEXT ---\n')
    content=(header+text+'\n--- END EXTRACTED TEXT ---\n').encode('utf-8')
    destdir=Path(instruments_root)/'regulatory'/reg/instrument_id
    destdir.mkdir(parents=True,exist_ok=True)
    target=destdir/(digest+'.txt'); metadata=destdir/(digest+'.conversion.json')
    if target.exists() and target.read_bytes()!=content:
        raise ConversionError('existing TXT derivative was modified')
    if not target.exists():_atomic_write(target,content)
    info={'status':'EXTRACTED_FOR_REVIEW','instrument_id':instrument_id,'regulator':reg,
          'source_sha256':digest,'text_sha256':hashlib.sha256(content).hexdigest(),
          'source_file':str(p),'source_url':receipt.get('document_url'),
          'source_receipt':str(Path(receipt_path).resolve()),'text_file':str(target.resolve()),
          'source_type':kind,'pages_or_html_documents':pages,
          'text_characters':len(text),'conversion_engine':'PyMuPDF' if suffix=='.pdf' else 'HTMLParser',
          'retrieval_state':receipt['state'],'retrieval_method':receipt.get('retrieval_method'),
          'live_retrieval_verified':receipt.get('retrieval_method') not in (None,'OPERATOR_SUPPLIED_LOCAL_PDF_NOT_LIVE_FETCH'),
          'not_authoritative':True,
          'classification_review_required':True,'ocr_performed':False}
    if metadata.exists():
        prev=json.loads(metadata.read_text(encoding='utf-8'))
        if any(prev.get(k)!=info[k] for k in ('source_sha256','text_sha256','instrument_id')):
            raise ConversionError('existing conversion metadata conflicts')
    else:_atomic_write(metadata,json.dumps(info,indent=2).encode('utf-8'))
    return info

def import_local_pdf(source:Path,output:Path,*,regulator:str,url:str)->Path:
    """Operator-attested offline archival intake; does NOT assert official network retrieval."""
    from .regulator_fetch import Fetched,approved_url,record_receipt
    if not approved_url(url,regulator): raise ConversionError('not an approved official URL')
    raw=Path(source).read_bytes()
    text,_=extract_text(raw,'application/pdf')
    if len(text)<40:raise ConversionError('PDF has insufficient extractable text')
    receipt=record_receipt(output,regulator,None,Fetched(url,raw,'application/pdf',None,None),method='OPERATOR_SUPPLIED_LOCAL_PDF_NOT_LIVE_FETCH')
    # Never silently claim fetch was successful just because user supplies a matching URL.
    # Write a distinct operator-supplied receipt: never overwrite or reuse a live retrieval receipt.
    rp=Path(output)/(receipt['source_sha256']+'.offline.receipt.json')
    data=dict(receipt)
    data['retrieval_method']='OPERATOR_SUPPLIED_LOCAL_PDF_NOT_LIVE_FETCH'
    data['live_retrieval_verified']=False
    data['operator_origin_attestation_required']=True
    if not rp.exists():_atomic_write(rp,json.dumps(data,indent=2).encode('utf-8'))
    return rp
