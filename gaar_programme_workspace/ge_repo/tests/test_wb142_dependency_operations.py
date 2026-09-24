"""Software acceptance tests; not auditor-judgment performance claims."""
import json
import pytest
from governance.investigation.dependencies import investigate,load
from governance.operations.stage_evaluation import score,evaluate


def test_change_has_required_investigation_relationships():
    result=investigate('INTERNAL','CHANGE.MGMT')
    nodes={n for e in result['edges'] for n in (e['upstream'],e['downstream'])}
    assert {'ACCESS.PRIVILEGED','LOGGING.COVERAGE','CHANGE.APPROVAL','CHANGE.FREEZE','INCIDENT.RESPONSE','SERVICE.RECOVERY'}<=nodes
    assert result['changes_control_verdict'] is False
    assert all(e['alternatives'] and e['evidence_required'] and e['non_inference'] for e in result['edges'])

def test_frameworks_do_not_silently_cross():
    assert investigate('MAS','CHANGE.MGMT')['edges']==[]
    assert all(e['framework']=='MAS' for e in investigate('Control Library - MAS','M3.12')['edges'])

def test_bounded_cycle_does_not_duplicate_or_loop():
    result=investigate('MAS','M3.12',max_depth=3,max_edges=2)
    assert len(result['edges'])==2 and result['edge_budget_exhausted']
    assert len({e['edge_id'] for e in result['edges']})==2

def test_missing_catalogue_not_empty_success(tmp_path):
    with pytest.raises(FileNotFoundError):investigate('MAS','M3.6',path=tmp_path/'missing')

def test_duplicate_and_self_approved_edges_rejected(tmp_path):
    book,_=load();p=tmp_path/'graph.json'
    book['edges'].append(book['edges'][0]);p.write_text(json.dumps(book))
    with pytest.raises(ValueError,match='duplicate'):load(p)
    book['edges'].pop();book['edges'][0]['review_status']='APPROVED';p.write_text(json.dumps(book))
    with pytest.raises(ValueError,match='self-approve'):load(p)

def test_version_pin_changes_with_content(tmp_path):
    book,first=load();p=tmp_path/'graph.json';book['edges'][0]['relation']+=' Revised.';p.write_text(json.dumps(book))
    assert load(p)[1]!=first

def test_engine_policy_requires_dependency_review(tmp_path):
    from tools.wb140_demo import fixture_environment,prepare
    from governance.investigation.agents import challenge,conclude_blocked_by_policy
    from governance.investigation.contracts import ChallengeRecord
    engine,signers=fixture_environment(tmp_path)
    engine.store.trust[signers['assessor'].key_id]['require_dependency_review']=True
    iid=prepare(engine,signers)
    engine.execute_plan(iid,signers['executor'])
    ctx=engine.challenge_input(iid)
    proposal=ChallengeRecord(input_head=ctx['input_head'],status='COMPLETED',disproof_attempts=('Reviewed supplied test and alternative explanations',),findings=(),reviewed_refs=('E1','E2','H1','T1'))
    challenge(engine,iid,signers['challenger'],invoke=lambda _:proposal.model_dump_json())
    conclude_blocked_by_policy(engine,iid,signers['decision'])
    assert 'dependency_review_missing_or_unavailable' in engine.gate(iid)['blockers']

@pytest.mark.parametrize('stage,field',[('examine','findings'),('explain','hypotheses'),('challenge','findings')])
def test_stage_metrics_capture_material_omissions(stage,field):
    r=score(stage,{field:[{'id':'a','evidence_refs':['invented'],'status':'SUPPORTED'}]},
       {'required_ids':['a','b'],'material_ids':['b'],'expected_fields':{'a':{'status':'NOT_EVIDENCED'}}},['real'])
    assert r['required_item_recall']==0.5 and r['invented_reference_count']==1
    assert r['missed_material_ids']==['b'] and r['field_mismatches']==['a:status']
    assert r['semantic_review']=='PENDING_INDEPENDENT_REVIEW'

def test_planning_priority_and_fake_execution_detected():
    r=score('plan',{'tests':[{'id':'low','evidence_refs':[],'execution_status':'EXECUTED'}]},
      {'required_ids':['high'],'acceptable_first_test_ids':['high']},[])
    assert r['unexecuted_claimed_executed']==1 and not r['first_test_decision_impact_correct']

def test_empty_evaluation_does_not_pass(tmp_path):
    assert evaluate({},tmp_path)['status']=='NOT_EVALUATED'
    with pytest.raises(ValueError,match='empty rubric'):score('examine',{'findings':[]},{'required_ids':[]},[])

def test_resolver_exposes_version_and_structured_dependencies(tmp_path):
    from tools.wb140_demo import fixture_environment,prepare
    from governance.knowledge_resolver import resolve_investigation
    engine,signers=fixture_environment(tmp_path);iid=prepare(engine,signers,stop='examine',scenario='change')
    # Demo framework stays separate; no generic alias silently grants applicability.
    bundle=resolve_investigation(engine,iid,'What could invalidate this conclusion?')
    lane=next(x for x in bundle['lanes'] if x['name']=='dependencies')
    assert lane['status']=='COMPLETED' and any(x.startswith('knowledge-sha256:') for x in lane['refs'])
    assert bundle['dependency_search']['knowledge_sha256']

def test_private_key_file_can_replace_repeated_shell_exports(tmp_path):
    from governance.operations.secrets import private_seed
    p=tmp_path/'key';p.write_text('operator-provided-secret');p.chmod(0o600)
    assert private_seed({'private_key_file':'key'},tmp_path)=='operator-provided-secret'
    p.chmod(0o644)
    with pytest.raises(ValueError,match='chmod 600'):private_seed({'private_key_file':'key'},tmp_path)

def test_private_key_final_symlink_rejected(tmp_path):
    from governance.operations.secrets import private_seed
    p=tmp_path/'key';p.write_text('secret');p.chmod(0o600);(tmp_path/'link').symlink_to(p)
    with pytest.raises(OSError):private_seed({'private_key_file':'link'},tmp_path)
