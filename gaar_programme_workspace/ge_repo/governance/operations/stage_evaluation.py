"""Task-specific objective metrics. Semantic judgment still needs independent review."""
import hashlib
import json
from governance.investigation.store import canonical
from governance.result_contract import verify_signature
from .runtime import signers_for, STAGES
from .live import LiveClient

FIELDS={'examine':'findings','explain':'hypotheses','plan':'tests','challenge':'findings'}
# This explicit evaluation interface is separate from production InvestigationRecord schemas.

def score(stage,response,rubric,allowed_refs):
    if stage not in FIELDS: raise ValueError('unsupported evaluation stage')
    items=response.get(FIELDS[stage])
    if not isinstance(items,list): raise ValueError('missing stage response items')
    ids=[i['id'] for i in items]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate response item IDs')
    if any(not isinstance(i.get('evidence_refs'),list) for i in items): raise ValueError('evidence_refs required')
    refs={ref for i in items for ref in i['evidence_refs']}
    expected=set(rubric['required_ids']);got=set(ids)
    prohibited=set(rubric.get('prohibited_ids',[]))
    if not expected: raise ValueError('empty rubric cannot produce a perfect recall score')
    out={'required_item_recall':len(got&expected)/len(expected),
         'selection_precision':len(got&set(rubric.get('acceptable_ids',rubric['required_ids'])))/len(got) if got else 0.0,
         'invented_reference_count':len(refs-set(allowed_refs)),
         'prohibited_claim_count':len(got&prohibited),
         'missed_material_ids':sorted(set(rubric.get('material_ids',[]))-got)}
    mismatches=[]
    for i in items:
        for field,value in rubric.get('expected_fields',{}).get(i['id'],{}).items():
            if i.get(field)!=value:mismatches.append(i['id']+':'+field)
    out['field_mismatches']=mismatches
    if stage=='plan':
        first=rubric.get('acceptable_first_test_ids',[])
        if not first:raise ValueError('planning rubric needs acceptable first tests')
        out['first_test_decision_impact_correct']=bool(ids and ids[0] in first)
        out['unexecuted_claimed_executed']=sum(i.get('execution_status')=='EXECUTED' for i in items)
    out['semantic_review']='PENDING_INDEPENDENT_REVIEW'
    return out


def evaluate(config,root):
    if not config.get('stage_evaluation_manifest'):
        return {'status':'NOT_EVALUATED','cases_executed':0,'reason':'Approved four-stage held-out manifest missing'}
    manifest=json.loads((root/config['stage_evaluation_manifest']).read_text());body=manifest['payload']
    trust=config['trusted_keys'].get(manifest['key_id'],{})
    if 'judgment_evaluator' not in trust.get('roles',[]) or not verify_signature(trust.get('public_key',''),manifest['signature'],canonical(body).encode()):
        raise ValueError('invalid independent evaluation approval')
    signers=signers_for(config,root)
    for role in ('assessor','test_planner','challenger'):
        policy=config['trusted_keys'][signers[role].key_id]
        if trust.get('actor')==policy.get('actor') or trust.get('public_key')==policy.get('public_key'):
            raise ValueError('label approver must be separate from evaluated agents')
    cases=body['cases'];categories={'violation','legitimate_exception','contradiction','insufficient_evidence'}
    if not body.get('frozen_at') or not cases:raise ValueError('frozen nonempty corpus required')
    if len({c['case_id'] for c in cases})!=len(cases):raise ValueError('duplicate case identity')
    if {(c['stage'],c['category']) for c in cases}!={(s,c) for s in FIELDS for c in categories}:
        raise ValueError('all four categories required in each of four stages')
    hashes=set();loaded=[]
    for case in cases:
        p=(root/case['path']).resolve(strict=True)
        if not p.is_relative_to(root.resolve()):raise ValueError('case outside approved corpus directory')
        raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=case['sha256'] or digest in hashes or digest in set(body['development_input_hashes']):raise ValueError('modified, duplicated or development-overlap case')
        hashes.add(digest);content=json.loads(raw)
        if set(content)!={'context','evidence','allowed_refs','candidate_items'}:raise ValueError('case input has unexpected fields')
        candidate_ids={item['id'] for item in content['candidate_items']}
        if len(candidate_ids)!=len(content['candidate_items']):raise ValueError('duplicate candidate ID')
        rubric=case['rubric'];required=set(rubric['required_ids']);acceptable=set(rubric.get('acceptable_ids',rubric['required_ids']))
        if not required<=acceptable<=candidate_ids or not set(rubric.get('material_ids',[]))<=required or set(rubric.get('prohibited_ids',[]))&acceptable:
            raise ValueError('inconsistent evaluation rubric')
        score(case['stage'],{FIELDS[case['stage']]:[]},rubric,content['allowed_refs'])
        loaded.append((case,content))
    results=[]
    for case,content in loaded:
        stage=case['stage'];role=STAGES[stage]
        client=LiveClient(config['models'][stage],'evaluation_'+stage,signers[role],root/config['receipt_dir'],case['case_id'])
        prompt={'task':'Evaluate the supplied case for stage '+stage+'. Select supported items from candidate_items, using supplied evidence. Alternatives are not established facts. Proposed tests are not executed tests.',
                'response_contract':{FIELDS[stage]:[{'id':'candidate ID','evidence_refs':['supplied reference ID'],'rationale':'auditable explanation','status':'stage-specific disposition','execution_status':'PROPOSED for planned tests'}]},
                'case':content}
        try:
            response=json.loads(client(canonical(prompt)))
            metrics=score(stage,response,case['rubric'],content['allowed_refs'])
            results.append({'case_id':case['case_id'],'stage':stage,'category':case['category'],'status':'METRICS_COMPUTED','metrics':metrics,'response':response})
        except Exception as exc:
            results.append({'case_id':case['case_id'],'stage':stage,'category':case['category'],'status':'UNAVAILABLE','error':str(exc)})
    completed=sum(r['status']=='METRICS_COMPUTED' for r in results)
    return {'status':'METRICS_COMPUTED' if completed==len(results) else 'PARTIAL','cases_executed':completed,'total_cases':len(results),'results':results,
        'release_decision':'NOT_AUTHORIZED','semantic_review':'PENDING_INDEPENDENT_REVIEW',
        'limitation':'Structured candidate selection benchmark, not a free-form production-agent benchmark. No automatic quality certification.'}
