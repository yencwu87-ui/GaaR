"""Live, full-contract held-out evaluation; structural checks do not grade wisdom."""
import hashlib,json,uuid
from governance.investigation.contracts import EvidenceExamination,ExplanationSet,TestPlan,ChallengeRecord
from governance.investigation.store import canonical
from governance.operations.runtime import signers_for
from governance.operations.live import LiveClient
from .qualification import signed_document,fingerprint
from .journal import atomic_json

SCHEMAS={'examine':EvidenceExamination,'explain':ExplanationSet,'plan':TestPlan,'challenge':ChallengeRecord}
ROLES={'examine':'assessor','explain':'assessor','plan':'test_planner','challenge':'challenger'}
CATEGORIES={'violation','legitimate_exception','contradiction','insufficient_evidence'}

def predicate(response,rule):
    if rule['operator'] not in {'equals','contains','absent'}:raise ValueError('unsupported rubric operator')
    value=response;found=True
    for part in rule['path']:
        try:value=value[int(part)] if isinstance(value,list) else value[part]
        except (KeyError,IndexError,TypeError,ValueError):found=False;break
    if rule['operator']=='absent':return not found
    if not found:return False
    if rule['operator']=='equals':return value==rule['value']
    return isinstance(value,(list,dict,str)) and rule['value'] in value


def evaluate(config,root):
    path=config.get('production_evaluation_manifest')
    if not path:return {'status':'NOT_EVALUATED','reason':'Independent frozen full-contract corpus required','release_authorized':False}
    body,labeler,_=signed_document(root/path,config['trusted_keys'],'judgment_evaluator',True)
    signers=signers_for(config,root)
    for role in set(ROLES.values()):
        actor=config['trusted_keys'][signers[role].key_id]
        if actor['actor']==labeler['actor'] or actor['public_key']==labeler['public_key']:raise ValueError('labels must be independent of evaluated identities')
    cases=body['cases']
    if not body.get('frozen_at') or not cases or len({c['case_id'] for c in cases})!=len(cases):raise ValueError('unique frozen cases required')
    if {(c['stage'],c['category']) for c in cases}!={(s,c) for s in SCHEMAS for c in CATEGORIES}:raise ValueError('four stages by four case categories required')
    development=set(body['development_input_hashes']);seen=set();loaded=[]
    for case in cases:
        source=(root/case['path']).resolve(strict=True)
        if not source.is_relative_to(root.resolve()):raise ValueError('case escaped approved corpus root')
        raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        if sha!=case['sha256'] or sha in development or sha in seen:raise ValueError('case integrity, duplication or development overlap')
        seen.add(sha);item=json.loads(raw)
        if set(item)!={'production_prompt'} or not isinstance(item['production_prompt'],dict):raise ValueError('only frozen production prompt may be sent')
        if not case.get('assertions') or not case.get('independent_expected_judgment'):raise ValueError('independent labels and nonempty checks required')
        for rule in case['assertions']:
            if not rule.get('id') or not isinstance(rule.get('path'),list) or rule.get('operator') not in {'equals','contains','absent'}:raise ValueError('invalid deterministic rubric')
        if len({r['id'] for r in case['assertions']})!=len(case['assertions']):raise ValueError('duplicate rubric item')
        loaded.append((case,item['production_prompt']))
    run_id=uuid.uuid4().hex;directory=root/config.get('evaluation_dir','../var/judgment_evaluations')/run_id
    records=[]
    for case,prompt in loaded:
        stage=case['stage'];schema=SCHEMAS[stage]
        # Expected labels/rubric remain outside the inference request.
        prompt={**prompt,'schema':schema.model_json_schema()}
        client=LiveClient(config['models'][stage],'evaluation_'+stage,signers[ROLES[stage]],directory/'receipts',case['case_id'])
        try:
            raw=client(canonical(prompt));response=schema.model_validate_json(raw).model_dump(mode='json')
            assertions=[{'id':r['id'],'passed':predicate(response,r),'critical':r.get('critical',False)} for r in case['assertions']]
            records.append({'case_id':case['case_id'],'stage':stage,'category':case['category'],'status':'RESPONSE_VALIDATED','response':response,'assertions':assertions,
                            'independent_expected_judgment':case['independent_expected_judgment'],'semantic_review':'PENDING_INDEPENDENT_REVIEW'})
        except Exception as exc:records.append({'case_id':case['case_id'],'stage':stage,'category':case['category'],'status':'UNAVAILABLE','reason':str(exc)})
    result={'status':'RESPONSES_RECORDED' if all(r['status']=='RESPONSE_VALIDATED' for r in records) else 'PARTIAL','run_id':run_id,'fingerprint':fingerprint(config),'cases':records,
            'critical_assertion_failures':sum(not a['passed'] and a['critical'] for r in records for a in r.get('assertions',[])),
            'semantic_review':'PENDING_INDEPENDENT_REVIEW','auditor_baseline':'NOT_MEASURED','release_authorized':False,
            'limitations':['Production response schemas validated; semantic truth and production prompt equivalence require independent review.','Structural assertions are not claim-level precision or recall.','No auditor superiority claim.']}
    atomic_json(directory/'evaluation.json',result)
    return {**result,'report_path':str(directory/'evaluation.json')}
