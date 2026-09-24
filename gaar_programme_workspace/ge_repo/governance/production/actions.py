"""Local governed remediation records and notification drafts. Never sends messages."""
from governance.investigation.store import digest
from .qualification import signed_document


def open_actions(config,iid,engine,journal,signer):
    _,values=engine.snapshot(iid);ctx=values['understand'];owners=config.get('action_owners',{})
    findings=[(h.hypothesis_id,h.claim) for h in values['explain'].hypotheses if h.material]
    findings += [(f.finding_id,f.claim) for f in values['challenge'].findings if f.material]
    result=[]
    for ref,claim in findings:
        action_id='ACTION-'+digest({'investigation_id':iid,'risk_ref':ref})
        existing=next((e for e in journal.read() if e['event_key']==action_id),None)
        if existing:result.append(existing['payload']);continue
        owner=owners.get(ctx.control_id)
        trusted=any(p.get('actor')==owner and 'action_owner' in p.get('roles',[]) for p in config['trusted_keys'].values())
        auto=config['trusted_keys'][signer.key_id].get('allow_action_assignment') is True
        action={'action_id':action_id,'investigation_id':iid,'risk_ref':ref,'claim':claim,'system_id':ctx.scope.system_id,
                'control_id':ctx.control_id,'framework':ctx.framework,'owner':owner if trusted and auto else None,
                'status':'OPEN' if trusted and auto else 'OWNER_ASSIGNMENT_REQUIRED','delivery':'LOCAL_ONLY',
                'required_closure_tools':config.get('closure_tools_by_control',{}).get(ctx.control_id,[])}
        journal.append(action_id,'remediation_opened',action,signer,'executor')
        journal.append(action_id+':notice','notification_draft',{'action_id':action_id,'owner':action['owner'],'message':'Material finding requires governed disposition: '+claim,'delivery':'NOT_SENT'},signer,'executor')
        result.append(action)
    return result


def close_action(config,root,journal,action_id,approval_path,verification_engine,executor):
    action_event=next((e for e in journal.read() if e['kind']=='remediation_opened' and e['payload']['action_id']==action_id),None)
    if not action_event:raise ValueError('unknown remediation action')
    action=action_event['payload'];approval,owner,document=signed_document(approval_path,config['trusted_keys'],'action_owner',True)
    if approval.get('action_id')!=action_id or approval.get('action_event_hash')!=action_event['event_hash'] or owner['actor']!=action.get('owner'):raise ValueError('closure is not authorized by the assigned owner for this action version')
    rows,values=verification_engine.snapshot(approval['verification_investigation_id'],approval['verification_head'])
    ctx=values['understand']
    if ctx.synthetic or ctx.scope.system_id!=action['system_id'] or ctx.control_id!=action['control_id'] or ctx.framework!=action['framework']:raise ValueError('closure proof does not match real system/control scope')
    if approval['verification_investigation_id']==action['investigation_id']:raise ValueError('closure needs fresh verification, not the original failing investigation')
    if not action['required_closure_tools']:raise ValueError('approved closure test policy missing')
    executed={t.test_id:t for t in values['verify'].tests};selected=[executed[t] for t in approval['test_ids']]
    if not set(action['required_closure_tools'])<={t.tool for t in selected}:raise ValueError('required closure procedures omitted')
    import json
    for test in selected:
        if test.status!='EXECUTED' or test.tool not in {'change_authorization','change_population','m36_model_evaluation','m36_representativeness','m36_independent_validation','m36_residual_risk'}:raise ValueError('unsupported or unexecuted closure proof')
        result=json.loads(test.result_json)
        if result.get('findings') or result.get('assurance_gaps'):raise ValueError('closure verification still has findings or gaps')
    verifier=next(r for r in rows if r['stage']=='verify');identity=config['trusted_keys'][verifier['key_id']]
    if owner['actor']==identity['actor'] or owner['public_key']==identity['public_key']:raise ValueError('closure verification must be independent of action owner')
    event=journal.append(action_id+':closed','remediation_closed',{'action_id':action_id,'status':'CLOSED','owner_approval':document,'verification_head':approval['verification_head'],'test_ids':approval['test_ids'],'deployment_authorized':False},executor,'executor')
    return event['payload']
