"""Deterministic-first completion: a failed model stage no longer strands the run."""
import json
from pathlib import Path

import pytest

from tests.test_reconciliation import FIXTURE, IID, ROOT, _provision


def _run(tmp_path, monkeypatch, examine_answer=None, enabled=True, mapping=None):
    import governance.production.orchestrator as orch
    config, root = _provision(tmp_path, mapping)
    config["deterministic_completion"] = enabled
    (root / "operations.json").write_text(json.dumps(config, indent=2))
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    calls = []

    def model(self, prompt):
        calls.append(self.stage)
        if self.stage == "examine":
            return examine_answer or FIXTURE["response"]
        raise ValueError("dependency has no traceable evidence/gap basis")
    monkeypatch.setattr(orch.LiveClient, "__call__", model)
    report = orch.run(config, root, IID)
    from governance.production.journal import Journal
    from governance.investigation import InvestigationEngine, InvestigationStore
    journal = Journal(orch.case_directory(config, root, IID) / "operations.sqlite", config["trusted_keys"])
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    return config, root, report, journal, engine, calls, orch


def test_run_b_completes_on_tests_and_d8_without_fabricating_model_stages(tmp_path, monkeypatch):
    config, root, report, journal, engine, calls, orch = _run(tmp_path, monkeypatch)
    assert report["checkpoint"] == "DETERMINISTIC_COMPLETE" and report["deterministic_verdict"] == "ADVERSE"
    assert report["model_stage_unavailable"]["stage"] == "explain"
    assert "traceable evidence/gap basis" in report["model_stage_unavailable"]["error"]
    assert [r["stage"] for r in engine.snapshot(IID)[0]] == ["understand", "expectations", "examine"]
    assert {o["element_id"]: o["governed_status"] for o in report["obligations"]} == {
        "chg.1": "CONTRADICTED", "chg.2": "CONTRADICTED", "chg.3": "NOT_EVIDENCED", "chg.4": "NOT_EVIDENCED"}
    assert report["deployment_authorized"] is False and report["gate"]["assessment_finalizable"] is False

    before = list(calls)
    again = orch.run(config, root, IID)
    assert calls == before, "a completed deterministic record must not re-ask the model"
    assert again["reconciliation_event_hash"] == report["reconciliation_event_hash"]


def test_examine_rejected_still_yields_a_deterministic_record(tmp_path, monkeypatch):
    j2 = json.dumps({"findings": [{"element_id": f"chg.{i}", "status": "SUPPORTED",
                                   "rationale": "All changes comply."} for i in range(1, 5)]})  # J2: no refs
    config, root, report, journal, engine, calls, orch = _run(tmp_path, monkeypatch, examine_answer=j2)
    assert report["checkpoint"] == "DETERMINISTIC_COMPLETE"
    assert report["model_stage_unavailable"]["stage"] == "examine"
    assert [r["stage"] for r in engine.snapshot(IID)[0]] == ["understand", "expectations"]
    rec = journal.latest("obligation_reconciliation")["payload"]
    assert rec["examine_record_hash"] is None and rec["evidence_manifest_event_hash"]
    assert {o["assessor_status"] for o in rec["obligations"]} == {"MODEL_UNAVAILABLE"}
    assert rec["false_assurance_count"] == 0
    assert [o["governed_status"] for o in rec["obligations"]] == ["CONTRADICTED", "CONTRADICTED",
                                                                  "NOT_EVIDENCED", "NOT_EVIDENCED"]
    assert len(rec["issues"]) == 13


def test_switched_off_keeps_the_old_behaviour(tmp_path, monkeypatch):
    config, root, report, journal, engine, calls, orch = _run(tmp_path, monkeypatch, enabled=False)
    assert report["checkpoint"] == "ACTION_REQUIRED"
    assert journal.latest("model_stage_unavailable") is None


def test_deterministic_record_never_yields_pass():
    from governance.production.completion import deterministic_verdict
    assert deterministic_verdict([{"governed_status": "SUPPORTED"}] * 4) == "INCONCLUSIVE"
    assert deterministic_verdict([{"governed_status": "NOT_EVIDENCED"}, {"governed_status": "SUPPORTED"}]) == "INCONCLUSIVE"
    assert deterministic_verdict([{"governed_status": "CONTRADICTED"}]) == "ADVERSE"


def test_human_attests_the_deterministic_record_and_it_cannot_be_sealed(tmp_path, monkeypatch):
    from governance import decisions
    import governance.production.qualification as qual
    import governance.production.lifecycle as life
    config, root, report, journal, engine, calls, orch = _run(tmp_path, monkeypatch)
    pre = decisions.deterministic_preflight(config, root, IID, engine, journal)
    assert pre["ready"], pre["problems"]
    assert [(c["decision"], c["assurance_only_fail"]) for c in pre["choices"]] == [("FAIL", False)]

    with pytest.raises(ValueError, match="cannot carry decision PASS"):
        decisions.attest_deterministic(config, root, IID, decisions.build_payload(
            IID, pre["investigation_head"], "PASS", "Trying to pass a deterministic adverse record."), engine, journal)
    payload = decisions.build_payload(IID, pre["investigation_head"], "FAIL",
        "Deterministic tests contradict chg.1 and chg.2; the assessor's SUPPORTED claims are false assurance.")
    outcome = decisions.attest_deterministic(config, root, IID, payload, engine, journal)
    signed = outcome["attestation"]
    assert signed["record_basis"] == "DETERMINISTIC_RECORD" and signed["model_stage_unavailable"] == "explain"
    assert signed["reliance"] == "PILOT_DECISION_SUPPORT" and signed["governance_result"] is False
    assert signed["reconciliation_event_hash"] == report["reconciliation_event_hash"]
    assert not decisions.deterministic_preflight(config, root, IID, engine, journal)["ready"]

    config["operation_mode"] = "production"
    qualified = {"status": "QUALIFIED", "fingerprint": qual.fingerprint(config)}
    monkeypatch.setattr(qual, "check", lambda *a: qualified)
    monkeypatch.setattr(life, "check_qualification", lambda *a: qualified)
    config["result_decisions"] = {IID: str(Path(outcome["decision_document"]).relative_to(root))}
    with pytest.raises(ValueError):
        life.seal(config, root, IID, engine, journal)
    assert journal.latest("result_sealed") is None


def test_reviewer_sees_the_deterministic_record_and_attests_it(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    config, root, report, journal, engine, calls, orch = _run(tmp_path, monkeypatch)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(root / "operations.json"))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    assert not app.exception
    assert any("deterministic record only" in w.value for w in app.warning)
    assert any("Reconciled against the deterministic tests" in s.value for s in app.subheader)
    assert not any("Press Run to start it" in c.value for c in app.caption)
    app.text_area(key="deterministic-rationale").input(
        "Tests contradict chg.1 and chg.2; model stages unavailable; remediate before reliance.").run()
    _confirm(app).check().run()
    next(b for b in app.button if b.label == "Sign attestation").click().run()
    assert not app.exception
    assert journal.latest("pilot_attestation")["payload"]["attestation"]["record_basis"] == "DETERMINISTIC_RECORD"


MISTRAL = json.loads((ROOT / "tests/fixtures/mistral_nemo_12b_J8_examine.json").read_text())
EXPECTED = {"chg.1": "CONTRADICTED", "chg.2": "CONTRADICTED", "chg.3": "NOT_EVIDENCED", "chg.4": "NOT_EVIDENCED"}


def _governed(obligations):
    return [{"element_id": k, "governed_status": v} for k, v in EXPECTED.items()]


def test_d13_attempted_false_assurance_is_measured_from_the_receipt():
    from governance.production.reconciliation import attempted_false_assurance
    qwen = attempted_false_assurance(FIXTURE["response"], _governed(None))
    mistral = attempted_false_assurance(MISTRAL["response"], _governed(None))
    assert (qwen["attempted"], qwen["obligations"]) == (4, 4)
    assert (mistral["attempted"], mistral["obligations"]) == (4, 4)          # rejected, yet it tried 4 of 4
    assert mistral["false_claims"] == ["chg.1", "chg.2", "chg.3", "chg.4"]
    assert attempted_false_assurance("not json", _governed(None))["parsed"] is False


def test_mistral_j8_answer_is_rejected_and_the_record_completes_from_evidence(tmp_path, monkeypatch):
    config, root, report, journal, engine, calls, orch = _run(tmp_path, monkeypatch, examine_answer=MISTRAL["response"])
    assert report["model_stage_unavailable"]["stage"] == "examine"
    assert "admitted evidence omitted" in report["model_stage_unavailable"]["error"]
    rec = journal.latest("obligation_reconciliation")["payload"]
    assert {o["element_id"]: o["governed_status"] for o in rec["obligations"]} == EXPECTED
    assert rec["false_assurance_count"] == 0                                   # recorded: nothing got through


def test_models_disabled_calls_no_model_and_builds_the_record_from_tests(tmp_path, monkeypatch):
    import governance.production.orchestrator as orch
    config, root = _provision(tmp_path)
    config["model_stages"] = "disabled"
    (root / "operations.json").write_text(json.dumps(config, indent=2))
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    def forbidden(self, prompt):
        raise AssertionError("no model may be called when model stages are disabled")
    monkeypatch.setattr(orch.LiveClient, "__call__", forbidden)
    report = orch.run(config, root, IID)
    assert report["checkpoint"] == "DETERMINISTIC_COMPLETE" and report["deterministic_verdict"] == "ADVERSE"
    assert report["model_stage_unavailable"]["disabled_by_configuration"] is True
    assert {o["element_id"]: o["governed_status"] for o in report["obligations"]} == EXPECTED
    assert not list((orch.case_directory(config, root, IID) / "inference_receipts").glob("*.json"))
    from governance import decisions
    from governance.production.journal import Journal
    from governance.investigation import InvestigationEngine, InvestigationStore
    journal = Journal(orch.case_directory(config, root, IID) / "operations.sqlite", config["trusted_keys"])
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    pre = decisions.deterministic_preflight(config, root, IID, engine, journal)
    assert pre["ready"], pre["problems"]


def test_models_disabled_does_not_block_readiness_on_absent_model_servers(tmp_path):
    from governance.operations.runtime import doctor
    config, root = _provision(tmp_path)
    for stage in config["models"].values():
        stage.update(provider="ollama", base_url="http://127.0.0.1:9", model="nothing-here")
    assert any(b.startswith("model:") for b in doctor(config, root)["blockers"])
    config["model_stages"] = "disabled"
    report = doctor(config, root)
    assert not any(b.startswith("model:") for b in report["blockers"])
    assert report["checks"]["model:examine"]["status"] == "DISABLED"


def test_models_disabled_without_a_mapping_is_refused(tmp_path, monkeypatch):
    import governance.production.orchestrator as orch
    config, root = _provision(tmp_path)
    config["model_stages"] = "disabled"
    config["reconciliation_map"] = {}
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    report = orch.run(config, root, IID)
    assert report["checkpoint"] == "ACTION_REQUIRED" and "no reconciliation mapping" in json.dumps(report)


def test_reviewer_sees_a_no_model_record_labelled_as_such(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import governance.production.orchestrator as orch
    config, root = _provision(tmp_path)
    config["model_stages"] = "disabled"
    (root / "operations.json").write_text(json.dumps(config, indent=2))
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    report = orch.run(config, root, IID)
    assert report["gate"]["blockers"][0] == "model_stages_disabled"
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(root / "operations.json"))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    assert not app.exception
    assert any("Model stages are disabled for this pilot" in i.value for i in app.info)
    assert not app.error                                  # no false-assurance banner: no model claimed anything
    assert any("Attest the deterministic record" in m.value for m in app.markdown)


def test_the_signed_sentence_describes_a_deterministic_record_truthfully(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from governance.decisions import CONFIRM_DETERMINISTIC_COVERAGE as CONFIRM
    import governance.production.orchestrator as orch
    config, root = _provision(tmp_path)
    config["model_stages"] = "disabled"
    (root / "operations.json").write_text(json.dumps(config, indent=2))
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    orch.run(config, root, IID)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(root / "operations.json"))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    box = _confirm(app)
    assert box.label == CONFIRM and "challenge" not in box.label
    table = next(df.value for df in app.dataframe if "Recorded status" in df.value.columns)
    assert set(table["Assessor said"]) == {"not asked (models off)"}
    assert any("switched off for this pilot" in c.value for c in app.caption)
    assert not any("A model stage was unavailable" in c.value for c in app.caption)
    app.text_area(key="deterministic-rationale").input("Tests contradict chg.1 and chg.2; remediate before reliance.").run()
    box.check().run()
    next(b for b in app.button if b.label == "Sign attestation").click().run()
    from governance.production.journal import Journal
    signed = Journal(orch.case_directory(config, root, IID) / "operations.sqlite",
                     config["trusted_keys"]).latest("pilot_attestation")["payload"]["attestation"]
    assert signed["reviewer_confirmed"] == CONFIRM
    assert signed["models_disabled_by_configuration"] is True


def test_rationale_warnings_flag_contradiction_not_legitimate_risk_acceptance():
    from governance.decisions import rationale_warnings, local_time
    assert rationale_warnings("FAIL", "i think is ok to proceed")                        # unqualified approval
    assert rationale_warnings("FAIL", "The control was effective this period.")          # claims a pass
    assert not rationale_warnings("FAIL", "Accepted for continued operation pending remediation of CHG-23 by 30 Sep.")
    assert not rationale_warnings("FAIL", "The control is not effective: chg.2 contradicted by CHG-23 and CHG-25.")
    assert not rationale_warnings("FAIL", "Ineffective control; approvals were missing for CHG-24.")
    assert not rationale_warnings("PASS", "ok to proceed")                              # only FAIL is checked
    shown = local_time("2026-09-23T11:16:17+00:00")
    assert "UTC" in shown and "(UTC" in shown


def _confirm(app):
    """The confirmation is keyed to the record on screen (kit v20), so it is found by its prefix."""
    return next(c for c in app.checkbox if (c.key or "").startswith("deterministic-confirm-"))
