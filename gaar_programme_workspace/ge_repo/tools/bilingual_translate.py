#!/usr/bin/env python3
"""Create an English review translation from a WB-133 Chinese TXT instrument.

Explicit local-model action only. It never ADDs, COMMITs or PUSHes.
Examples:
  python tools/bilingual_translate.py --source instruments/regulatory/NFRA/...txt --authority NFRA --id NFRA-2026-X --provider ollama
  python tools/bilingual_translate.py --source ... --authority NFRA --id ... --provider colibri
"""
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from governance.watcher.bilingual import translate_instrument,TranslationError

def provider(name,model=None):
    if name=='ollama':
        base=os.environ.get('OLLAMA_BASE_URL','http://127.0.0.1:11434').rstrip('/')
        mdl=model or os.environ.get('OLLAMA_MODEL','llama3.2:latest')
        def call(zh):
            prompt=('Translate the following Chinese regulatory text into faithful English. Do not interpret, summarize, add legal conclusions, or omit numbers. Preserve defined terms where possible. Return only the English translation.\n\n'+zh)
            r=requests.post(base+'/api/generate',json={'model':mdl,'prompt':prompt,'stream':False,'options':{'temperature':0}},timeout=120);r.raise_for_status();return r.json().get('response','')
        return 'ollama',mdl,call
    if name=='colibri':
        base=os.environ.get('COLIBRI_BASE_URL','http://127.0.0.1:8000/v1').rstrip('/')
        mdl=model or os.environ.get('COLIBRI_MODEL','glm-5.2-colibri')
        def call(zh):
            prompt='Translate faithfully from Chinese to English. No interpretation, summary, added legal conclusion, or omitted numbers. Output translation only.\n\n'+zh
            r=requests.post(base+'/chat/completions',json={'model':mdl,'messages':[{'role':'user','content':prompt}],'temperature':0},timeout=180);r.raise_for_status();return r.json()['choices'][0]['message']['content']
        return 'colibri',mdl,call
    raise TranslationError('unsupported provider')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--authority',required=True);p.add_argument('--id',required=True);p.add_argument('--provider',choices=('ollama','colibri'),required=True);p.add_argument('--model');p.add_argument('--out',type=Path,default=ROOT/'instruments')
    a=p.parse_args()
    try:
        pname,model,call=provider(a.provider,a.model);out=translate_instrument(a.source,a.out,authority=a.authority,instrument_id=a.id,provider_name=pname,model_name=model,translate=call);print(json.dumps(out,ensure_ascii=False,indent=2));return 0
    except Exception as e:
        print(json.dumps({'status':'BLOCKED','reason':str(e)},ensure_ascii=False),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
