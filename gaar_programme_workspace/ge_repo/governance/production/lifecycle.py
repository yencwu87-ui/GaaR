"""GovernanceResult sealing and explicit lifecycle transitions; no deployment approval."""
import hashlib,json
from pathlib import Path
from governance.result_contract import (CanonicalSigner,Decision,ProvenanceTrail,GovernanceResult,create_governance_result,
    ResultStateLog,approve_result,make_state_event,ValidityState,ActorType,TransitionTrigger)
from governance.result_store import ResultStore
from governance.investigation.store import digest,canonical
from governance.operations.secrets import private_seed
from .qualification import signed_document,check as check_qualification
from .journal import atomic_json


def actor_signer(config,root,role):
    item=config['signers'][role];signer=CanonicalSigner.from_base64(item['key_id'],private_seed(item,root));trust=config['trusted_keys'][signer.key_id]
    if role not in trust.get('roles',[]) or trust.get('public_key')!=signer.public_key_b64:raise ValueError('untrusted '+role)
    return signer


def verify_state_pins(journal,state_log):
    states={e.event_hash:e for e in state_log.read()}
    for event in journal.read():
        if event['kind'] in {'result_current','reassessment_requested'}:
            payload=event['payload'];pin=payload.get('state_event_hash')
            if pin and (pin not in states or states[pin].result_id!=payload.get('result_id',payload.get('source_result_id'))):
                raise ValueError('signed result-state anchor is missing or altered')


def seal(config,root,iid,engine,journal):
    from .orchestrator import programme_gate
    quality=check_qualification(config,root);gate=programme_gate(engine,iid,journal,quality,config.get('operation_mode','evaluation'),config)
    if not gate['assessment_finalizable']:raise ValueError('integrated quality gate blocks sealing: '+','.join(gate['blockers']))
    executor=actor_signer(config,root,'executor')
    if check_changes(config,root,iid,engine,journal,executor)['status']=='INPUT_CHANGE_DETECTED':
        raise ValueError('changed bound evidence/configuration requires reassessment')
    if journal.latest('reassessment_requested'):raise ValueError('previous result requires reassessment; cannot repromote it')
    path=config.get('result_decisions',{}).get(iid)
    if not path:raise ValueError('result requires explicit signed human decision')
    approval,person,document=signed_document(root/path,config['trusted_keys'],'result_approver',True)
    if 'reliance' in approval or approval.get('governance_result') is False:
        raise ValueError('a pilot attestation is decision support and cannot be promoted to a governance result')
    rows,values=engine.snapshot(iid)
    if values['understand'].synthetic:raise ValueError('synthetic investigation cannot produce production result')
    if approval.get('investigation_id')!=iid or approval.get('investigation_head')!=rows[-1]['record_hash']:raise ValueError('decision does not bind current investigation')
    for role in ('assessor','challenger'):
        other=config['trusted_keys'][config['signers'][role]['key_id']]
        if person['actor']==other['actor'] or person['public_key']==other['public_key']:raise ValueError('result approver must be independent of assessed agent identities')
    verdict=values['conclude'].verdict;decision=Decision(approval['decision'])
    if verdict=='ADVERSE' and decision!=Decision.FAIL:raise ValueError('adverse investigation cannot seal a passing result')
    if verdict=='INCONCLUSIVE' and (decision!=Decision.FAIL or approval.get('assurance_only_fail') is not True):
        raise ValueError('inconclusive requires explicit assurance-only FAIL mapping; no operational breach inferred')
    signer=actor_signer(config,root,'result_sealer')
    sealed=journal.latest('result_sealed')
    if sealed:
        if sealed['payload'].get('human_approval')!=document:raise ValueError('sealed result belongs to a different human approval')
        result=GovernanceResult.model_validate(sealed['payload']['result'])
        if result.provenance.rule_versions.get('investigation_head')!=rows[-1]['record_hash']:
            raise ValueError('sealed result belongs to a different investigation head')
    else:
        ids={'requirement_version_id':values['understand'].requirement_version,'evidence_set_id':'EVID-'+digest([e.model_dump(mode='json') for e in values['examine'].evidence]),
             'assessment_id':'ASSESS-'+iid,'challenge_set_id':'CHALLENGE-'+next(r['record_hash'] for r in rows if r['stage']=='challenge'),
             'human_decision_id':approval['decision_id']}
        provenance=ProvenanceTrail(**ids,assessor_prompt_version='programme-v1',model_version=digest(config['models']),model_invocation_id='INVOCATIONS-'+iid,
            human_decider_id=person['actor'],human_decision_timestamp=approval['at'],workflow_step_timestamps={r['stage']:r['at'] for r in rows},
            rule_versions={'investigation_head':rows[-1]['record_hash'],'investigation_verdict':verdict,'dependency_review':journal.latest('dependency_review')['event_hash'],
                           'quality_fingerprint':digest(quality['fingerprint'])},retrieval_receipt_id='DEPENDENCIES-'+journal.latest('dependency_review')['event_hash'],retrieval_pipeline_version='WB144')
        result=create_governance_result(**ids,decision=decision,rationale=approval['rationale'],provenance=provenance,signer=signer,created_at=approval['at'])
        payload={'result':result.model_dump(mode='json'),'human_approval':document,'deployment_authorized':False}
        journal.append('sealed_result','result_sealed',payload,signer,'result_sealer')
    store=ResultStore(root/config.get('result_store','../var/programme_results.jsonl'))
    existing=[r for r in store.read() if r.result_id==result.result_id]
    if existing and existing[0]!=result:raise ValueError('sealed result identity collision')
    if not existing:store.append(result)
    state_log=ResultStateLog(root/config.get('result_state_log','../var/programme_result_states.jsonl'))
    verify_state_pins(journal,state_log)
    if not any(e.result_id==result.result_id for e in state_log.read()):
        state_log.append(approve_result(result,actor_id=person['actor'],decision_id=approval['decision_id'],reason=approval['rationale'],timestamp=approval['at'],prev_hash=state_log.last_hash()))
    if state_log.current_state(result.result_id)!=ValidityState.CURRENT:raise ValueError('result is no longer current; new assessment required')
    journal.append('result_current','result_current',{'result_id':result.result_id,'decision_id':approval['decision_id'],'state_event_hash':next(e.event_hash for e in reversed(state_log.read()) if e.result_id==result.result_id),'state':'CURRENT','deployment_authorized':False},signer,'result_sealer')
    return {'result_id':result.result_id,'state':'CURRENT','decision':decision.value,'investigation_verdict':verdict,'deployment_authorized':False}


def flag_changed(config,root,journal,signer,change):
    sealed=journal.latest('result_sealed')
    if not sealed:return {'status':'NO_RESULT_TO_REASSESS'}
    result=GovernanceResult.model_validate(sealed['payload']['result']);change_id='CHANGE-'+digest(change)
    state_log=ResultStateLog(root/config.get('result_state_log','../var/programme_result_states.jsonl'))
    verify_state_pins(journal,state_log)
    rows=[e for e in state_log.read() if e.result_id==result.result_id]
    if not rows:return {'status':'RESULT_NOT_CURRENT'}
    current=rows[-1].to_state
    if current==ValidityState.CURRENT:
        state_log.append(make_state_event(result=result,to_state=ValidityState.REVIEW_REQUIRED,current_state=current,
            actor_type=ActorType.SERVICE,actor_id=config['trusted_keys'][signer.key_id]['actor'],trigger=TransitionTrigger.GOVERNANCE_CHANGE,
            reason='Bound inputs or approved operating configuration changed; original result preserved',trigger_id=change_id,prev_hash=state_log.last_hash()))
    job={'job_id':change_id,'source_result_id':result.result_id,'state':'REASSESSMENT_REQUIRED','state_event_hash':next(e.event_hash for e in reversed(state_log.read()) if e.result_id==result.result_id),'change':change,
         'next_action':'Create a newly authorized investigation revision; never mutate the signed prior result.'}
    journal.append(change_id,'reassessment_requested',job,signer,'executor')
    return job


def check_changes(config,root,iid,engine,journal,signer):
    from .qualification import fingerprint
    binding=journal.latest('binding');changes={}
    if binding and binding['payload']['fingerprint']!=fingerprint(config):
        bound,current=binding['payload']['fingerprint'],fingerprint(config)
        changes['operating_configuration']=sorted(k for k in set(bound)|set(current) if bound.get(k)!=current.get(k)) or ['unspecified']
    evidence=journal.latest('evidence_manifest')
    if evidence:
        expected={row[0]:row[1] for row in evidence['payload']['evidence']}
        for collector in config.get('collectors',[]):
            allowed=(root/collector['root']).resolve();path=(allowed/collector['path']).resolve()
            if not path.is_relative_to(allowed):raise ValueError('collector path escaped approved root')
            actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'UNAVAILABLE'
            for segment in collector['segments']:
                if segment['evidence_id'] in expected and actual!=expected[segment['evidence_id']]:changes[segment['evidence_id']]=actual
        if config.get('periodic_evidence'):
            from governance.operations.runtime import periodic_folder
            folder=periodic_folder(config,root,engine.snapshot(iid)[1]['understand'].scope)
            for item in config['periodic_evidence']['evidence']:
                path=folder/item['file']
                actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'UNAVAILABLE'
                if item['evidence_id'] in expected and actual!=expected[item['evidence_id']]:changes[item['evidence_id']]=actual
    return {'status':'INPUT_CHANGE_DETECTED','changes':changes,'reassessment':flag_changed(config,root,journal,signer,changes)} if changes else {'status':'NO_BOUND_CHANGE_DETECTED','limitation':'Only configured local inputs/configuration were checked; no universal regulator or system monitoring.'}
