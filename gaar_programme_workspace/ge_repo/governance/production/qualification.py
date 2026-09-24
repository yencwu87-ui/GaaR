"""A software pass cannot substitute for independently approved live judgment."""
from datetime import datetime,timezone
import hashlib,json,math
from pathlib import Path
from governance.investigation.store import canonical,digest
from governance.investigation.dependencies import load as load_knowledge
from governance.result_contract import verify_signature


def fingerprint(config):
    root=Path(__file__).resolve().parents[2]
    paths=[]
    for folder in ('governance/investigation','governance/operations','governance/production'):
        paths.extend(sorted((root/folder).glob('*.py')))
    paths.extend(root/p for p in ('governance/knowledge_resolver.py','governance/result_contract.py','governance/result_store.py'))
    return {'code_sha256':digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),
            'knowledge_sha256':load_knowledge()[1], 'models_sha256':digest(config['models']),
            'trust_sha256':digest(config['trusted_keys']),
            'operating_scope_sha256':digest({k:config.get(k) for k in ('sources','collectors','http_collectors','precedent_snapshot','action_owners','closure_tools_by_control')}),'quality_policy_sha256':digest(config.get('quality_policy',{}))}


def signed_document(path,trust,role,human=False):
    doc=json.loads(Path(path).read_text());policy=trust.get(doc['key_id'],{})
    if role not in policy.get('roles',[]) or (human and policy.get('actor_type')!='human'):raise ValueError('required independent approval role absent')
    if not verify_signature(policy.get('public_key',''),doc['signature'],canonical(doc['payload']).encode()):raise ValueError('invalid approval signature')
    return doc['payload'],policy,doc


def check(config,root):
    path=config.get('qualification_report')
    if not path:return {'status':'NOT_QUALIFIED','reason':'Independent live-judgment qualification approval missing'}
    try:
        identities={}
        for stage in ('examine','challenge'):
            model=config['models'][stage]
            revision=model.get('model_sha256') or model.get('model_revision')
            if not revision:raise ValueError('production qualification requires an immutable model revision/hash for '+stage)
            identities[stage]=(model.get('provider'),model.get('base_url'),model.get('model'),revision)
        if identities['examine']==identities['challenge']:
            raise ValueError('challenge must use a separately identified model/revision from examination')
        if identities['examine'][3]==identities['challenge'][3]:
            raise ValueError('challenge must use a different model revision, not the same weights at another endpoint')
        payload,approver,_=signed_document(root/path,config['trusted_keys'],'quality_approver',True)
        if payload['fingerprint']!=fingerprint(config):raise ValueError('qualification is for different code, knowledge, models or policy')
        expiry=datetime.fromisoformat(payload['valid_until'].replace('Z','+00:00'))
        if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):raise ValueError('qualification expired or lacks timezone')
        if payload.get('semantic_review')!='APPROVED' or not payload.get('semantic_review_ref') or payload.get('decision')!='APPROVED':raise ValueError('semantic quality has not been independently approved')
        for role in ('assessor','test_planner','challenger'):
            actor=config['trusted_keys'][config['signers'][role]['key_id']]
            if actor.get('actor')==approver.get('actor') or actor.get('public_key')==approver.get('public_key'):raise ValueError('quality approver must be independent of evaluated agents')
        policy=config.get('quality_policy',{})
        minimum=policy.get('minimum_cases_per_cell')
        if isinstance(minimum,bool) or not isinstance(minimum,int) or minimum<1:raise ValueError('approved minimum sample requirement absent')
        for stage in ('examine','explain','plan','challenge'):
            for category in ('violation','legitimate_exception','contradiction','insufficient_evidence'):
                cell=payload['metrics'][stage][category]
                if any(isinstance(cell[n],bool) or not isinstance(cell[n],int) or cell[n]<0 for n in ('case_count','unavailable_count','critical_failures')):raise ValueError('invalid measured quality counts')
                if cell['case_count']<minimum or cell['unavailable_count'] or cell['critical_failures']:raise ValueError('incomplete/critical-failing judgment cell')
                for metric in ('precision','recall'):
                    value=cell[metric];limit=policy.get('minimum_'+metric)
                    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('invalid measured quality metric')
                    if isinstance(limit,bool) or not isinstance(limit,(float,int)) or not 0<=limit<=1 or value<limit:raise ValueError('approved quality threshold not met')
        for key in ('held_out_manifest','evaluation_results','semantic_review_artifact'):
            item=payload[key];raw=(root/item['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('qualification artifact hash mismatch')
        receipts=payload['live_receipts']
        if not receipts:raise ValueError('qualification lacks actual inference receipts')
        stages=set()
        for item in receipts:
            raw=(root/item['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('inference receipt hash mismatch')
            receipt=json.loads(raw);signature=receipt.pop('signature');key=config['trusted_keys'].get(receipt['key_id'],{})
            if not verify_signature(key.get('public_key',''),signature,canonical(receipt).encode()):raise ValueError('invalid inference receipt signature')
            if receipt.get('live') is not True or receipt.get('status')!='RESPONSE_RECEIVED':raise ValueError('qualification used missing or non-live inference')
            stage=receipt['stage'].removeprefix('evaluation_');stages.add(stage)
            role={'examine':'assessor','explain':'assessor','plan':'test_planner','challenge':'challenger'}.get(stage)
            if not role or receipt['key_id']!=config['signers'][role]['key_id'] or role not in key.get('roles',[]):raise ValueError('inference receipt does not belong to approved stage identity')
            if stage in config['models'] and receipt.get('model')!=config['models'][stage]['model']:raise ValueError('receipt model mismatch')
        if not {'examine','explain','plan','challenge'}<=stages:raise ValueError('all four live judgment stages required')
        return {'status':'QUALIFIED','valid_until':payload['valid_until'],'fingerprint':payload['fingerprint'],
                'scope_limit':'Qualification approval for recorded version/scope; not a guarantee for every new assessment.'}
    except Exception as exc:return {'status':'NOT_QUALIFIED','reason':str(exc)}
