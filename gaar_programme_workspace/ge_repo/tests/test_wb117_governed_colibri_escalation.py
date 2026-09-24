from __future__ import annotations

import json

from inference.policy import TaskSignals, build_plan, governed_colibri_decision


def _base(**kw):
    data = dict(role='assess', control_id='SAFR-2.1', control_complexity_score=1,
                control_complexity_reasons=('multiple_control_elements',))
    data.update(kw)
    return TaskSignals(**data)


def _enable(monkeypatch):
    monkeypatch.setenv('WB_COLIBRI_ENABLED', '1')
    monkeypatch.setenv('WB_COLIBRI_GOVERNED_ESCALATION', '1')
    monkeypatch.setenv('COLIBRI_MODEL', 'glm-5.2-colibri')
    monkeypatch.delenv('WB_PROVIDER_ASSESS', raising=False)
    monkeypatch.delenv('WB_DEFAULT_PROVIDER', raising=False)


def test_complex_control_alone_does_not_spend_deep_reasoning_budget(monkeypatch):
    _enable(monkeypatch)
    plan = build_plan(_base())
    assert plan.provider == 'ollama'
    assert plan.deep_reasoning is False
    assert plan.escalation_policy == 'governed-v1'
    assert plan.escalation_reasons == ()


def test_ambiguity_routes_to_colibri_with_reason(monkeypatch):
    _enable(monkeypatch)
    plan = build_plan(_base(ambiguity=0.7))
    assert plan.provider == 'colibri'
    assert plan.deep_reasoning is True
    assert 'ambiguity' in plan.escalation_reasons


def test_contradiction_materiality_and_strong_challenge_are_first_class(monkeypatch):
    _enable(monkeypatch)
    for field, reason in [
        ('evidence_contradiction', 'evidence_contradiction'),
        ('material_change', 'material_regulatory_change'),
        ('unresolved_strong_challenge', 'unresolved_strong_challenge'),
    ]:
        plan = build_plan(_base(**{field: True}))
        assert plan.provider == 'colibri'
        assert reason in plan.escalation_reasons


def test_regulatory_freshness_alone_does_not_equal_materiality(monkeypatch):
    _enable(monkeypatch)
    plan = build_plan(_base(regulatory_freshness=True))
    assert plan.provider == 'ollama'
    assert 'material_regulatory_change' not in plan.escalation_reasons


def test_high_risk_and_reviewer_disagreement_escalate(monkeypatch):
    _enable(monkeypatch)
    for sig, reason in [
        (_base(high_risk=True), 'high_risk_control'),
        (_base(reviewer_disagreement=True), 'reviewer_assessor_disagreement'),
    ]:
        plan = build_plan(sig)
        assert plan.provider == 'colibri'
        assert reason in plan.escalation_reasons


def test_critical_structural_control_can_escalate(monkeypatch):
    _enable(monkeypatch)
    plan = build_plan(TaskSignals(role='challenge', control_complexity_score=3,
                                  control_complexity_reasons=('many_control_elements','many_expected_artefacts')))
    assert plan.provider == 'colibri'
    assert 'critical_control_complexity' in plan.escalation_reasons


def test_prior_validation_failure_escalates(monkeypatch):
    _enable(monkeypatch)
    plan = build_plan(_base(prior_failures=1))
    assert plan.provider == 'colibri'
    assert 'prior_validation_failure' in plan.escalation_reasons


def test_colibri_disabled_blocks_governed_escalation(monkeypatch):
    monkeypatch.setenv('WB_COLIBRI_ENABLED', '0')
    monkeypatch.setenv('WB_COLIBRI_GOVERNED_ESCALATION', '1')
    plan = build_plan(_base(ambiguity=1.0, high_risk=True))
    assert plan.provider == 'ollama'
    decision = governed_colibri_decision(plan.tier, _base(ambiguity=1.0, high_risk=True))
    assert decision['enabled'] is False
    assert decision['escalate'] is False


def test_explicit_provider_override_remains_operator_controlled(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv('WB_PROVIDER_ASSESS', 'ollama')
    plan = build_plan(_base(high_risk=True))
    assert plan.provider == 'ollama'
    # The policy still records why deeper reasoning would otherwise be justified.
    assert 'high_risk_control' in plan.escalation_reasons


def test_telemetry_records_policy_and_budget(monkeypatch, tmp_path):
    _enable(monkeypatch)
    import inference.telemetry as tel
    path = tmp_path / 'tasks.jsonl'
    monkeypatch.setattr(tel, 'TASK_METRICS', path)
    plan = build_plan(_base(evidence_contradiction=True))
    rec = tel.record_task(task_id='T1', role='assess', control_id='SAFR-2.1', plan=plan,
                          calls=1, escalated=False, validation_failures=0, completed=True,
                          elapsed_ms=12)
    assert rec['provider'] == 'colibri'
    assert rec['deep_reasoning'] is True
    assert rec['escalation_policy'] == 'governed-v1'
    assert rec['escalation_reasons'] == ['evidence_contradiction']
    assert rec['generation_budget'] == plan.num_predict
    assert json.loads(path.read_text())['escalation_policy'] == 'governed-v1'
