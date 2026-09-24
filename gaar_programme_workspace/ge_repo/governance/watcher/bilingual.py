"""WB-136: governed bilingual review derivatives for Chinese regulatory instruments.

The source Chinese TXT and original PDF/HTML remain authoritative artifacts. Translation
is a review aid only and can never be used as evidence of legal meaning or automatically
committed/pushed into an assessment.
"""
from __future__ import annotations
import hashlib,json,os,re,tempfile
from pathlib import Path
from typing import Callable

DISCLAIMER=("MACHINE TRANSLATION FOR REVIEW ONLY. The original Chinese regulatory text "
            "remains authoritative. Verify material legal or regulatory interpretations "
            "against the original source and, where required, qualified counsel.")

class TranslationError(ValueError):pass

def looks_chinese(text:str)->bool:
    chars=re.findall(r'[\u4e00-\u9fff]',text)
    visible=re.sub(r'\s+','',text)
    return bool(visible) and len(chars)/max(1,len(visible))>=0.05

def segments_from_instrument(text:str,max_chars:int=2400)->list[dict]:
    if not looks_chinese(text):raise TranslationError('source instrument does not appear to contain Chinese text')
    # Preserve WB-133 page anchors when available.
    page_rx=re.compile(r'===== SOURCE PAGE (\d+) =====')
    marks=list(page_rx.finditer(text));segments=[]
    bodies=[]
    if marks:
        for i,m in enumerate(marks):
            bodies.append((int(m.group(1)),text[m.end():marks[i+1].start() if i+1<len(marks) else len(text)]))
    else:bodies=[(None,text)]
    seq=0
    for page,body in bodies:
        paras=[p.strip() for p in re.split(r'\n{2,}',body) if p.strip()]
        buf=''
        for para in paras:
            pieces=[para[i:i+max_chars] for i in range(0,len(para),max_chars)]
            for piece in pieces:
                if buf and len(buf)+len(piece)+2>max_chars:
                    seq+=1;segments.append({'segment_id':f'S{seq:04d}','page':page,'zh':buf});buf=''
                buf=(buf+'\n\n'+piece).strip()
        if buf:
            seq+=1;segments.append({'segment_id':f'S{seq:04d}','page':page,'zh':buf})
    if not segments:raise TranslationError('no translatable segments produced')
    return segments

def _atomic(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.bilingual-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def translate_instrument(source_txt:Path,out_root:Path,*,authority:str,instrument_id:str,provider_name:str,model_name:str,
                         translate:Callable[[str],str])->dict:
    source_txt=Path(source_txt).resolve(strict=True)
    raw=source_txt.read_bytes();source_hash=hashlib.sha256(raw).hexdigest();text=raw.decode('utf-8')
    segments=segments_from_instrument(text);translated=[]
    for row in segments:
        en=translate(row['zh'])
        if not isinstance(en,str) or len(en.strip())<3:raise TranslationError(f"translation missing for {row['segment_id']}")
        translated.append({**row,'en':en.strip()})
    payload={'schema':'gaar.bilingual-instrument.v1','status':'TRANSLATED_FOR_HUMAN_REVIEW',
             'authority':authority,'instrument_id':instrument_id,'source_text_file':str(source_txt),
             'source_text_sha256':source_hash,'source_language':'zh-CN','target_language':'en',
             'provider':provider_name,'model':model_name,'translation_authoritative':False,
             'human_verification_required':True,'auto_add':False,'auto_commit':False,'auto_push':False,
             'disclaimer':DISCLAIMER,'segments':translated}
    canonical=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    payload['bilingual_payload_sha256']=hashlib.sha256(canonical).hexdigest()
    dest=Path(out_root)/'bilingual'/authority/instrument_id/source_hash
    jpath=dest/'instrument.bilingual.json';mpath=dest/'instrument.bilingual.md'
    md=[f'# {instrument_id} — bilingual review aid','',DISCLAIMER,'',f'Provider: `{provider_name}` · Model: `{model_name}`','']
    for row in translated:
        loc=f"Source page {row['page']}" if row['page'] else 'Source location: text derivative'
        md += [f"## {row['segment_id']} · {loc}",'', '**中文原文**','',row['zh'],'','**English review translation**','',row['en'],'']
    _atomic(jpath,json.dumps(payload,ensure_ascii=False,indent=2).encode('utf-8'))
    _atomic(mpath,'\n'.join(md).encode('utf-8'))
    return {k:v for k,v in payload.items() if k!='segments'}|{'segment_count':len(translated),'json_file':str(jpath),'markdown_file':str(mpath)}
