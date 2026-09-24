"""Human decision contract (seal) and the pilot path built around it.

`test_sign_and_seal` is the supplied contract, unchanged in substance. The
remaining tests cover the pilot on-ramp and attestation integrated around it.
Scripted model responses are protocol fixtures, not judgment evidence."""
import json,sys
from pathlib import Path
import pytest
from tests.test_wb143_149_programme import environment
from governance.production.orchestrator import run, case_directory
from governance.production.journal import Journal
from governance.production.qualification import fingerprint
from governance import decisions

def test_sign_and_seal(tmp_path, monkeypatch):
    import governance.production.orchestrator as orch
    import governance.production.lifecycle as life
    config,engine,signers,iid,calls=environment(tmp_path,monkeypatch,seal_fixture=True)
    config['operation_mode']='production'
    qualified={'status':'QUALIFIED','fingerprint':fingerprint(config)}
    monkeypatch.setattr(orch,'qualification_check',lambda *a:qualified)
    monkeypatch.setattr(life,'check_qualification',lambda *a:qualified)
    import governance.production.qualification as qual
    monkeypatch.setattr(qual,'check',lambda *a:qualified)
    monkeypatch.setattr(life,'actor_signer',lambda c,r,role:signers[role])
    monkeypatch.setattr(decisions,'approver_signer',
        lambda c,r:(signers['owner'],c['trusted_keys'][signers['owner'].key_id]))
    monkeypatch.setattr(decisions,'_executor',lambda c,r:signers['executor'])
    report=run(config,tmp_path,iid)
    assert report['checkpoint']=='COMPLETE',report
    journal=Journal(case_directory(config,tmp_path,iid)/'operations.sqlite',config['trusted_keys'])

    pre=decisions.preflight(config,tmp_path,iid,engine,journal)
    print('PREFLIGHT ready:',pre['ready'],'verdict:',pre['verdict'])
    print('  problems:',pre['problems'])
    print('  choices:',[(c['decision'],c['assurance_only_fail']) for c in pre['choices']])
    assert pre['ready'], pre['problems']

    # Wrong decision for the verdict must be refused before anything is written.
    bad=decisions.build_payload(iid,pre['investigation_head'],'PASS',
        'Attempting to pass an adverse investigation to prove it is refused.')
    cfg_path=tmp_path/'ops.json'; cfg_path.write_text(json.dumps(config,indent=2))
    with pytest.raises(ValueError,match='cannot carry decision'):
        decisions.sign_and_register(cfg_path,config,tmp_path,iid,bad,engine,journal)
    print('REFUSED wrong decision for verdict: ok')

    # Stale head must be refused.
    stale=decisions.build_payload(iid,'0'*64,'FAIL','Stale head attempt to prove binding is enforced.')
    with pytest.raises(ValueError,match='moved while you were deciding'):
        decisions.sign_and_register(cfg_path,config,tmp_path,iid,stale,engine,journal)
    print('REFUSED stale head: ok')

    # Thin rationale must be refused.
    with pytest.raises(ValueError,match='rationale'):
        decisions.build_payload(iid,pre['investigation_head'],'FAIL','ok')
    print('REFUSED thin rationale: ok')

    good=decisions.build_payload(iid,pre['investigation_head'],'FAIL',
        'Observed change executed outside approved authorisation; hold pending remediation.')
    out=decisions.sign_and_register(cfg_path,config,tmp_path,iid,good,engine,journal)
    print('SEALED:',out['result'])
    assert out['result']['state']=='CURRENT'
    assert out['result']['decision']=='FAIL'
    assert out['result']['deployment_authorized'] is False

    # The written document must verify through the production contract.
    from governance.production.qualification import signed_document
    payload,policy,doc=signed_document(Path(out['decision_document']),config['trusted_keys'],'result_approver',True)
    assert payload==good and policy['actor_type']=='human'
    print('DOCUMENT verifies via signed_document as result_approver/human: ok')

    # Second attempt is blocked by preflight, not by a crash inside seal.
    post=decisions.preflight(config,tmp_path,iid,engine,journal)
    assert not post['ready']
    print('SECOND ATTEMPT blocked:',post['problems'])


# --------------------------------------------------------------------------
# pilot on-ramp and attestation
# --------------------------------------------------------------------------

import os, subprocess, hashlib
from governance.investigation.store import canonical
from governance.investigation.contracts import (ExplanationSet, RetrievalLane, Dependency, Explanation,
    TestPlan as PlanContract, TestProposal as ProposalContract, ChallengeRecord, ChallengeFinding)
from governance.production.dependencies import Review, Treatment

PILOT = Path(__file__).resolve().parents[1] / 'tools' / 'gaar_pilot.py'
IID = 'CHG-PILOT-001'
SCOPE = {'system': 'credit-platform', 'period': '2026-09-20T00:00:00Z'}


def _cli(*args):
    return subprocess.run([sys.executable, str(PILOT), *map(str, args)], text=True, capture_output=True)


def _inputs(tmp_path):
    from tools.wb140_change_fixture import package
    base = tmp_path / 'inputs'; base.mkdir()
    changes = package(); changes.pop('synthetic', None)
    changes.update(scope=SCOPE['system'], as_of=SCOPE['period'])
    (base / 'changes.json').write_text(canonical(changes))
    population = {'scope': SCOPE['system'], 'as_of': SCOPE['period'],
                  'primary': {'scope': SCOPE['system'], 'as_of': SCOPE['period'], 'complete': True,
                              'source_id': 'ticketing', 'event_ids': ['CHG-OBS-1']},
                  'independent': {'scope': SCOPE['system'], 'as_of': SCOPE['period'], 'complete': True,
                                  'source_id': 'host-audit', 'event_ids': ['CHG-OBS-1', 'CHG-OBS-2']}}
    (base / 'population.json').write_text(canonical(population))
    (base / 'policy.md').write_text('# Change policy v4\nEvery production change is authorised before execution.\n')
    return base


def _provision(tmp_path, owner_key, approver_key, *, extra=()):
    base = _inputs(tmp_path)
    return _cli('provision', '--output-config', tmp_path / 'pilot_cfg' / 'operations.json',
                '--investigation-id', IID, '--confirm', IID, '--system-id', SCOPE['system'], '--version', '2.3',
                '--period', SCOPE['period'], '--framework', 'INTERNAL', '--control', 'CHANGE.MGMT',
                '--requirement-version', 'change-policy-v4', '--policy', base / 'policy.md', '--policy-version', 'v4',
                '--element', 'chg.1=Every production change is authorised before execution',
                '--element', 'chg.2=The change population reconciles to an independent source',
                '--evidence', f'CHANGES={base / "changes.json"}', '--evidence', f'POPULATION={base / "population.json"}',
                '--owner-key', owner_key, '--owner-name', 'Pilot Owner',
                '--governance-key', owner_key, '--governance-name', 'Pilot Owner',
                '--approver-key', approver_key, '--approver-name', 'Independent Reviewer',
                '--examine-model', 'examiner-model', '--explain-model', 'examiner-model',
                '--plan-model', 'examiner-model', '--challenge-model', 'challenger-model', *extra)


def _keys(tmp_path):
    keys = tmp_path / 'personal_keys'
    for name in ('owner', 'reviewer'):
        assert _cli('keygen', '--out', keys / f'{name}.key').returncode == 0
    return keys / 'owner.key', keys / 'reviewer.key'


def _scripted(self, prompt):
    p = json.loads(prompt)
    if self.stage == 'examine':
        return canonical({'evidence': p['admitted_evidence'], 'findings': [
            {'element_id': 'chg.1', 'status': 'CONTRADICTED', 'evidence_refs': ['CHANGES'],
             'rationale': 'Observed change used actions and a credential outside its approval'},
            {'element_id': 'chg.2', 'status': 'NOT_EVIDENCED', 'evidence_refs': ['POPULATION'],
             'rationale': 'Independent source reports an event the primary source does not'}]})
    if self.stage == 'explain':
        return ExplanationSet(status='COMPLETED',
            retrieval=tuple(RetrievalLane(name=n, status='COMPLETED') for n in
                            ('expectations', 'facts', 'dependencies', 'counterevidence', 'procedures', 'precedents')),
            dependencies=(Dependency(dependency_id='D1', upstream='CHANGE.MGMT', downstream='SECURITY.LOGGING',
                relation='A change that disables audit logging weakens detection', basis_refs=('CHANGES',),
                status='hypothesis'),),
            hypotheses=(Explanation(hypothesis_id='H1', claim='A change executed outside its approved authorisation',
                basis_refs=('CHANGES',), alternatives=('Unexported emergency approval', 'Clock skew'),
                compensating_controls_review='Check recorded exceptions and audit events', dependencies=('D1',),
                material=True),),
            limitations=('Supplied exports only',)).model_dump_json()
    if self.stage == 'plan':
        return PlanContract(policy_id='change-policy-v4', tests=(
            ProposalContract(test_id='T1', hypothesis_id='H1', tool='change_authorization', version='2',
                input_ref='CHANGES', decision_impact='Separates discrepancy from a missing record', priority=1),
            ProposalContract(test_id='T2', hypothesis_id='H1', tool='change_population', version='1',
                input_ref='POPULATION', decision_impact='Tests population completeness', priority=2))).model_dump_json()
    if self.stage == 'dependency_review':
        return Review(knowledge_sha256=p['knowledge']['knowledge_sha256'], treatments=[
            Treatment(edge_id=e['edge_id'], status='INVESTIGATED', material=True,
                      rationale='Bound to the supplied exports and executed comparisons',
                      evidence_refs=['CHANGES', 'POPULATION'], test_refs=['T1', 'T2'], risk_refs=['H1'])
            for e in p['knowledge']['edges']]).model_dump_json()
    if self.stage == 'challenge':
        return ChallengeRecord(status='COMPLETED', input_head=p['investigation']['input_head'],
            reviewed_refs=('CHANGES', 'POPULATION', 'H1', 'T1', 'T2'),
            disproof_attempts=('Tested the unexported emergency-approval alternative',),
            findings=(ChallengeFinding(finding_id='C1', material=True,
                claim='The freeze-window exception path was not examined', basis_refs=('CHANGES', 'H1')),)).model_dump_json()
    raise AssertionError(self.stage)


def _pilot_run(tmp_path, monkeypatch):
    from governance.operations.runtime import load
    import governance.production.orchestrator as orch
    owner_key, approver_key = _keys(tmp_path)
    result = _provision(tmp_path, owner_key, approver_key)
    assert result.returncode == 0, result.stderr
    config, root = load(tmp_path / 'pilot_cfg' / 'operations.json')
    monkeypatch.setattr(orch, 'doctor', lambda c, r: {'blockers': [], 'checks': {}})
    monkeypatch.setattr(orch.LiveClient, '__call__', _scripted)
    report = run(config, root, IID)
    assert report['checkpoint'] == 'EVALUATION_COMPLETE', report
    from governance.investigation import InvestigationEngine, InvestigationStore
    engine = InvestigationEngine(InvestigationStore(root / config['store'], config['trusted_keys']), config['sources'])
    journal = Journal(case_directory(config, root, IID) / 'operations.sqlite', config['trusted_keys'])
    return config, root, engine, journal, (owner_key, approver_key)


def test_pilot_provisioning_uses_supplied_human_keys_and_never_creates_one(tmp_path):
    owner_key, approver_key = _keys(tmp_path)
    before = {p: p.read_bytes() for p in (owner_key, approver_key)}
    result = _provision(tmp_path, owner_key, approver_key)
    assert result.returncode == 0, result.stderr
    config = json.loads((tmp_path / 'pilot_cfg' / 'operations.json').read_text())
    assert config['deployment_profile'] == 'pilot' and config['operation_mode'] == 'evaluation'
    assert config['separation_of_duties'] == 'APPROVER_SEPARATED'
    humans = [k for k, v in config['trusted_keys'].items() if v['actor_type'] == 'human']
    assert len(humans) == 2
    for role in ('owner', 'governance', 'result_approver'):
        assert Path(config['signers'][role]['private_key_file']).parent == owner_key.parent
    minted = sorted((tmp_path / 'pilot_cfg').rglob('*.key'))
    assert len(minted) == 6 and all(p.parent.name == 'service_keys' for p in minted)
    assert {p: p.read_bytes() for p in before} == before
    from governance.investigation import InvestigationEngine, InvestigationStore
    root = tmp_path / 'pilot_cfg'
    rows, values = InvestigationEngine(InvestigationStore(root / config['store'], config['trusted_keys']),
                                       config['sources']).snapshot(IID)
    assert len(rows) == 2 and values['understand'].synthetic is False
    assert config['expected_heads'][IID] == rows[-1]['record_hash']
    from governance.operations.sources import validate_source
    assert validate_source(next(iter(config['sources'].values())), root, config['trusted_keys'])
    assert config['models']['examine']['model'] != config['models']['challenge']['model']


def test_pilot_refuses_unconfirmed_scope_workspace_keys_and_group_readable_keys(tmp_path):
    owner_key, approver_key = _keys(tmp_path)
    wrong = _cli('provision', '--output-config', tmp_path / 'x' / 'o.json', '--investigation-id', 'A',
                 '--confirm', 'B', '--system-id', 's', '--version', 'v', '--period', SCOPE['period'],
                 '--framework', 'INTERNAL', '--control', 'CHANGE.MGMT', '--requirement-version', 'r',
                 '--policy', owner_key, '--policy-version', 'v', '--owner-key', owner_key, '--owner-name', 'a',
                 '--governance-key', owner_key, '--governance-name', 'a', '--approver-key', approver_key,
                 '--approver-name', 'b')
    assert wrong.returncode == 2 and 'confirm' in wrong.stderr
    inside = tmp_path / 'pilot_cfg' / 'mine.key'
    assert _cli('keygen', '--out', inside).returncode == 0
    refused = _provision(tmp_path, inside, approver_key)
    assert refused.returncode == 2 and 'inside the pilot configuration directory' in refused.stderr
    assert not (tmp_path / 'pilot_cfg' / 'operations.json').exists()
    loose = tmp_path / 'loose.key'; loose.write_text(owner_key.read_text()); os.chmod(loose, 0o644)
    shutil_dir = tmp_path / 'second'; shutil_dir.mkdir()
    readable = _cli('provision', '--output-config', shutil_dir / 'o.json', '--investigation-id', IID, '--confirm', IID,
                    '--system-id', 's', '--version', 'v', '--period', SCOPE['period'], '--framework', 'INTERNAL',
                    '--control', 'CHANGE.MGMT', '--requirement-version', 'r', '--policy', approver_key,
                    '--policy-version', 'v', '--element', 'e=x', '--evidence', f'E={approver_key}',
                    '--owner-key', loose, '--owner-name', 'a', '--governance-key', loose, '--governance-name', 'a',
                    '--approver-key', approver_key, '--approver-name', 'b')
    assert readable.returncode == 2 and 'chmod 600' in readable.stderr
    in_package = _cli('keygen', '--out', PILOT.parent / 'never.key')
    assert in_package.returncode == 2 and not (PILOT.parent / 'never.key').exists()


def test_pilot_run_attests_once_and_the_attestation_cannot_be_sealed(tmp_path, monkeypatch):
    import governance.production.qualification as qual
    import governance.production.orchestrator as orch
    import governance.production.lifecycle as life
    from governance.trace import verify_operations
    config, root, engine, journal, _ = _pilot_run(tmp_path, monkeypatch)

    assert not decisions.preflight(config, root, IID, engine, journal)['ready']
    pre = decisions.pilot_preflight(config, root, IID, engine, journal)
    assert pre['ready'], pre['problems']
    assert pre['verdict'] == 'ADVERSE' and [(c['decision'], c['assurance_only_fail']) for c in pre['choices']] == [('FAIL', False)]
    assert pre['approver']['actor'] == 'Independent Reviewer'

    with pytest.raises(ValueError, match='cannot carry decision'):
        decisions.attest(config, root, IID, decisions.build_payload(
            IID, pre['investigation_head'], 'PASS', 'Trying to pass an adverse pilot run to prove refusal.'),
            engine, journal)
    with pytest.raises(ValueError, match='moved while you were deciding'):
        decisions.attest(config, root, IID, decisions.build_payload(
            IID, '0' * 64, 'FAIL', 'Stale head attempt to prove binding is enforced.'), engine, journal)

    payload = decisions.build_payload(IID, pre['investigation_head'], 'FAIL',
        'Change executed outside approval and the population does not reconcile; remediate before reliance.')
    outcome = decisions.attest(config, root, IID, payload, engine, journal)
    assert outcome['attestation']['reliance'] == 'PILOT_DECISION_SUPPORT'
    assert outcome['attestation']['governance_result'] is False
    assert config.get('result_decisions') == {}

    from governance.production.qualification import signed_document
    signed, policy, _ = signed_document(Path(outcome['decision_document']), config['trusted_keys'], 'result_approver', True)
    assert signed == outcome['attestation'] and policy['actor'] == 'Independent Reviewer'
    ops = verify_operations(case_directory(config, root, IID), config['trusted_keys'])
    assert ops['status'] == 'VALID', ops['problems']
    assert sum(e['kind'] == 'pilot_attestation' for e in ops['records']) == 1
    assert decisions.existing_attestation(journal)['decision'] == 'FAIL'

    again = decisions.pilot_preflight(config, root, IID, engine, journal)
    assert not again['ready'] and any('already carries' in p for p in again['problems'])

    # Promotion attempt: register the pilot document as a result decision under a
    # forged-qualified production configuration. seal must refuse it.
    config['operation_mode'] = 'production'
    qualified = {'status': 'QUALIFIED', 'fingerprint': qual.fingerprint(config)}
    monkeypatch.setattr(qual, 'check', lambda *a: qualified)
    monkeypatch.setattr(life, 'check_qualification', lambda *a: qualified)
    monkeypatch.setattr(orch, 'qualification_check', lambda *a: qualified)
    config['result_decisions'] = {IID: str(Path(outcome['decision_document']).relative_to(root))}
    with pytest.raises(ValueError, match='cannot be promoted'):
        life.seal(config, root, IID, engine, journal)
    assert journal.latest('result_sealed') is None


def test_demonstration_configuration_cannot_attest(tmp_path, monkeypatch):
    config, engine, signers, iid, calls = environment(tmp_path, monkeypatch)
    assert run(config, tmp_path, iid)['checkpoint'] == 'EVALUATION_COMPLETE'
    journal = Journal(case_directory(config, tmp_path, iid) / 'operations.sqlite', config['trusted_keys'])
    monkeypatch.setattr(decisions, '_executor', lambda c, r: signers['executor'])
    report = decisions.pilot_preflight(config, tmp_path, iid, engine, journal)
    assert not report['ready']
    assert any('not provisioned as a pilot' in p for p in report['problems'])
    assert any('synthetic' in p for p in report['problems'])


def test_production_qualification_rejects_same_weights_at_another_endpoint(tmp_path):
    from governance.production.qualification import check
    same = {'provider': 'ollama', 'model': 'm', 'model_sha256': 'a' * 64}
    config = {'qualification_report': 'q.json', 'trusted_keys': {}, 'signers': {},
              'models': {'examine': {**same, 'base_url': 'http://127.0.0.1:11434'},
                         'challenge': {**same, 'base_url': 'http://127.0.0.1:11435'}}}
    report = check(config, tmp_path)
    assert report['status'] == 'NOT_QUALIFIED' and 'different model revision' in report['reason']


def test_reviewer_app_reveals_on_request_logs_it_and_attests(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    config, root, engine, journal, _ = _pilot_run(tmp_path, monkeypatch)
    monkeypatch.setenv('WB_INVESTIGATION_CONFIG', str(root / 'operations.json'))
    monkeypatch.setenv('GAAR_REVIEWER_TOKEN', 'pilot-token')
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app_gaar.py'), default_timeout=60).run()
    assert not app.exception
    assert any('reviewer token' in w.value for w in app.warning)       # locked until authenticated
    app.text_input[0].input('pilot-token').run()
    assert not app.exception
    assert not app.code                                                  # evidence hidden by default
    assert any('Attest this pilot result' in m.value for m in app.markdown)
    assert any('Source approval' in df.value.columns and set(df.value['Source approval']) == {'governance approved'}
               for df in app.dataframe)

    next(b for b in app.button if b.label == 'Open evidence and reasoning').click().run()
    assert app.code                                                      # admitted bytes now readable
    log = (case_directory(config, root, IID) / 'reviewer_access.jsonl').read_text().splitlines()
    assert len(log) == 1 and json.loads(log[0])['session'] == 'token-authenticated'

    app.text_area(key='attest-rationale').input(
        'Change executed outside approval; population does not reconcile. Remediate before reliance.').run()
    app.checkbox(key='attest-confirm').check().run()
    next(b for b in app.button if b.label == 'Sign attestation').click().run()
    assert not app.exception
    assert any('Attested' in s.value for s in app.success)
    assert decisions.existing_attestation(journal)['approver'] == 'Independent Reviewer'


def test_examine_attaches_admitted_evidence_and_still_rejects_altered_echo(tmp_path, monkeypatch):
    from governance.investigation import agents
    config, engine, signers, iid, calls = environment(tmp_path, monkeypatch)
    from governance.production.collectors import collect_all
    from governance.production.journal import Journal
    evidence = collect_all(config, tmp_path, engine.snapshot(iid)[1]['understand'].scope,
                           Journal(tmp_path / 'collect.sqlite', config['trusted_keys']), signers['executor'])
    element = engine.snapshot(iid)[1]['expectations'].elements[0].element_id
    findings = [{'element_id': element, 'status': 'NOT_EVIDENCED', 'evidence_refs': [e.evidence_id for e in evidence],
                 'rationale': 'findings-only answer'}]
    altered = [e.model_dump(mode='json') for e in evidence]; altered[0]['text'] = altered[0]['text'] + ' '
    with pytest.raises(ValueError, match='alter admitted evidence'):
        agents.examine(engine, iid, evidence, signers['assessor'],
                       invoke=lambda prompt: json.dumps({'evidence': altered, 'findings': findings}))
    row = agents.examine(engine, iid, evidence, signers['assessor'],
                         invoke=lambda prompt: json.dumps({'findings': findings}))
    stored = engine.snapshot(iid)[1]['examine']
    assert stored.evidence == tuple(evidence) and len(stored.findings) == 1


def test_run_error_stays_visible_after_the_page_refreshes(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import governance.production.orchestrator as orch
    config, root, engine, journal, _ = _pilot_run(tmp_path, monkeypatch)
    def boom(*a, **k):
        raise RuntimeError('model endpoint refused the run')
    monkeypatch.setattr(orch, 'run', boom)
    monkeypatch.setenv('WB_INVESTIGATION_CONFIG', str(root / 'operations.json'))
    monkeypatch.setenv('GAAR_REVIEWER_TOKEN', 'pilot-token')
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app_gaar.py'), default_timeout=60).run()
    app.text_input[0].input('pilot-token').run()
    next(b for b in app.button if 'Run' in b.label).click().run()
    assert any('model endpoint refused the run' in e.value for e in app.error)


def test_ollama_health_accepts_implicit_latest_tag(monkeypatch):
    import governance.operations.live as live
    monkeypatch.setattr(live, 'request_json', lambda url, cfg, body=None: {'models': [{'name': 'llama3.2:latest'}]})
    base = {'provider': 'ollama', 'base_url': 'http://127.0.0.1:11434'}
    assert live.health({**base, 'model': 'llama3.2'})['status'] == 'AVAILABLE'
    assert live.health({**base, 'model': 'llama3.2:latest'})['status'] == 'AVAILABLE'
    assert live.health({**base, 'model': 'llama3.2:1b'})['status'] == 'MODEL_NOT_LOADED'


def test_prompt_puts_task_rules_and_answer_format_first():
    from governance.investigation.prompting import render
    text = render({'admitted_evidence': [{'x': 1}], 'context': {}, 'schema': {}, 'task': 'T',
                   'rules': ['r'], 'answer_format': {}})
    keys = list(json.loads(text))
    assert keys[:4] == ['task', 'rules', 'answer_format', 'schema'] and keys[4] == 'admitted_evidence'


def test_examine_prompt_names_the_citable_evidence_and_the_citation_rules(tmp_path, monkeypatch):
    from governance.investigation import agents
    config, engine, signers, iid, calls = environment(tmp_path, monkeypatch)
    from governance.production.collectors import collect_all
    evidence = collect_all(config, tmp_path, engine.snapshot(iid)[1]['understand'].scope,
                           Journal(tmp_path / 'collect.sqlite', config['trusted_keys']), signers['executor'])
    seen = {}
    def capture(prompt):
        seen['prompt'] = json.loads(prompt)
        raise RuntimeError('stop after capturing the prompt')
    with pytest.raises(RuntimeError):
        agents.examine(engine, iid, evidence, signers['assessor'], invoke=capture)
    prompt = seen['prompt']
    assert list(prompt)[:3] == ['task', 'rules', 'answer_format']
    rules = ' '.join(prompt['rules'])
    assert all(e.evidence_id in rules for e in evidence)
    assert 'Absence of a record is not a contradiction' in rules


def test_live_client_refuses_a_prompt_larger_than_the_model_context(tmp_path):
    from governance.operations.live import LiveClient
    from governance.result_contract import CanonicalSigner
    import base64
    signer = CanonicalSigner.from_base64('k', base64.b64encode(b'\x01' * 32).decode())
    client = LiveClient({'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:9/v1', 'model': 'm',
                         'max_tokens': 1024, 'context_tokens': 4096}, 'examine', signer, tmp_path / 'r', 'I')
    with pytest.raises(ValueError, match='Refused rather than letting the server cut the prompt'):
        client('x' * 30000)
    receipt = json.loads(next((tmp_path / 'r').glob('*.json')).read_text())
    assert 'model context is 4096' in receipt['error']
