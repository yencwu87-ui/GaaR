"""Software tests, not held-out auditor judgment or production evidence."""
import json
import pytest
from governance.operations.m36 import model_evaluation, representativeness, independent_validation, residual_risk
from governance.operations.live import endpoint, LiveClient
from governance.operations.runtime import collect
from governance.investigation.bridge import required


def package(**updates):
    return dict(scope='s',model_version='1',as_of='2026-09-20T00:00:00Z',source_refs=['export'],criteria_ref='e1',**updates)

@pytest.mark.parametrize('procedure',[model_evaluation,representativeness,independent_validation,residual_risk])
def test_absence_is_gap_not_violation(procedure):
    result=procedure(package())
    assert result['conclusion']=='INCONCLUSIVE'
    assert result['assurance_gaps'] and not result['findings']

def test_recompute_accuracy_and_replay():
    data=package(prediction_records=[dict(sample_id='a',model_version='1',actual_label=1,predicted_label=0)],approved_thresholds={'accuracy':{'operator':'>=','value':0.9}})
    result=model_evaluation(data)
    assert result['metrics']['accuracy']==0
    assert result['findings'] and result==model_evaluation(data)

def test_cross_version_predictions_rejected():
    with pytest.raises(ValueError,match='cross-version'):
        model_evaluation(package(prediction_records=[dict(sample_id='a',model_version='2',actual_label=1,predicted_label=1)]))

def test_zero_denominator_not_green():
    result=representativeness(package(dimensions=[dict(name='age',population_counts={},test_counts={})]))
    assert result['conclusion']=='INCONCLUSIVE'

def test_observed_review_conflict():
    result=independent_validation(package(validation_record={'model_version':'1','reviewer_ids':['dev']},developer_ids=['dev'],deployer_ids=[]))
    assert any('overlap' in x for x in result['findings'])

def test_missing_disposition_is_assurance_gap():
    result=residual_risk(package(risks=[{'risk_id':'r'}],validation_findings=[{'finding_id':'f','material':True}]))
    assert result['conclusion']=='INCONCLUSIVE' and not result['findings']

def test_remote_transfer_policy_enforced():
    with pytest.raises(ValueError): endpoint({'base_url':'https://example.com/v1'})
    assert endpoint({'base_url':'http://127.0.0.1:11434'})=='http://127.0.0.1:11434'

def test_mandatory_gate_and_bound_no_downgrade(monkeypatch):
    monkeypatch.delenv('WB_INVESTIGATION_REQUIRED',raising=False)
    assert required()
    monkeypatch.setenv('WB_INVESTIGATION_REQUIRED','0')
    assert required({'governance_context':{'investigation_id':'bound'}})

def test_collector_rejects_root_escape(tmp_path):
    root=tmp_path/'approved';root.mkdir()
    (tmp_path/'outside').write_text('data')
    with pytest.raises(ValueError,match='outside approved root'):
        collect({'collectors':[{'root':'approved','path':'../outside'}]},tmp_path,{})

def test_live_failure_receipt_never_becomes_success(tmp_path,monkeypatch):
    import governance.operations.live as live
    from tools.wb140_demo import fixture_environment
    _,signers=fixture_environment(tmp_path/'keys')
    def unavailable(*a,**k): raise OSError('endpoint unavailable')
    monkeypatch.setattr(live,'request_json',unavailable)
    client=LiveClient({'provider':'ollama','base_url':'http://127.0.0.1:11434','model':'test'},'examine',signers['assessor'],tmp_path/'receipts','i')
    with pytest.raises(OSError): client('{}')
    receipt=json.loads(next((tmp_path/'receipts').glob('*.json')).read_text())
    assert receipt['status']=='UNAVAILABLE' and receipt['response'] is None and receipt['signature']

def test_source_rejects_buried_maintenance_and_js_shell():
    from governance.operations.sources import validate_content
    with pytest.raises(ValueError,match='maintenance'):
        validate_content(('<html><style>'+('x'*200000)+'</style><body>Sorry, this service is currently unavailable.'+(' contact '*40)+'</body></html>').encode(),'text/html')
    with pytest.raises(ValueError,match='shell'):
        validate_content(b'<html><script>location.href="next";</script><title>Regulator</title></html>','text/html')

def test_missing_validation_kind_is_not_observed_failure():
    result=independent_validation(package(risk_tier='high',validation_record={'model_version':'1'}))
    assert result['assurance_gaps'] and not result['findings']

def test_unconfigured_judgment_has_no_score(tmp_path):
    from governance.operations.benchmark import evaluate
    result=evaluate({},tmp_path)
    assert result['status']=='NOT_EVALUATED' and result['cases_executed']==0
    assert 'accuracy_all_cases' not in result

def test_two_missing_labels_cannot_be_correct_prediction():
    with pytest.raises(ValueError,match='missing labels'):
        model_evaluation(package(prediction_records=[dict(sample_id='a',model_version='1',actual_label=None,predicted_label=None)]))
