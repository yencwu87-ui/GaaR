"""Recurring results: standing authorisation, per-period evidence, scheduler, deltas."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/gaar_recurring.py"
WEEK1 = ROOT / "tests/fixtures/constructed_change_pack"
WEEK2 = ROOT / "tests/fixtures/constructed_change_pack_week2"
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
AFTER_WEEK3 = _dt(2026, 10, 1, 9, 0, tzinfo=_tz(_td(hours=8)))   # simulated clock: constructed demo series only


def _cli(home, *args):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True, env=env)


@pytest.fixture
def series(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo")
    assert result.returncode == 0, result.stderr
    config_path = home / "demo/operations.json"
    return home, config_path


def _load(config_path):
    from governance.operations.runtime import load
    return load(config_path)


def test_standing_authorisation_signs_every_period_opening_with_human_keys(series):
    from governance.production import recurring
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    payload = recurring.verify(config, root)
    assert len(payload["periods"]) == 4 and payload["model_stages"] == "disabled"
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    for period in payload["periods"]:
        rows, values = engine.snapshot(period["investigation_id"])
        assert [r["stage"] for r in rows] == ["understand", "expectations"]
        assert values["understand"].scope.period == period["as_of"]
        assert all(config["trusted_keys"][r["key_id"]]["actor_type"] == "human" for r in rows)
        assert payload["authorisation_id"] in values["understand"].boundary


def test_results_arrive_as_evidence_arrives_with_a_recorded_delta(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    from datetime import datetime, timezone, timedelta
    before_series = datetime(2026, 9, 10, tzinfo=timezone(timedelta(hours=8)))
    assert {s["state"] for s in recurring.tick(config, root, now=before_series)} == {"NOT_YET_DUE"}

    assert _cli(home, "demo-inbox", "--config", config_path, "--week", 1).returncode == 0
    first = recurring.tick(config, root)
    assert (first[0]["state"], first[0]["verdict"], first[0]["issues"]) == ("AWAITING_ATTESTATION", "ADVERSE", 13)

    assert _cli(home, "demo-inbox", "--config", config_path, "--week", 2).returncode == 0
    second = recurring.tick(config, root)
    week2 = second[1]
    assert (week2["state"], week2["verdict"], week2["issues"]) == ("AWAITING_ATTESTATION", "ADVERSE", 3)
    delta = week2["delta"]
    assert delta["previous_label"] == "2026-09-15" and delta["verdict_changed"] is False
    assert (delta["issues_before"], delta["issues_after"]) == (13, 3)
    assert delta["codes_new"] == ["IMPLEMENTER_NOT_APPROVED"]
    assert delta["codes_persisting"] == ["NO_MATCHING_APPROVED_TICKET", "OUTSIDE_APPROVED_WINDOW"]
    assert "SELF_APPROVAL" in delta["codes_resolved"]
    assert {c["element_id"]: (c["before"], c["after"]) for c in delta["obligation_changes"]} == {
        "chg.1": ("CONTRADICTED", "NOT_EVIDENCED"),
        "chg.3": ("NOT_EVIDENCED", "NO_EXCEPTIONS_FOR_PERIOD"),     # coverage: nothing to breach this period
        "chg.4": ("NOT_EVIDENCED", "NO_EXCEPTIONS_FOR_PERIOD")}     # coverage: both records list the same 6

    third = recurring.tick(config, root)
    assert not any(s.get("ran") for s in third), "completed periods must not run again"
    status = json.loads((root / "pilot/schedule_status.json").read_text())
    assert [p["state"] for p in status["periods"]][:2] == ["AWAITING_ATTESTATION"] * 2


def test_an_export_placed_in_the_wrong_week_is_refused(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    folder = root / config["periodic_evidence"]["inbox"] / "2026-09-15"
    folder.mkdir(parents=True)
    for name in ("changes.json", "population.json"):
        shutil.copyfile(WEEK2 / name, folder / name)                 # week-2 files in week 1's folder
    summary = recurring.tick(config, root)
    assert summary[0]["state"] == "EVIDENCE_READY" and summary[0]["checkpoint"] == "ACTION_REQUIRED"
    latest = json.loads((recurring._case(config, root, "CHG-WEEKLY-2026-09-15") / "latest_status.json").read_text())
    assert "not this period" in json.dumps(latest)


def test_changing_a_past_period_export_is_caught_before_attestation(series):
    from governance import decisions
    from governance.production import recurring
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 1)
    recurring.tick(config, root)
    changes = root / config["periodic_evidence"]["inbox"] / "2026-09-15/changes.json"
    changes.write_text(changes.read_text().replace('"alice.tan"', '"dave.lim"', 1))   # quiet edit after the run
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    journal = recurring._journal(config, root, "CHG-WEEKLY-2026-09-15")
    pre = decisions.deterministic_preflight(config, root, "CHG-WEEKLY-2026-09-15", engine, journal)
    assert not pre["ready"]
    assert any("evidence export CHANGES was changed after this run" in p and "integrity event" in p
               for p in pre["problems"])


def test_altering_what_was_signed_stops_the_scheduler(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    config["reconciliation_map"]["CHANGE.MGMT"]["chg.1"] = ["APPROVAL_AFTER_EXECUTION"]   # narrower than signed
    with pytest.raises(ValueError, match="differs from the signed standing authorisation"):
        recurring.tick(config, root)
    config, root = _load(config_path)
    document = json.loads((root / config["standing_authorisation"]).read_text())
    document["payload"]["periods"][0]["as_of"] = "2026-09-14T00:00:00+08:00"
    (root / config["standing_authorisation"]).write_text(json.dumps(document))
    with pytest.raises(ValueError, match="signature is invalid"):
        recurring.verify(config, root)


def test_schedule_file_runs_tick_on_an_interval(series, tmp_path):
    home, config_path = series
    result = _cli(home, "install-schedule", "--config", config_path, "--every-minutes", 15, "--plist-dir", tmp_path / "agents")
    assert result.returncode == 0, result.stderr
    plist = (tmp_path / "agents/com.gaar.recurring.plist").read_text()
    assert "<string>tick</string>" in plist and "<integer>900</integer>" in plist and str(config_path) in plist


def test_reviewer_sees_the_new_period_and_what_changed(series, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    for week in (1, 2):
        _cli(home, "demo-inbox", "--config", config_path, "--week", week)
    recurring.tick(config, root)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    app.sidebar.radio[0].set_value("CHG-WEEKLY-2026-09-22").run()
    assert not app.exception
    assert any("awaiting your attestation" in s.value for s in app.success)
    assert any("Since the previous period (2026-09-15)" in m.value for m in app.markdown)
    assert any("13 → 3" in m.value for m in app.markdown)


def test_only_one_check_runs_at_a_time(series):
    import fcntl
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    with open(root / "pilot/tick.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(recurring.SchedulerBusy):
            recurring.tick(config, root)


def test_scheduled_check_skips_while_watch_owns_the_workspace(series):
    import fcntl
    home, config_path = series
    config, root = _load(config_path)
    with open(root / "pilot/watch.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _cli(home, "tick", "--config", config_path)
        assert result.returncode == 0 and "watch is running on this workspace" in result.stdout
        second = _cli(home, "watch", "--config", config_path, "--every", 1)
        assert second.returncode == 2 and "another watch is already running" in second.stderr


def test_watch_stops_plainly_when_the_signed_series_changes(series):
    import time as _time
    home, config_path = series
    config, root = _load(config_path)
    env = {**os.environ, "HOME": str(home)}
    proc = subprocess.Popen([sys.executable, str(TOOL), "watch", "--config", str(config_path), "--every", "1"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    _time.sleep(3)
    document = json.loads((root / config["standing_authorisation"]).read_text())
    document["payload"]["cadence_days"] = 14
    (root / config["standing_authorisation"]).write_text(json.dumps(document))
    out, err = proc.communicate(timeout=20)
    assert proc.returncode == 0 and "Stopped: this workspace's standing authorisation changed" in out


def _signed_mapping_with_demo_keys(home, tmp_path):
    """Sign a mapping with the same governance key the constructed demo uses."""
    from tools.gaar_phase0 import ELEMENTS, RECONCILIATION_MAP
    pilot = ROOT / "tools/gaar_pilot.py"
    env = {**os.environ, "HOME": str(home)}
    keys = home / ".gaar-test-keys"
    for name in ("owner", "reviewer"):
        if not (keys / f"{name}.key").exists():
            subprocess.run([sys.executable, str(pilot), "keygen", "--out", str(keys / f"{name}.key")], check=True, env=env)
    command = [sys.executable, str(pilot), "provision", "--output-config", str(tmp_path / "trial/operations.json"),
               "--investigation-id", "CHG-MAP-001", "--confirm", "CHG-MAP-001", "--system-id", "CONSTRUCTED-payments-api",
               "--version", "4.x", "--period", "2026-09-15T00:00:00+08:00", "--framework", "INTERNAL",
               "--control", "CHANGE.MGMT", "--requirement-version", "constructed-cm-v1",
               "--policy", str(WEEK1 / "change_policy.md"), "--policy-version", "v1",
               "--evidence", f"CHANGES={WEEK1 / 'changes.json'}", "--evidence", f"POPULATION={WEEK1 / 'population.json'}",
               "--owner-key", str(keys / "owner.key"), "--owner-name", "Test Owner",
               "--governance-key", str(keys / "owner.key"), "--governance-name", "Test Owner",
               "--approver-key", str(keys / "reviewer.key"), "--approver-name", "Test Reviewer", "--model", "none"]
    for element in ELEMENTS:
        command += ["--element", element]
    subprocess.run(command, check=True, env=env, capture_output=True)
    mapping_tool = ROOT / "tools/gaar_mapping.py"
    worksheet = tmp_path / "mapping/worksheet.json"
    subprocess.run([sys.executable, str(mapping_tool), "draft", "--config", str(tmp_path / "trial/operations.json"),
                    "--out", str(worksheet)], check=True, env=env, capture_output=True)
    sheet = json.loads(worksheet.read_text())
    for ob in sheet["obligations"]:
        for code in ob["codes"]:
            code["include"] = code["code"] in RECONCILIATION_MAP.get(ob["element_id"], [])
    worksheet.write_text(json.dumps(sheet))
    signed = subprocess.run([sys.executable, str(mapping_tool), "sign", "--config", str(tmp_path / "trial/operations.json"),
                             "--worksheet", str(worksheet), "--confirm", "CHANGE.MGMT"],
                            check=True, env=env, capture_output=True, text=True)
    return Path(json.loads(signed.stdout)["document"])


def test_a_series_can_be_pinned_to_a_governance_signed_mapping(tmp_path):
    from governance.production import recurring
    from governance.production.journal import Journal
    home = tmp_path / "home"
    home.mkdir()
    document = _signed_mapping_with_demo_keys(home, tmp_path)
    result = _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo", "--mapping", document)
    assert result.returncode == 0, result.stderr
    config_path = home / "demo/operations.json"
    config, root = _load(config_path)
    payload = recurring.verify(config, root)
    assert payload["mapping_document_sha256"]
    assert config["reconciliation_mapping_document"]["signed_by"] == "Test Owner"

    _cli(home, "demo-inbox", "--config", config_path, "--week", 1)
    recurring.tick(config, root)
    rec = recurring._journal(config, root, "CHG-WEEKLY-2026-09-15").latest("obligation_reconciliation")["payload"]
    assert rec["mapping_signed_by"] == "Test Owner"

    other = json.loads(document.read_text())
    other["payload"]["signed_at"] = "2026-01-01T00:00:00+0800"       # any change: different document
    document.write_text(json.dumps(other))
    with pytest.raises(ValueError, match="differs from the one the standing authorisation pins"):
        recurring.verify(config, root)


def test_authorisation_ids_are_unique_per_signing_and_cannot_be_edited(tmp_path):
    from governance.production import recurring
    ids = []
    for n in (1, 2):
        home = tmp_path / f"home{n}"
        home.mkdir()
        result = _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo")
        assert result.returncode == 0, result.stderr
        config, root = _load(home / "demo/operations.json")
        payload = recurring.verify(config, root)
        assert payload["authorisation_id"].startswith("SA2-")
        ids.append(payload["authorisation_id"])
    assert ids[0] != ids[1], "identical inputs, separate signings: two distinct authorisations"
    # A legitimate key-holder re-signs, so the signature is valid and only the id check can catch it.
    # (This test used to accept any ValueError; the signature check caught the edit first, so the id
    # check itself was never exercised — a vacuous pass, found by tracing unreached refusal lines.)
    from tests.test_guards_exercised import resign
    resign(tmp_path / "home2", root, config, lambda payload: payload.update(authorisation_id=ids[0]))
    with pytest.raises(ValueError, match="does not match the inputs it was derived from"):
        recurring.verify(config, root)


def test_a_quiet_period_is_labelled_as_not_positively_shown(series, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    for week in (1, 2):
        _cli(home, "demo-inbox", "--config", config_path, "--week", week)
    changes, population = _week3(clean=True)
    population["independent"]["event_ids"].append("CHG-99")        # independent record disagrees
    _drop(config, root, "2026-09-29", changes, population)
    recurring.tick(config, root, now=AFTER_WEEK3)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    app.sidebar.radio[0].set_value(next(i for i in config["expected_heads"] if i.endswith("2026-09-29"))).run()
    assert not app.exception
    changes_table = next(df.value for df in app.dataframe if "This period" in df.value.columns)
    assert "no finding this period (not positively shown)" in set(changes_table["This period"])
    assert any("A quiet period is not a clean one" in c.value for c in app.caption)


def test_not_yet_due_awaiting_and_overdue_are_distinct(series):
    from datetime import datetime, timezone, timedelta
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    sgt = timezone(timedelta(hours=8))
    week1 = recurring.verify(config, root)["periods"][0]
    state = lambda when: recurring.period_state(config, root, week1, when)
    assert state(datetime(2026, 9, 14, tzinfo=sgt))["state"] == "NOT_YET_DUE"
    assert state(datetime(2026, 9, 16, tzinfo=sgt))["state"] == "AWAITING_EVIDENCE"      # inside the 2-day grace
    late = state(datetime(2026, 9, 21, tzinfo=sgt))
    assert (late["state"], late["overdue_days"]) == ("OVERDUE", 4)
    assert late["missing_files"] == ["changes.json", "population.json"]
    notices = []
    for _ in range(3):                                      # notify once, not on every check
        recurring.tick(config, root, notify=notices.append, now=datetime(2026, 9, 21, tzinfo=sgt))
    assert notices == ["2026-09-15: evidence OVERDUE by 4 day(s)"]


def test_a_software_upgrade_is_named_as_such_not_as_tampering(series, monkeypatch):
    from governance import decisions
    from governance.production import recurring, qualification
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 1)
    recurring.tick(config, root)
    real = qualification.fingerprint
    monkeypatch.setattr(qualification, "fingerprint", lambda c: {**real(c), "code_sha256": "0" * 64})
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    journal = recurring._journal(config, root, "CHG-WEEKLY-2026-09-15")
    problems = decisions.deterministic_preflight(config, root, "CHG-WEEKLY-2026-09-15", engine, journal)["problems"]
    assert any("the GaaR software was updated after this run" in p for p in problems)
    assert not any("integrity event" in p for p in problems)



def _shift(value, days):
    from datetime import datetime, timedelta
    if isinstance(value, dict):
        return {k: _shift(v, days) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift(v, days) for v in value]
    if isinstance(value, str) and len(value) == 25 and value[10] == "T":
        try:
            return (datetime.fromisoformat(value) + timedelta(days=days)).isoformat()
        except ValueError:
            return value
    return value


def _week3(clean=True):
    """Week 2's clean changes moved one week later: CHG-21, CHG-22 and CHG-26 only."""
    changes = _shift(json.loads((WEEK2 / "changes.json").read_text()), 7)
    keep = {"CHG-21", "CHG-22", "CHG-26"} if clean else {c["event_id"] for c in changes["changes"]}
    changes["changes"] = [c for c in changes["changes"] if c["event_id"] in keep]
    population = _shift(json.loads((WEEK2 / "population.json").read_text()), 7)
    for side in ("primary", "independent"):
        population[side]["event_ids"] = sorted(keep)
    return changes, population


def _drop(config, root, label, changes, population):
    folder = root / config["periodic_evidence"]["inbox"] / label
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "changes.json").write_text(json.dumps(changes))
    (folder / "population.json").write_text(json.dumps(population))


def _reconciled(config, root, label):
    from governance.production import recurring
    journal = recurring._journal(config, root, f"CHG-WEEKLY-{label}")
    rec = journal.latest("obligation_reconciliation")["payload"]
    return rec, {o["element_id"]: (o["governed_status"], o["basis"]) for o in rec["obligations"]}, journal


def test_week2_coverage_is_corroborated_and_week1_is_not(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    for week in (1, 2):
        _cli(home, "demo-inbox", "--config", config_path, "--week", week)
    recurring.tick(config, root)
    rec1, _, _ = _reconciled(config, root, "2026-09-15")
    assert rec1["coverage"]["corroborated"] is False and "differ" in rec1["coverage"]["reason"]
    rec2, status2, _ = _reconciled(config, root, "2026-09-22")
    assert rec2["coverage"]["corroborated"] is True
    assert status2 == {"chg.1": ("NOT_EVIDENCED", "DETERMINISTIC_ASSURANCE_GAP"),
                       "chg.2": ("CONTRADICTED", "DETERMINISTIC_DISCREPANCY"),
                       "chg.3": ("NO_EXCEPTIONS_FOR_PERIOD", "NO_APPLICABLE_EVENTS"),
                       "chg.4": ("NO_EXCEPTIONS_FOR_PERIOD", "COVERAGE_CORROBORATED")}
    chg4 = next(o for o in rec2["obligations"] if o["element_id"] == "chg.4")
    assert chg4["coverage"]["COLLECTION_POPULATION_DISAGREEMENT"] == {"applied_to": 6, "violations": 0}


def test_a_clean_period_reads_no_exceptions_and_still_never_pass(series):
    from governance import decisions
    from governance.production import recurring
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    _drop(config, root, "2026-09-29", *_week3(clean=True))
    summary = recurring.tick(config, root, now=AFTER_WEEK3)
    week3 = next(s for s in summary if s["label"] == "2026-09-29")
    assert week3["verdict"] == "NO_EXCEPTIONS_FOUND"
    _, status, journal = _reconciled(config, root, "2026-09-29")
    assert {v[0] for v in status.values()} == {"NO_EXCEPTIONS_FOR_PERIOD"}
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    pre = decisions.deterministic_preflight(config, root, "CHG-WEEKLY-2026-09-29", engine, journal)
    assert [(c["decision"], c["assurance_only_fail"]) for c in pre["choices"]] == [("NO_EXCEPTIONS_NOTED", True)]
    assert decisions.deterministic_confirm_text(journal) == decisions.CONFIRM_NO_EXCEPTIONS


def test_checked_zero_of_zero_is_never_clean(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    changes, population = _week3(clean=True)
    changes["changes"], changes["tickets"] = [], []
    for side in ("primary", "independent"):
        population[side]["event_ids"] = []
    _drop(config, root, "2026-09-29", changes, population)
    recurring.tick(config, root, now=AFTER_WEEK3)
    rec, status, _ = _reconciled(config, root, "2026-09-29")
    assert set(status.values()) == {("NOT_EVIDENCED", "EMPTY_POPULATION")}


def test_a_mapped_check_that_cannot_run_is_never_silence(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    changes, population = _week3(clean=True)
    changes["collection"]["complete"] = False               # the change checks cannot draw a conclusion
    _drop(config, root, "2026-09-29", changes, population)
    recurring.tick(config, root, now=AFTER_WEEK3)
    rec, status, _ = _reconciled(config, root, "2026-09-29")
    for element in ("chg.1", "chg.2", "chg.3"):
        assert status[element] == ("NOT_EVIDENCED", "PROCEDURE_DID_NOT_RUN")
    assert rec["coverage"]["status"] == "NOT_COMPARABLE"


def test_uncorroborated_coverage_is_shown_as_a_claim(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    changes, population = _week3(clean=True)
    population["independent"]["event_ids"].append("CHG-99")
    _drop(config, root, "2026-09-29", changes, population)
    recurring.tick(config, root, now=AFTER_WEEK3)
    rec, status, _ = _reconciled(config, root, "2026-09-29")
    assert status["chg.4"][0] == "NOT_EVIDENCED"                                  # the disagreement itself
    for element in ("chg.1", "chg.2", "chg.3"):
        assert status[element] == ("NOT_EVALUATED", "COVERAGE_UNCORROBORATED")


def test_status_as_of_previews_overdue_without_recording_anything(series):
    home, config_path = series
    config, root = _load(config_path)
    before = sorted(p.name for p in (root / "pilot").iterdir())
    result = _cli(home, "status", "--config", config_path, "--as-of", "2026-10-02T09:00:00+08:00")
    assert result.returncode == 0, result.stderr
    assert "PREVIEW as of 2026-10-02T09:00:00+08:00" in result.stdout
    assert "OVERDUE" in result.stdout and "overdue after 2 day(s) grace" in result.stdout
    assert sorted(p.name for p in (root / "pilot").iterdir()) == before


def test_the_grace_period_is_part_of_what_was_signed(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    assert recurring.verify(config, root)["grace_days"] == 2
    config["periodic_evidence"]["grace_days"] = 30
    with pytest.raises(ValueError, match="grace period differs"):
        recurring.verify(config, root)



def _attest(config, root, iid, decision, assurance_only, rationale):
    from governance import decisions
    from governance.investigation import InvestigationEngine, InvestigationStore
    from governance.production import recurring
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    journal = recurring._journal(config, root, iid)
    pre = decisions.deterministic_preflight(config, root, iid, engine, journal)
    payload = decisions.build_payload(iid, pre["investigation_head"], decision, rationale,
                                      assurance_only_fail=assurance_only)
    return decisions.attest_deterministic(config, root, iid, payload, engine, journal), engine, journal


def test_the_clean_week3_story_ends_with_no_exceptions_noted(series):
    from governance import decisions
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    for week in (1, 2, 3):
        assert _cli(home, "demo-inbox", "--config", config_path, "--week", week).returncode == 0
    summary = {s["label"]: s for s in recurring.tick(config, root, now=AFTER_WEEK3)}
    assert [summary[l]["verdict"] for l in ("2026-09-15", "2026-09-22", "2026-09-29")] == \
           ["ADVERSE", "ADVERSE", "NO_EXCEPTIONS_FOUND"]
    rec, status, journal = _reconciled(config, root, "2026-09-29")
    assert set(status.values()) == {("NO_EXCEPTIONS_FOR_PERIOD", "COVERAGE_CORROBORATED")}
    chg3 = next(o for o in rec["obligations"] if o["element_id"] == "chg.3")
    assert chg3["coverage"]["FREEZE_WITHOUT_PRIOR_EXCEPTION"] == {"applied_to": 1, "violations": 0}
    assert chg3["coverage"]["RECOVERY_NOT_ESTABLISHED"] == {"applied_to": 1, "violations": 0}
    delta = journal.latest("period_delta")["payload"]
    assert {"element_id": "chg.3", "status": "NO_EXCEPTIONS_FOR_PERIOD", "before": "NO_APPLICABLE_EVENTS",
            "after": "COVERAGE_CORROBORATED"} in delta["basis_changes"]
    outcome, _, _ = _attest(config, root, "CHG-WEEKLY-2026-09-29", "NO_EXCEPTIONS_NOTED", True,
                            "Week 3: all four obligations checked with corroborated coverage; nothing raised.")
    signed = outcome["attestation"]
    assert signed["decision"] == "NO_EXCEPTIONS_NOTED" and signed["verdict"] == "NO_EXCEPTIONS_FOUND"
    assert signed["reviewer_confirmed"] == decisions.CONFIRM_NO_EXCEPTIONS
    assert "no findings were raised this period" in signed["reviewer_confirmed"]


def test_no_exceptions_noted_is_never_offered_on_an_adverse_or_inconclusive_record(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    for week in (1, 2):
        _cli(home, "demo-inbox", "--config", config_path, "--week", week)
    recurring.tick(config, root)
    with pytest.raises(ValueError, match="cannot carry decision NO_EXCEPTIONS_NOTED"):
        _attest(config, root, "CHG-WEEKLY-2026-09-22", "NO_EXCEPTIONS_NOTED", True,
                "Trying to note no exceptions on a record with a contradicted obligation.")


def test_no_exceptions_noted_can_never_be_sealed_as_a_governance_result(series, monkeypatch):
    """Standing rule: every new decision-vocabulary item ships with its non-promotion test."""
    import governance.production.qualification as qual
    import governance.production.lifecycle as life
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    recurring.tick(config, root, now=AFTER_WEEK3)
    outcome, engine, journal = _attest(config, root, "CHG-WEEKLY-2026-09-29", "NO_EXCEPTIONS_NOTED", True,
                                       "Week 3 clean with corroborated coverage; noting no exceptions.")
    config["operation_mode"] = "production"
    qualified = {"status": "QUALIFIED", "fingerprint": qual.fingerprint(config)}
    monkeypatch.setattr(qual, "check", lambda *a: qualified)
    monkeypatch.setattr(life, "check_qualification", lambda *a: qualified)
    config["result_decisions"] = {"CHG-WEEKLY-2026-09-29": str(Path(outcome["decision_document"]).relative_to(root))}
    with pytest.raises(ValueError):
        life.seal(config, root, "CHG-WEEKLY-2026-09-29", engine, journal)
    assert journal.latest("result_sealed") is None


def test_losing_corroboration_is_shown_as_a_regression(series, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 2)
    changes, population = _week3(clean=True)
    population["independent"]["event_ids"].append("CHG-99")
    _drop(config, root, "2026-09-29", changes, population)
    recurring.tick(config, root, now=AFTER_WEEK3)
    _, _, journal = _reconciled(config, root, "2026-09-29")
    delta = journal.latest("period_delta")["payload"]
    assert delta["coverage_before"]["corroborated"] is True and delta["coverage_after"]["corroborated"] is False
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    app.sidebar.radio[0].set_value(next(i for i in config["expected_heads"] if i.endswith("2026-09-29"))).run()
    assert any("corroborated → not corroborated" in w.value for w in app.warning)


def test_runner_names_missing_requirements(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner", ROOT / "tools/run_all_tests.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    (tmp_path / "requirements.txt").write_text("pytest>=1\nnot-a-real-package==1.0\n-r extra.txt\n")
    (tmp_path / "extra.txt").write_text("pytest<2\n")
    missing, mismatched = runner.requirement_problems(tmp_path / "requirements.txt")
    assert missing == ["not-a-real-package==1.0"]
    assert len(mismatched) == 1 and mismatched[0].startswith("pytest<2")


def test_a_simulated_clock_is_carried_into_the_signature_and_shown_prominently(series, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    after_week3 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    recurring.tick(config, root, now=after_week3)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    app.sidebar.radio[0].set_value(next(i for i in config["expected_heads"] if i.endswith("2026-09-29"))).run()
    assert not app.exception
    assert sum("Simulated clock" in w.value for w in app.warning) >= 2      # record banner and attestation panel
    outcome, _, _ = _attest(config, root, "CHG-WEEKLY-2026-09-29", "NO_EXCEPTIONS_NOTED", True,
                            "Constructed week 3, assessed under a simulated clock; noting no exceptions.")
    assert outcome["attestation"]["clock_simulated"] == after_week3.isoformat()


def test_rationale_warnings_shown_at_signing_are_signed_with_the_attestation(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 1)
    recurring.tick(config, root)
    outcome, _, _ = _attest(config, root, "CHG-WEEKLY-2026-09-15", "FAIL", False, "i think is ok to proceed")
    assert outcome["attestation"]["rationale_warnings"], "the contradiction warning must be recorded"
    outcome_clean = outcome["attestation"]
    assert "unqualified approval" in " ".join(outcome_clean["rationale_warnings"])


def test_the_canonical_run_writes_its_own_record(tmp_path):
    import os, subprocess, sys
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "requirements.txt").write_text("pytest>=1\n")
    env = {**os.environ, "GAAR_TEST_ROOT": str(tmp_path), "GAAR_TEST_BATCHES": "1"}
    result = subprocess.run([sys.executable, str(ROOT / "tools/run_all_tests.py")], env=env, text=True,
                            capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    records = list((tmp_path / ".test_runs").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["verdict"] == "COMPLETE RUN, ALL PASSED" and record["collected"] == record["executed"] == 1
    assert record["requirements_sha256"]["requirements.txt"] and record["python"]


def test_a_run_in_an_environment_missing_a_requirement_stops_and_says_so(tmp_path):
    """D25: the v24 Mac round ran in the wrong conda environment; 27 failures hid one missing package."""
    import os, subprocess, sys
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "requirements.txt").write_text("pytest>=1\nnot-a-real-package==1.0\n")
    env = {**os.environ, "GAAR_TEST_ROOT": str(tmp_path), "GAAR_TEST_BATCHES": "1"}
    result = subprocess.run([sys.executable, str(ROOT / "tools/run_all_tests.py")], env=env, text=True,
                            capture_output=True)
    assert result.returncode == 1
    assert "VERDICT: ENVIRONMENT NOT READY — 1 required package(s) missing from" in result.stdout
    assert "conda activate gaar" in result.stdout and "batch 1/1" not in result.stdout      # no tests were run
    record = json.loads(next((tmp_path / ".test_runs").glob("*.json")).read_text())
    assert record["verdict"] == "ENVIRONMENT NOT READY" and record["environment_missing"] == ["not-a-real-package==1.0"]
