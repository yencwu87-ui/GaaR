"""Offline protocol/recovery/security checks. Scripted calls are NOT live judgment proof."""
import copy,json,os,sqlite3,subprocess,sys,zipfile
from pathlib import Path
import pytest
from governance.investigation import InvestigationEngine,InvestigationStore,admit_segments
from governance.investigation.contracts import ApplicableExpectations, ChallengeRecord, Dependency, Expectation, Explanation, ExplanationSet, InvestigationContext, RetrievalLane, Scope, TestPlan as ContractTestPlan, TestProposal as ContractTestProposal
from governance.investigation.store import digest,canonical
from governance.production.journal import Journal,exclusive
from governance.production.orchestrator import CheckpointEngine,reconcile,run,case_directory
from governance.production.dependencies import Review,Treatment,validate
from governance.production.procedures import change_authorization,change_population
from governance.production.qualification import check as quality


def environment(tmp_path,monkeypatch,seal_fixture=False):
    from tools.wb140_demo import fixture_environment
    from tools.wb140_change_fixture import package
    old,signers=fixture_environment(tmp_path)
    trust=old.store.trust
    trust[signers['assessor'].key_id].update(require_dependency_review=True,require_integrated_gate=True)
    trust[signers['test_planner'].key_id]['required_tools_by_control']={'CHANGE.MGMT':[['change_authorization','2'],['change_population','1']]}
    if seal_fixture:
        # Test-only trusted identities and a non-synthetic flag exercise guards;
        # inputs/inference remain fixtures and cannot establish production proof.
        trust[signers['owner'].key_id].update(actor_type='human',roles=['owner','result_approver'])
        trust[signers['executor'].key_id]['roles'].append('result_sealer')
        signers['result_sealer']=signers['executor']
    engine=InvestigationEngine(InvestigationStore(tmp_path/'main.sqlite',trust),old.source_registry)
    scope=Scope(system_id='credit-platform-v2.3',version='2.3',period='2026-09-20T00:00:00Z')
    iid='PROGRAMME-TEST'
    engine.append(iid,'understand',InvestigationContext(investigation_id=iid,framework='INTERNAL',control_id='CHANGE.MGMT',requirement_version='demo-v1',scope=scope,
                  boundary='Scripted offline protocol fixture only',owner=trust[signers['owner'].key_id]['actor'],criticality='high',synthetic=not seal_fixture),signers['owner'])
    source=old.source_registry['INTERNAL-DEMO']
    engine.append(iid,'expectations',ApplicableExpectations(requirement_version='demo-v1',elements=(Expectation(element_id='e1',text='Verify actual changes against authorization',source_id='INTERNAL-DEMO',source_sha256=source['sha256'],source_version=source['version'],authority='internal',purpose='operating',applies=True,applicability_reason='Offline protocol fixture'),)),signers['governance'])
    package_data=package();package_data.update(scope=scope.system_id,as_of=scope.period)
    population={'scope':scope.system_id,'as_of':scope.period,'primary':{'scope':scope.system_id,'as_of':scope.period,'complete':True,'source_id':'one','event_ids':['c1']},'independent':{'scope':scope.system_id,'as_of':scope.period,'complete':True,'source_id':'two','event_ids':['c1']}}
    collectors=[]
    for eid,data in [('E1',package_data),('E2',population)]:
        raw=canonical(data).encode();(tmp_path/(eid+'.json')).write_bytes(raw)
        import hashlib
        collectors.append({'root':'.','path':eid+'.json','source_id':eid,'sha256':hashlib.sha256(raw).hexdigest(),'scope':scope.model_dump(),'authority':'internal','provenance':['explicit-scripted-test'],
                           'segments':[{'start':0,'end':len(raw.decode()),'evidence_id':eid,'element_ids':['e1'],'purposes':['operating_record']}]})
    config={'store':'main.sqlite','programme_dir':'programme','trusted_keys':trust,'sources':old.source_registry,'signers':{role:{'key_id':signer.key_id} for role,signer in signers.items()},
            'models':{stage:{'provider':'ollama','base_url':'http://127.0.0.1:11434','model':'SCRIPTED_TEST'} for stage in ['examine','explain','plan','challenge']},
            'expected_heads':{iid:engine.snapshot(iid)[0][-1]['record_hash']},'collectors':collectors,'operation_mode':'evaluation',
            'result_store':'results.jsonl','result_state_log':'result_states.jsonl'}
    import governance.production.orchestrator as orchestrator
    monkeypatch.setattr(orchestrator,'signers_for',lambda config,root:signers)
    # These two boundaries explicitly isolate unavailable operator services/authority.
    monkeypatch.setattr(orchestrator,'doctor',lambda config,root:{'blockers':[],'checks':{}})
    import governance.production.precedents as precedents
    monkeypatch.setattr(precedents,'providers',lambda *args:{'precedents':lambda q:[]})
    calls=[]
    def invoke(client,prompt):
        calls.append(client.stage);p=json.loads(prompt)
        if client.stage=='examine':return canonical({'evidence':p['admitted_evidence'],'findings':[{'element_id':'e1','status':'CONTRADICTED','evidence_refs':['E1','E2'],'rationale':'Observed supplied-record discrepancies'}]})
        if client.stage=='explain':
            return ExplanationSet(status='COMPLETED',retrieval=tuple(RetrievalLane(name=n,status='COMPLETED') for n in ['expectations','facts','dependencies','counterevidence','procedures','precedents']),
                dependencies=(Dependency(dependency_id='D1',upstream='CHANGE.MGMT',downstream='ACCESS.PRIVILEGED',relation='Scope of actual privileged credentials needs verification',basis_refs=('E1',),status='hypothesis'),),
                hypotheses=(Explanation(hypothesis_id='H1',claim='Actual changes may exceed recorded authority',basis_refs=('E1',),alternatives=('Approved emergency authorization','Clock discrepancy'),compensating_controls_review='Inspect recorded exceptions and independent audit events',dependencies=('D1',),material=True),),limitations=('Scripted software protocol test',)).model_dump_json()
        if client.stage=='plan':
            return ContractTestPlan(policy_id='fixture-policy',tests=tuple(ContractTestProposal(test_id=tid,hypothesis_id='H1',tool=tool,version=version,input_ref=eid,decision_impact='Discriminate record discrepancy from incomplete collection',priority=i+1,required=True) for i,(tid,tool,version,eid) in enumerate([('T1','change_authorization','2','E1'),('T2','change_population','1','E2')]))).model_dump_json()
        if client.stage=='dependency_review':
            return Review(knowledge_sha256=p['knowledge']['knowledge_sha256'],treatments=[Treatment(edge_id=e['edge_id'],status='INVESTIGATED',material=True,rationale='Protocol fixture binds actual supplied exports to executed comparisons',evidence_refs=['E1','E2'],test_refs=['T1','T2'],risk_refs=['H1']) for e in p['knowledge']['edges']]).model_dump_json()
        if client.stage=='challenge':return ChallengeRecord(status='COMPLETED',input_head=p['investigation']['input_head'],reviewed_refs=('E1','E2','H1','T1','T2'),disproof_attempts=('Examined timing/authorization alternatives and dependency treatments',)).model_dump_json()
        raise AssertionError(client.stage)
    monkeypatch.setattr(orchestrator.LiveClient,'__call__',invoke)
    return config,engine,signers,iid,calls


def test_integrated_change_run_and_idempotent_resume(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    report=run(config,tmp_path,iid)
    assert report['checkpoint']=='EVALUATION_COMPLETE',report
    assert not report['gate']['assessment_finalizable'] and not report['deployment_authorized']
    assert calls==['examine','explain','plan','dependency_review','challenge']
    assert run(config,tmp_path,iid)==report
    assert len(calls)==5
    assert len(engine.snapshot(iid)[0])==8
    assert 'integrated_gate_required' in engine.gate(iid)['blockers']
    assert report['actions'][0]['delivery']=='LOCAL_ONLY'


def test_production_cannot_use_unqualified_model(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch);config['operation_mode']='production'
    result=run(config,tmp_path,iid)
    assert result['request']['kind']=='AuthorizationRequest' and result['request']['stage']=='qualification'
    assert not calls and len(engine.snapshot(iid)[0])==2


def test_missing_evidence_returns_precise_request(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch);config['collectors']=[]
    result=run(config,tmp_path,iid)
    assert result['request']['kind']=='EvidenceRequest' and result['request']['scope']['system_id']
    assert not calls


def test_crash_after_stage_append_recovers_without_reinference(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    original=Journal.append
    def crash(self,key,kind,payload,signer,role):
        if key=='examine:commit':raise OSError('simulated power loss after signed stage write')
        return original(self,key,kind,payload,signer,role)
    monkeypatch.setattr(Journal,'append',crash)
    first=run(config,tmp_path,iid);assert first['checkpoint']=='ACTION_REQUIRED'
    assert len(engine.snapshot(iid)[0])==3
    monkeypatch.setattr(Journal,'append',original)
    second=run(config,tmp_path,iid)
    assert second['checkpoint']=='EVALUATION_COMPLETE',second
    assert calls.count('examine')==1


def test_changed_evidence_requires_new_revision(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch);run(config,tmp_path,iid)
    (tmp_path/'E1.json').write_text('{}')
    result=run(config,tmp_path,iid)
    assert result['request']['stage']=='reassessment'
    assert len(calls)==5


def test_signed_journal_rejects_role_abuse_and_rollback(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    journal=Journal(tmp_path/'secure.sqlite',config['trusted_keys'])
    with pytest.raises(ValueError,match='untrusted'):journal.append('fake','result_current',{},signers['assessor'],'assessor')
    journal.append('binding','binding',{'x':1},signers['executor'],'executor')
    with sqlite3.connect(journal.path) as db:
        db.execute('DROP TRIGGER entries_no_delete');db.execute('DELETE FROM entries')
    with pytest.raises(ValueError,match='rollback'):journal.read()


def test_backup_restore_and_tamper_detection(tmp_path,monkeypatch):
    from governance.production.assurance import backup,restore_verify
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch);run(config,tmp_path,iid)
    journal=Journal(case_directory(config,tmp_path,iid)/'operations.sqlite',config['trusted_keys'])
    result=backup(config,tmp_path,iid,engine,journal,signers['executor'],tmp_path/'backup.zip')
    restored=restore_verify(tmp_path/'backup.zip',config['trusted_keys'],tmp_path/'restore')
    assert restored['status']=='VERIFIED_IN_NEW_DIRECTORY' and not restored['production_restored']
    with zipfile.ZipFile(tmp_path/'backup.zip') as z,zipfile.ZipFile(tmp_path/'bad.zip','w') as bad:
        for n in z.namelist():bad.writestr(n,b'changed' if n=='operations.anchor.json' else z.read(n))
    with pytest.raises(ValueError,match='hash mismatch'):restore_verify(tmp_path/'bad.zip',config['trusted_keys'],tmp_path/'bad_restore')


def test_change_absence_stays_gap_and_population_mismatch_not_breach():
    from tools.wb140_change_fixture import package
    p=package();p['tickets']=[];result=change_authorization(p)
    assert any(f['code']=='NO_MATCHING_APPROVED_TICKET' for f in result['assurance_gaps'])
    assert all(f['code']!='NO_MATCHING_APPROVED_TICKET' for f in result['findings'])
    p={'scope':'s','as_of':'2026-09-20T00:00:00Z'}
    for name,ids in [('primary',['a']),('independent',['b'])]:p[name]={'scope':p['scope'],'as_of':p['as_of'],'complete':True,'source_id':name,'event_ids':ids}
    result=change_population(p)
    assert result['assurance_gaps'] and not result['findings']


def test_lock_blocks_concurrent_run(tmp_path):
    with exclusive(tmp_path/'lock'):
        with pytest.raises(RuntimeError,match='Another run'):
            with exclusive(tmp_path/'lock'):pass


def test_missing_precedent_search_blocks_not_false_green(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    import governance.production.precedents as p
    monkeypatch.setattr(p,'providers',lambda *args:{})
    report=run(config,tmp_path,iid)
    assert report['checkpoint']=='QUALITY_GATE_BLOCKED'
    assert 'retrieval:precedents:NOT_EVALUATED' in report['gate']['blockers']


def test_pending_signed_proposal_recovers_without_new_inference(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    original=InvestigationEngine.append
    def crash(self,iid,stage,payload,signer):
        if stage=='examine':raise OSError('power loss after intent, before stage')
        return original(self,iid,stage,payload,signer)
    monkeypatch.setattr(InvestigationEngine,'append',crash)
    assert run(config,tmp_path,iid)['checkpoint']=='ACTION_REQUIRED'
    assert len(engine.snapshot(iid)[0])==2
    monkeypatch.setattr(InvestigationEngine,'append',original)
    assert run(config,tmp_path,iid)['checkpoint']=='EVALUATION_COMPLETE'
    assert calls.count('examine')==1


def test_omitted_dependency_and_unexecuted_test_rejected(tmp_path,monkeypatch):
    from governance.investigation.dependencies import investigate
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch);run(config,tmp_path,iid)
    journal=Journal(case_directory(config,tmp_path,iid)/'operations.sqlite',config['trusted_keys'])
    review=Review.model_validate(journal.latest('dependency_review')['payload']['review'])
    values=engine.snapshot(iid)[1];knowledge=investigate('INTERNAL','CHANGE.MGMT')
    with pytest.raises(ValueError,match='exactly one'):validate(review.model_copy(update={'treatments':review.treatments[:-1]}),knowledge,values)
    first=review.treatments[0].model_copy(update={'test_refs':[]})
    with pytest.raises(ValueError,match='executed tests'):validate(review.model_copy(update={'treatments':[first]+review.treatments[1:]}),knowledge,values)


def test_collector_blocks_unapproved_endpoint_before_network(tmp_path,monkeypatch):
    from governance.production.collectors import collect_all
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    config['trusted_keys'][signers['executor'].key_id]['allow_readonly_collectors']=True
    config['http_collectors']=[{'url':'http://unapproved.invalid','allowed_hosts':['approved.invalid']}]
    journal=Journal(tmp_path/'http.sqlite',config['trusted_keys'])
    with pytest.raises(ValueError,match='HTTPS'):collect_all(config,tmp_path,engine.snapshot(iid)[1]['understand'].scope,journal,signers['executor'])


def test_evaluation_requires_independent_corpus_and_scores_real_fields(tmp_path):
    from governance.production.evaluation import evaluate,predicate
    assert evaluate({},tmp_path)['status']=='NOT_EVALUATED'
    assert predicate({'findings':[{'status':'MISSING'}]},{'path':['findings','0','status'],'operator':'equals','value':'MISSING'})
    assert not predicate({'findings':[]},{'path':['findings','0','status'],'operator':'equals','value':'SUPPORTED'})


def test_signed_result_seals_once_and_change_never_repromotes(tmp_path,monkeypatch):
    import governance.production.orchestrator as orch
    import governance.production.lifecycle as life
    from governance.production.qualification import fingerprint
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch,seal_fixture=True)
    config['operation_mode']='production'
    qualified={'status':'QUALIFIED','fingerprint':fingerprint(config)}
    monkeypatch.setattr(orch,'qualification_check',lambda *args:qualified)
    monkeypatch.setattr(life,'check_qualification',lambda *args:qualified)
    monkeypatch.setattr(life,'actor_signer',lambda c,r,role:signers[role])
    result=run(config,tmp_path,iid)
    assert result['checkpoint']=='COMPLETE',result
    rows,values=engine.snapshot(iid)
    payload={'investigation_id':iid,'investigation_head':rows[-1]['record_hash'],'decision':'FAIL','decision_id':'TEST-APPROVAL',
             'at':'2026-09-20T00:00:00Z','rationale':'Test-only adverse decision; not production proof'}
    approver=signers['owner'];doc={'payload':payload,'key_id':approver.key_id,'signature':approver.sign(canonical(payload).encode())}
    (tmp_path/'approval.json').write_text(canonical(doc));config['result_decisions']={iid:'approval.json'}
    journal=Journal(case_directory(config,tmp_path,iid)/'operations.sqlite',config['trusted_keys'])
    first=life.seal(config,tmp_path,iid,engine,journal)
    assert first['state']=='CURRENT' and first['decision']=='FAIL' and not first['deployment_authorized']
    assert life.seal(config,tmp_path,iid,engine,journal)==first
    events=journal.read()
    assert sum(e['kind']=='result_sealed' for e in events)==1
    assert sum(e['kind']=='result_current' for e in events)==1
    from governance.result_contract import ResultStateLog
    state_log=ResultStateLog(tmp_path/config.get('result_state_log','../var/programme_result_states.jsonl'))
    assert sum(e.result_id==first['result_id'] for e in state_log.read())==1
    from governance.result_contract import GovernanceResult,verify_signature
    stored=GovernanceResult.model_validate(journal.latest('result_sealed')['payload']['result'])
    assert stored.result_id==first['result_id']
    (tmp_path/'E1.json').write_text('{}')
    changed=life.check_changes(config,tmp_path,iid,engine,journal,signers['executor'])
    assert changed['status']=='INPUT_CHANGE_DETECTED'
    with pytest.raises(ValueError,match='reassessment'):life.seal(config,tmp_path,iid,engine,journal)
    assert journal.latest('reassessment_requested')['payload']['source_result_id']==first['result_id']


def test_source_internal_requires_human_and_cannot_claim_binding(tmp_path,monkeypatch):
    from governance.operations.sources import validate_source
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    signer=signers['governance'];trust=config['trusted_keys'];trust[signer.key_id]['actor_type']='human'
    import hashlib
    raw=b'Approved internal change policy for scoped execution';(tmp_path/'policy.txt').write_bytes(raw)
    entry={'issuer':'INTERNAL','source_id':'POLICY','sha256':hashlib.sha256(raw).hexdigest(),'version':'v1','authority':'internal','snapshot_path':'policy.txt','authority_decision_ref':'decision.json','approved_by':trust[signer.key_id]['actor']}
    payload={k:entry[k] for k in ('source_id','sha256','authority','version')}
    (tmp_path/'decision.json').write_text(canonical({'payload':payload,'key_id':signer.key_id,'signature':signer.sign(canonical(payload).encode())}))
    assert validate_source(entry,tmp_path,trust)
    with pytest.raises(ValueError,match='regulatory'):validate_source({**entry,'authority':'binding'},tmp_path,trust)
    trust[signer.key_id]['actor_type']='service'
    with pytest.raises(ValueError,match='approval role'):validate_source(entry,tmp_path,trust)


def test_wrong_qualification_signature_cannot_unlock(tmp_path,monkeypatch):
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    signer=signers['owner'];config['trusted_keys'][signer.key_id].update(roles=['owner','quality_approver'],actor_type='human')
    (tmp_path/'quality.json').write_text(canonical({'key_id':signer.key_id,'payload':{},'signature':'invalid'}));config['qualification_report']='quality.json'
    assert quality(config,tmp_path)['status']=='NOT_QUALIFIED'


def test_single_run_page_reports_missing_setup_without_exception(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('WB_INVESTIGATION_CONFIG',raising=False)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'tools/gaar_run_app.py')).run(timeout=10)
    assert not app.exception
    assert any('No authorized assessments' in w.value for w in app.warning)


def test_reviewer_trace_verifies_stage_and_operational_chains(tmp_path,monkeypatch):
    from governance.trace import build_trace
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    assert run(config,tmp_path,iid)['checkpoint']=='EVALUATION_COMPLETE'
    trace=build_trace(case_directory(config,tmp_path,iid),config['trusted_keys'])
    assert trace['integrity']['signature_status']=='VALID'
    assert trace['integrity']['operations']['status']=='VALID'
    assert trace['integrity']['receipts']['status']=='UNAVAILABLE'
    assert trace['integrity']['overall_status']=='PARTIAL'
    assert trace['verdict']=='ADVERSE' and trace['risks']
    snapshot=case_directory(config,tmp_path,iid)/'investigation.json'
    document=json.loads(snapshot.read_text());document['rows'][2]['payload']['findings'][0]['rationale']='tampered'
    snapshot.write_text(canonical(document))
    assert build_trace(case_directory(config,tmp_path,iid),config['trusted_keys'])['integrity']['overall_status']=='INVALID'


def test_reviewer_app_reports_missing_setup_without_exception(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('WB_INVESTIGATION_CONFIG',raising=False)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app_gaar.py')).run(timeout=10)
    assert not app.exception
    assert any('No authorised assessment' in item.value for item in app.info)


def test_remediation_closure_cannot_invent_an_action(tmp_path,monkeypatch):
    from governance.production.actions import close_action
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    journal=Journal(tmp_path/'actions.sqlite',config['trusted_keys'])
    with pytest.raises(ValueError,match='unknown remediation'):
        close_action(config,tmp_path,journal,'MADE-UP',tmp_path/'no-approval.json',engine,signers['executor'])
    assert journal.read()==[]


def test_evaluation_provisioner_builds_distinct_nonproduction_onramp(tmp_path):
    evidence=tmp_path/'changes.json';evidence.write_text(json.dumps({'scope':'s','as_of':'2026-09-20T00:00:00Z','changes':[]}))
    config=tmp_path/'evaluation.json'
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tools/gaar_provision.py'),
        '--output-config',str(config),'--evidence',str(evidence),'--investigation-id','EVAL-ONE',
        '--system-id','s','--version','v1','--period','2026-09-20T00:00:00Z','--framework','INTERNAL',
        '--control','CHANGE.MGMT','--requirement-version','v1','--requirement','Internal change requirement',
        '--element-id','e1','--element','Observed changes must match prior authorisation','--confirm-evaluation-only'],
        text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    document=json.loads(config.read_text());assert document['operation_mode']=='evaluation'
    assert len({v['key_id'] for v in document['signers'].values()})==8
    assert all(v['actor_type']=='service' for v in document['trusted_keys'].values())
    assert document['collectors'][0]['segments'][0]['start']==0
    assert document['collectors'][0]['segments'][0]['end']==len(evidence.read_text())
    engine=InvestigationEngine(InvestigationStore(tmp_path/document['store'],document['trusted_keys']),document['sources'])
    rows,values=engine.snapshot('EVAL-ONE');assert len(rows)==2 and values['understand'].synthetic
    from governance.operations.runtime import doctor
    checked=doctor(document,tmp_path)
    assert checked['checks']['source:EVAL-EXPECTATION-CHANGE.MGMT']['status']=='AVAILABLE'
    assert checked['checks']['identities']['status']=='AVAILABLE'


def test_trace_receipt_verification_distinguishes_valid_and_tampered(tmp_path,monkeypatch):
    from governance.trace import verify_receipts
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch)
    receipt={'schema':'wb141.live-inference.1','investigation_id':iid,'stage':'examine','provider':'ollama',
             'model':'fixture','base_url':'http://127.0.0.1:11434','started_at':'2026-09-20T00:00:00Z',
             'prompt':'question','prompt_sha256':__import__('hashlib').sha256(b'question').hexdigest(),
             'live':True,'status':'RESPONSE_RECEIVED','response':'{}',
             'response_sha256':__import__('hashlib').sha256(b'{}').hexdigest(),
             'finished_at':'2026-09-20T00:00:01Z','key_id':signers['assessor'].key_id}
    receipt['signature']=signers['assessor'].sign(canonical(receipt).encode())
    assert verify_receipts([receipt],config['trusted_keys'],iid)['status']=='VALID'
    receipt['response']='{"invented":true}'
    checked=verify_receipts([receipt],config['trusted_keys'],iid)
    assert checked['status']=='INVALID' and any('response hash' in p for p in checked['problems'])
