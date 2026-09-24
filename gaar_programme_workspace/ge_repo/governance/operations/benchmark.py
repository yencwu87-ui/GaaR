"""Held-out live judgment evaluation; labels are never sent to the model."""
import hashlib
import json
from pathlib import Path
from governance.result_contract import verify_signature
from governance.investigation.store import canonical
from .live import LiveClient
from .runtime import signers_for

CATEGORIES={'violation','legitimate_exception','contradiction','insufficient_evidence'}


def evaluate(config, root):
    path=config.get('held_out_manifest')
    if not path:
        return {'status':'NOT_EVALUATED','reason':'Independently labeled, frozen held-out corpus not configured','cases_executed':0}
    manifest=json.loads((root/path).read_text())
    body=manifest['payload'];trust=config['trusted_keys'].get(manifest['key_id'],{})
    if 'judgment_evaluator' not in trust.get('roles',[]) or not verify_signature(trust.get('public_key',''),manifest['signature'],canonical(body).encode()):
        raise ValueError('held-out manifest requires trusted independent evaluator signature')
    signers=signers_for(config,root)
    assessor=config['trusted_keys'][signers['assessor'].key_id]
    if trust.get('actor')==assessor.get('actor') or trust.get('public_key')==assessor.get('public_key'):
        raise ValueError('benchmark label approver must be independent of assessor')
    cases=body['cases']
    if set(c['category'] for c in cases)!=CATEGORIES or not body.get('frozen_at'):
        raise ValueError('frozen corpus must cover all four judgment categories')
    if len({c['case_id'] for c in cases})!=len(cases) or len({c['sha256'] for c in cases})!=len(cases):
        raise ValueError('duplicate held-out cases')
    forbidden=set(body['development_input_hashes'])
    loaded=[]
    for case in cases:
        path=(root/case['path']).resolve(strict=True)
        if not path.is_relative_to(root.resolve()): raise ValueError('case outside manifest root')
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=case['sha256'] or digest in forbidden: raise ValueError('held-out input modified or overlaps declared development corpus')
        content=json.loads(raw)
        # Input files contain evidence/context only; label is in signed manifest.
        if set(content)!={'context','evidence','allowed_refs'}: raise ValueError('unexpected case fields')
        loaded.append((case,content))
    results=[]
    for case,content in loaded:
        client=LiveClient(config['models']['examine'],'held_out',signers['assessor'],root/config['receipt_dir'],case['case_id'])
        prompt={'task':'Classify this case using only supplied evidence. Return JSON with classification, evidence_refs and rationale. Missing evidence is insufficient_evidence, not proof of violation.',
                'classification_options':sorted(CATEGORIES),'case':content}
        try:
            response=json.loads(client(canonical(prompt)))
            if response.get('classification') not in CATEGORIES or not response.get('rationale') or not isinstance(response.get('evidence_refs'),list):
                raise ValueError('invalid judgment response')
            if not set(response['evidence_refs'])<=set(content['allowed_refs']): raise ValueError('invented evidence reference')
            results.append({'case_id':case['case_id'],'category':case['category'],'predicted':response['classification'],'correct':response['classification']==case['category'],'status':'EVALUATED'})
        except Exception as exc:
            results.append({'case_id':case['case_id'],'category':case['category'],'status':'UNAVAILABLE','correct':False,'error':str(exc)})
    completed=sum(r['status']=='EVALUATED' for r in results)
    return {'status':'EVALUATED' if completed==len(results) else 'PARTIAL','cases_executed':completed,'cases':results,
        'accuracy_all_cases':sum(r['correct'] for r in results)/len(results),
        'limitation':'Category accuracy only; does not establish full investigation judgment quality or deployment readiness. Declared development exclusions require independent corpus governance.'}
