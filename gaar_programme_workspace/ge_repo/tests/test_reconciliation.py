"""D8 reconciliation, tested on the real Phase 0 run B answer.

tests/fixtures/qwen25_7b_J3_examine.json is qwen2.5:7b's actual examine
response from the user's Mac, with the prompt and response hashes from its
signed receipt. It cited real evidence ids, passed the examine validator and
marked all four obligations SUPPORTED on evidence with planted violations.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "tests/fixtures/constructed_change_pack"
FIXTURE = json.loads((ROOT / "tests/fixtures/qwen25_7b_J3_examine.json").read_text())
IID = "CHG-TEST-001"

sys.path.insert(0, str(ROOT / "tools"))
from gaar_phase0 import RECONCILIATION_MAP, ELEMENTS  # noqa: E402


def _cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools/gaar_pilot.py"), *map(str, args)],
                          text=True, capture_output=True)


def _provision(tmp_path, mapping=None):
    keys = tmp_path / "keys"
    for name in ("owner", "reviewer"):
        assert _cli("keygen", "--out", keys / f"{name}.key").returncode == 0
    command = ["provision", "--output-config", tmp_path / "ws/operations.json", "--investigation-id", IID,
               "--confirm", IID, "--system-id", "CONSTRUCTED-payments-api", "--version", "4.x",
               "--period", "2026-09-15T00:00:00+08:00", "--framework", "INTERNAL", "--control", "CHANGE.MGMT",
               "--requirement-version", "constructed-cm-v1", "--policy", PACK / "change_policy.md",
               "--policy-version", "v1", "--evidence", f"CHANGES={PACK / 'changes.json'}",
               "--evidence", f"POPULATION={PACK / 'population.json'}",
               "--owner-key", keys / "owner.key", "--owner-name", "Test Owner",
               "--governance-key", keys / "owner.key", "--governance-name", "Test Owner",
               "--approver-key", keys / "reviewer.key", "--approver-name", "Test Reviewer", "--model", "qwen2.5:7b"]
    for element in ELEMENTS:
        command += ["--element", element]
    result = _cli(*command)
    assert result.returncode == 0, result.stderr
    path = tmp_path / "ws/operations.json"
    config = json.loads(path.read_text())
    config["reconciliation_map"] = {"CHANGE.MGMT": mapping or RECONCILIATION_MAP}
    path.write_text(json.dumps(config, indent=2))
    from governance.operations.runtime import load
    return load(path)


def _replay_run_b(tmp_path, monkeypatch, mapping=None, response=None):
    import governance.production.orchestrator as orch
    config, root = _provision(tmp_path, mapping)
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})

    def model(self, prompt):
        if self.stage == "examine":
            return response or FIXTURE["response"]
        raise ValueError("dependency has no traceable evidence/gap basis")   # how explain failed on the Mac
    monkeypatch.setattr(orch.LiveClient, "__call__", model)
    report = orch.run(config, root, IID)
    from governance.production.journal import Journal
    journal = Journal(orch.case_directory(config, root, IID) / "operations.sqlite", config["trusted_keys"])
    return config, root, report, journal


def test_fixture_is_the_signed_run_b_answer():
    assert hashlib.sha256(FIXTURE["response"].encode()).hexdigest() == FIXTURE["response_sha256"]
    findings = json.loads(FIXTURE["response"])["findings"]
    assert [f["status"] for f in findings] == ["SUPPORTED"] * 4
    assert all(f.get("evidence_refs") for f in findings)


def test_segregation_procedure_finds_only_the_planted_self_approval():
    from governance.production.procedures import change_segregation
    result = change_segregation(json.loads((PACK / "changes.json").read_text()))
    assert [(f["event_id"], f["code"]) for f in result["findings"]] == [("CHG-03", "SELF_APPROVAL")]


def test_run_b_false_assurance_is_reconciled_before_the_model_stalls(tmp_path, monkeypatch):
    config, root, report, journal = _replay_run_b(tmp_path, monkeypatch)
    assert report["checkpoint"] == "ACTION_REQUIRED"            # explain still fails, as it did live
    event = journal.latest("obligation_reconciliation")
    assert event, "reconciliation must run straight after examine"
    rec = event["payload"]
    governed = {o["element_id"]: o["governed_status"] for o in rec["obligations"]}
    assert governed == {"chg.1": "CONTRADICTED", "chg.2": "CONTRADICTED",
                        "chg.3": "NOT_EVIDENCED", "chg.4": "NOT_EVIDENCED"}
    assert all(o["assessor_status"] == "SUPPORTED" and o["false_assurance"] for o in rec["obligations"])
    assert rec["false_assurance_count"] == 4 and rec["unmapped_codes"] == []

    by_element = {}
    for issue in rec["issues"]:
        by_element.setdefault(issue["element_id"], []).append((issue["event_id"], issue["code"]))
    assert sorted(by_element["chg.1"]) == sorted([("CHG-05", "APPROVAL_AFTER_EXECUTION"), ("CHG-03", "SELF_APPROVAL"),
                                                  ("CHG-07", "NO_MATCHING_APPROVED_TICKET"),
                                                  ("CHG-16", "APPROVAL_NOT_ESTABLISHED")])
    assert {c for _, c in by_element["chg.2"]} == {"IMPLEMENTATION_CONTENT_MISMATCH", "OUTSIDE_APPROVED_WINDOW",
                                                   "CREDENTIAL_NOT_APPROVED_FOR_CHANGE", "DEVIATES_FROM_APPROVED_SCOPE",
                                                   "PRIVILEGE_NOT_ESTABLISHED"}
    assert sorted(by_element["chg.3"]) == [("CHG-09", "FREEZE_WITHOUT_PRIOR_EXCEPTION"), ("CHG-11", "RECOVERY_NOT_ESTABLISHED")]
    assert by_element["chg.4"] == [("CHG-15", "COLLECTION_POPULATION_DISAGREEMENT")]
    assert len(rec["issues"]) == 13

    actions = [e for e in journal.read() if e["kind"] == "remediation_opened"
               and e["payload"].get("source") == "DETERMINISTIC_RECONCILIATION"]
    assert len(actions) == 13 and all(a["payload"]["delivery"] == "LOCAL_ONLY" for a in actions)


def test_reconciliation_is_bound_to_the_signed_examine_and_runs_once(tmp_path, monkeypatch):
    import governance.production.orchestrator as orch
    from governance.investigation import InvestigationEngine, InvestigationStore
    config, root, report, journal = _replay_run_b(tmp_path, monkeypatch)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    rows, values = engine.snapshot(IID)
    examine_row = next(r for r in rows if r["stage"] == "examine")
    first = journal.latest("obligation_reconciliation")
    assert first["payload"]["examine_record_hash"] == examine_row["record_hash"]
    assert [f.status for f in values["examine"].findings] == ["SUPPORTED"] * 4   # signed stage untouched
    orch.run(config, root, IID)                                                  # resume
    events = [e for e in journal.read() if e["kind"] == "obligation_reconciliation"]
    assert len(events) == 1 and events[0]["event_hash"] == first["event_hash"]


def test_deterministic_silence_never_changes_a_status_and_unmapped_findings_are_reported(tmp_path, monkeypatch):
    answer = json.loads(FIXTURE["response"])
    answer["findings"][3]["status"] = "NOT_EVIDENCED"          # chg.4
    mapping = {**RECONCILIATION_MAP, "chg.4": ["IMPLEMENTER_NOT_APPROVED"]}  # real code, never fires here
    config, root, report, journal = _replay_run_b(tmp_path, monkeypatch, mapping, json.dumps(answer))
    rec = journal.latest("obligation_reconciliation")["payload"]
    chg4 = next(o for o in rec["obligations"] if o["element_id"] == "chg.4")
    assert chg4["governed_status"] == "NOT_EVIDENCED" and chg4["basis"] == "ASSESSOR_UNCHALLENGED"
    assert chg4["false_assurance"] is False
    assert rec["unmapped_codes"] == ["COLLECTION_POPULATION_DISAGREEMENT"]   # visible, not silently dropped


def test_gate_blocks_a_pass_that_reconciliation_contradicts(tmp_path, monkeypatch):
    from governance.production.reconciliation import gate_blockers
    config, root, report, journal = _replay_run_b(tmp_path, monkeypatch)

    class Conclude:
        verdict = "PASS"
    class Understand:
        control_id = "CHANGE.MGMT"
    values = {"examine": object(), "understand": Understand(), "conclude": Conclude()}
    blockers = gate_blockers(config, values, journal)
    assert sorted(blockers) == ["pass_conflicts_with_reconciliation:" + e for e in ("chg.1", "chg.2", "chg.3", "chg.4")]
    unconfigured = {**config, "reconciliation_map": {}}
    assert gate_blockers(unconfigured, values, journal) == []


def test_reviewer_sees_the_reconciliation_even_though_the_run_stalled(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    config, root, report, journal = _replay_run_b(tmp_path, monkeypatch)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(root / "operations.json"))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    assert not app.exception
    assert any("marked 4 obligations SUPPORTED" in e.value for e in app.error)
    table = next(df.value for df in app.dataframe if "Recorded status" in df.value.columns)
    assert list(table["Recorded status"]) == ["CONTRADICTED", "CONTRADICTED", "NOT_EVIDENCED", "NOT_EVIDENCED"]
    assert set(table["Assessor said"]) == {"SUPPORTED"}


def test_mapping_with_invented_codes_is_rejected():
    from governance.production.reconciliation import validate_map
    with pytest.raises(ValueError, match="CHG_AUTH_001"):
        validate_map({"chg.1": ["CHG_AUTH_001", "APPROVAL_AFTER_EXECUTION"]})
    validate_map(RECONCILIATION_MAP)


def test_every_stage_prompt_lists_the_valid_references_and_leaks_no_answers(tmp_path, monkeypatch):
    """D11/D12: each prompt names exactly the ids its validator accepts."""
    import governance.production.orchestrator as orch
    import gaar_fake_models as fake
    from governance.production.reconciliation import KNOWN_CODES
    from governance.production.dependencies import investigate
    fake.PERSONA = "good"
    config, root = _provision(tmp_path)
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    prompts = {}

    def model(self, prompt):
        prompts[self.stage] = json.loads(prompt)
        return json.dumps(fake.answer(prompt))
    monkeypatch.setattr(orch.LiveClient, "__call__", model)
    assert orch.run(config, root, IID)["checkpoint"] == "EVALUATION_COMPLETE"

    for stage, prompt in prompts.items():
        assert list(prompt)[:2] == ["task", "rules"], stage
        text = " ".join(prompt["rules"])
        assert not [c for c in KNOWN_CODES if c in text], f"{stage} rules leak a finding code"
        assert "SUPPORTED" not in text or stage == "examine", f"{stage} rules name a status"

    explain = " ".join(prompts["explain"]["rules"])
    assert "only these ids: CHANGES, POPULATION, gap:chg.3." in explain and "NOT valid basis_refs" in explain

    plan = " ".join(prompts["plan"]["rules"])
    assert "change_population reads the population export: POPULATION" in plan
    assert "change_authorization:2, change_population:1" in plan and "hypothesis_id must be one of: H1" in plan

    dependency = " ".join(prompts["dependency_review"]["rules"])
    edges = [e["edge_id"] for e in investigate("INTERNAL", "CHANGE.MGMT")["edges"]]
    assert "one treatment for each edge_id: " + ", ".join(edges) in dependency
    assert "executed tests: T1, T2" in dependency

    challenge = " ".join(prompts["challenge"]["rules"])
    assert "must include every one of: CHANGES, POPULATION, H1, T1, T2" in challenge
