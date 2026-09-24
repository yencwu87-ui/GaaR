"""Additional read-only checks; absence of records is not proof of breach."""


def change_authorization(package):
    from governance.investigation.change_test import reconcile_changes
    result=reconcile_changes(package)
    if result['status']!='COMPUTED_ON_SUPPLIED_EXPORTS':return result
    gaps=[];discrepancies=[]
    absence={'NO_MATCHING_APPROVED_TICKET','APPROVAL_NOT_ESTABLISHED','PRIVILEGE_NOT_ESTABLISHED','RECOVERY_NOT_ESTABLISHED','FREEZE_WITHOUT_PRIOR_EXCEPTION'}
    changes={c['event_id']:c for c in package['changes']}
    for f in result.pop('findings'):
        if f['code'] in absence or (f['code']=='IMPLEMENTATION_CONTENT_MISMATCH' and not changes[f['event_id']].get('actual_spec_hash')):gaps.append(f)
        else:discrepancies.append(f)
    result.update(schema='change-authorization.2',findings=discrepancies,assurance_gaps=gaps,
                  conclusion='ADVERSE' if discrepancies else 'INCONCLUSIVE' if gaps else 'SUPPORTED_WITHIN_SUPPLIED_RECORD_SCOPE')
    return result


def change_population(package):
    from governance.investigation.change_test import _time
    if not package.get('scope') or not package.get('as_of'):raise ValueError('scope/time required')
    _time(package['as_of']);sets=[];sources=[]
    for name in ('primary','independent'):
        export=package.get(name)
        if not export or export.get('complete') is not True:return {'status':'NOT_COMPARABLE','reason':name+' collection completeness unavailable'}
        if export.get('scope')!=package['scope'] or export.get('as_of')!=package['as_of']:raise ValueError('population scope/time mismatch')
        if not export.get('source_id'):raise ValueError('population provenance missing')
        ids=export.get('event_ids')
        if not isinstance(ids,list) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):raise ValueError('invalid/duplicate event identity')
        sources.append(export['source_id']);sets.append(set(ids))
    if len(set(sources))!=2:raise ValueError('independent population must identify a different source')
    missing_primary=sorted(sets[1]-sets[0]);missing_independent=sorted(sets[0]-sets[1])
    return {'status':'COMPUTED_ON_SUPPLIED_EXPORTS','schema':'change-population.1','findings':[],
        'assurance_gaps':[{'code':'COLLECTION_POPULATION_DISAGREEMENT','missing_primary':missing_primary,'missing_independent':missing_independent}] if missing_primary or missing_independent else [],
        'metrics':{'primary':len(sets[0]),'independent':len(sets[1])},
        'limitation':'Distinct source IDs do not alone prove collection independence, authenticity or complete discovery.',
        'changes_control_verdict':False}

def change_segregation(package):
    """Segregation of duties: the approver of a change must not be the person who implemented it.

    Read-only and deterministic. A ticket that names the implementer as its own
    approver is positive evidence that the independence requirement was not met,
    so it is a discrepancy, not an assurance gap. Changes without a matching
    approved ticket are left to change_authorization, which already reports them.
    """
    from governance.investigation.change_test import _time
    if not package.get('scope') or not package.get('as_of'):raise ValueError('scope/time required')
    _time(package['as_of'])
    tickets={t.get('ticket_id'):t for t in package.get('tickets',[]) if t.get('ticket_id')}
    findings=[]
    for change in package.get('changes',[]):
        ticket=tickets.get(change.get('ticket_id'))
        approver=(ticket or {}).get('approved_by') or ''
        if ticket and approver and approver==change.get('actor_id'):
            findings.append({'code':'SELF_APPROVAL','event_id':change.get('event_id'),'ticket_id':ticket['ticket_id'],
                             'approver':approver,'implementer':change.get('actor_id')})
    return {'status':'COMPUTED_ON_SUPPLIED_EXPORTS','schema':'change-segregation.1','scope':package['scope'],
            'as_of':package['as_of'],'findings':findings,'assurance_gaps':[],'observations':[],
            'changes_examined':len(package.get('changes',[])),
            'conclusion':'ADVERSE' if findings else 'SUPPORTED_WITHIN_SUPPLIED_RECORD_SCOPE'}


def change_coverage(package):
    """How many records each change check actually applied to — a coverage statement, not a finding.

    Mirrors the applicability conditions of change_authorization v2 and change_segregation v1 without
    changing either. Reports NOT_COMPARABLE when the export is not declared complete, so no obligation
    can be read as clean on an incomplete collection.
    """
    from governance.investigation.change_test import _time
    if not package.get('scope') or not package.get('as_of'):raise ValueError('scope/time required')
    collection=package.get('collection') or {}
    if collection.get('complete') is not True or not collection.get('source_ids'):
        return {'status':'NOT_COMPARABLE','schema':'change-coverage.1','reason':'collection not declared complete'}
    tickets={t.get('ticket_id'):t for t in package.get('tickets',[]) if t.get('ticket_id')}
    policy=package.get('policy') or {}
    counts={code:0 for code in ('NO_MATCHING_APPROVED_TICKET','PRIVILEGE_NOT_ESTABLISHED','APPROVAL_NOT_ESTABLISHED',
            'OUTSIDE_APPROVED_WINDOW','DEVIATES_FROM_APPROVED_SCOPE','IMPLEMENTER_NOT_APPROVED',
            'CREDENTIAL_NOT_APPROVED_FOR_CHANGE','APPROVAL_AFTER_EXECUTION','SELF_APPROVAL',
            'IMPLEMENTATION_CONTENT_MISMATCH','FREEZE_WITHOUT_PRIOR_EXCEPTION','RECOVERY_NOT_ESTABLISHED')}
    changes=package.get('changes',[])
    for change in changes:
        when=_time(change['occurred_at'])
        counts['NO_MATCHING_APPROVED_TICKET']+=1
        counts['PRIVILEGE_NOT_ESTABLISHED']+=1
        ticket=tickets.get(change.get('ticket_id'))
        if ticket is not None:
            for code in ('APPROVAL_NOT_ESTABLISHED','OUTSIDE_APPROVED_WINDOW','DEVIATES_FROM_APPROVED_SCOPE',
                         'IMPLEMENTER_NOT_APPROVED','CREDENTIAL_NOT_APPROVED_FOR_CHANGE'):
                counts[code]+=1
            if ticket.get('approved_by') and ticket.get('approved_at') and ticket.get('status')=='approved':
                counts['APPROVAL_AFTER_EXECUTION']+=1
            if ticket.get('approved_by'):
                counts['SELF_APPROVAL']+=1
            if ticket.get('approved_spec_hash'):
                counts['IMPLEMENTATION_CONTENT_MISMATCH']+=1
        if any(change.get('asset_id') in f.get('targets',[]) and _time(f['start'])<=when<_time(f['end'])
               for f in package.get('freezes',[])):
            counts['FREEZE_WITHOUT_PRIOR_EXCEPTION']+=1
        if change.get('outcome')=='failed' and policy.get('failed_change_requires_recovery') is True:
            counts['RECOVERY_NOT_ESTABLISHED']+=1
    return {'status':'COMPUTED_ON_SUPPLIED_EXPORTS','schema':'change-coverage.1','scope':package['scope'],
            'as_of':package['as_of'],'changes':len(changes),'change_ids':sorted(c.get('event_id') for c in changes),
            'applied_to':counts}


PROCEDURES={('change_authorization','2'):change_authorization,('change_population','1'):change_population,
            ('change_segregation','1'):change_segregation,('change_coverage','1'):change_coverage}
