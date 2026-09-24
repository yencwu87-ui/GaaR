"""Every refusal must be reached by a test that expects exactly that refusal.

Found by tracing the full suite against the pilot's own code: 36 refusal lines were never reached. One of them
belonged to a test that passed anyway — it accepted any error, and a different guard fired first. So every test
here names the exact refusal it expects, and where a guard sits behind a signature check, a legitimate
key-holder re-signs the tampered document so that only the guard under test can catch it.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/gaar_recurring.py"
WEEK3 = ROOT / "tests/fixtures/constructed_change_pack_week3"
SGT = timezone(timedelta(hours=8))
BEFORE_WEEK3_ENDS = datetime(2026, 9, 24, 11, 0, tzinfo=SGT)
AFTER_WEEK3 = datetime(2026, 10, 1, 9, 0, tzinfo=SGT)


def _cli(home, *args):
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True,
                          env={**os.environ, "HOME": str(home)})


def _load(config_path):
    from governance.operations.runtime import load
    return load(config_path)


def resign(home, root, config, mutate):
    """Change the signed standing authorisation and re-sign it with the demo's own owner/governance key."""
    sys.path.insert(0, str(ROOT / "tools"))
    import gaar_pilot
    from governance.investigation.store import canonical
    path = root / config["standing_authorisation"]
    document = json.loads(path.read_text())
    mutate(document["payload"])
    key = Path(home) / ".gaar-test-keys/owner.key"
    _, owner = gaar_pilot.load_human(str(key), "Test Owner", "owner", root)
    document["signatures"] = [{"role": role, "key_id": owner.key_id,
                               "signature": owner.sign(canonical(document["payload"]).encode())}
                              for role in ("owner", "governance")]
    path.write_text(json.dumps(document))


@pytest.fixture
def series(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo")
    assert result.returncode == 0, result.stderr
    return home, home / "demo/operations.json"


# ---------------------------------------------------------------------------------------------------------
# D14 — arrival before the period ends
# ---------------------------------------------------------------------------------------------------------

def test_a_premature_complete_export_is_quarantined_as_a_signed_integrity_event(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    notices = []
    summary = {s["label"]: s for s in recurring.tick(config, root, notify=notices.append, now=BEFORE_WEEK3_ENDS)}
    week3 = summary["2026-09-29"]
    assert week3["state"] == "NOT_YET_DUE" and week3["integrity_event"]["rule"] == "D14 / runbook E1"
    assert not (root / config["periodic_evidence"]["inbox"] / "2026-09-29").exists()
    moved = root / week3["integrity_event"]["quarantined_to"]
    assert sorted(p.name for p in moved.iterdir()) == ["changes.json", "population.json"]
    assert set(week3["integrity_event"]["files_sha256"]) == {"changes.json", "population.json"}
    journal = recurring._journal(config, root, "CHG-WEEKLY-2026-09-29")
    assert journal.latest("integrity_event")["payload"]["finding"].startswith("an export declared complete")
    assert journal.latest("obligation_reconciliation") is None, "nothing may be assessed from it"
    assert notices.count("2026-09-29: premature complete export quarantined (integrity event)") == 1


def test_an_early_partial_export_waits_and_never_corroborates(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    folder = root / config["periodic_evidence"]["inbox"] / "2026-09-29"
    folder.mkdir(parents=True)
    changes = json.loads((WEEK3 / "changes.json").read_text())
    population = json.loads((WEEK3 / "population.json").read_text())
    changes["collection"]["complete"] = False
    for side in ("primary", "independent"):
        population[side]["complete"] = False
    (folder / "changes.json").write_text(json.dumps(changes))
    (folder / "population.json").write_text(json.dumps(population))
    early = {s["label"]: s for s in recurring.tick(config, root, now=BEFORE_WEEK3_ENDS)}["2026-09-29"]
    assert early["state"] == "EARLY_PARTIAL" and not early.get("integrity_event") and folder.exists()
    later = {s["label"]: s for s in recurring.tick(config, root, now=AFTER_WEEK3)}["2026-09-29"]
    assert later["state"] == "AWAITING_ATTESTATION" and later["verdict"] != "NO_EXCEPTIONS_FOUND"
    rec = recurring._journal(config, root, "CHG-WEEKLY-2026-09-29").latest("obligation_reconciliation")["payload"]
    assert rec["coverage"]["corroborated"] is False


def test_the_signed_slack_window_tolerates_clock_skew_and_nothing_more(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    assert recurring.verify(config, root)["slack_minutes"] == 10
    end = datetime(2026, 9, 29, 0, 0, tzinfo=SGT)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    inside = {s["label"]: s for s in recurring.tick(config, root, now=end - timedelta(minutes=5))}["2026-09-29"]
    assert inside["state"] == "AWAITING_ATTESTATION"                      # 5 minutes early: within slack, runs
    home2 = home.parent / "home2"
    home2.mkdir()
    assert _cli(home2, "authorise", "--constructed-demo", "--workspace", home2 / "demo").returncode == 0
    config2, root2 = _load(home2 / "demo/operations.json")
    _cli(home2, "demo-inbox", "--config", home2 / "demo/operations.json", "--week", 3)
    outside = {s["label"]: s for s in recurring.tick(config2, root2, now=end - timedelta(minutes=30))}["2026-09-29"]
    assert outside.get("integrity_event")                                 # 30 minutes early: quarantined


def test_the_collector_contract_refuses_a_premature_export_on_any_path(series):
    """Defence in depth: the scheduler quarantines, and the collector itself refuses, e.g. a manual Run."""
    from governance.operations.runtime import collect_periodic
    from governance.production import recurring
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    scope = engine.snapshot("CHG-WEEKLY-2026-09-29")[1]["understand"].scope
    with pytest.raises(ValueError, match="D14: changes.json declares complete collection"):
        collect_periodic({**config, "simulated_clock": BEFORE_WEEK3_ENDS.isoformat()}, root, scope)


def test_a_simulated_clock_is_refused_outside_a_constructed_demo(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    resign(home, root, config, lambda payload: payload.update(constructed_demo=False))
    with pytest.raises(ValueError, match="simulated clock is allowed only for a signed constructed demonstration"):
        recurring.tick(config, root, now=AFTER_WEEK3)


def test_a_simulated_clock_is_written_into_the_result(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    recurring.tick(config, root, now=AFTER_WEEK3)
    rec = recurring._journal(config, root, "CHG-WEEKLY-2026-09-29").latest("obligation_reconciliation")["payload"]
    assert rec["clock_simulated"] == AFTER_WEEK3.isoformat()


# ---------------------------------------------------------------------------------------------------------
# The standing authorisation — each guard reached behind a valid signature
# ---------------------------------------------------------------------------------------------------------

def test_missing_signature_is_refused(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    path = root / config["standing_authorisation"]
    document = json.loads(path.read_text())
    document["signatures"] = [s for s in document["signatures"] if s["role"] != "owner"]
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="lacks the owner signature"):
        recurring.verify(config, root)


def test_a_signature_from_the_wrong_role_is_refused(series):
    sys.path.insert(0, str(ROOT / "tools"))
    import gaar_pilot
    from governance.investigation.store import canonical
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    path = root / config["standing_authorisation"]
    document = json.loads(path.read_text())
    _, reviewer = gaar_pilot.load_human(str(home / ".gaar-test-keys/reviewer.key"), "Test Reviewer", "reviewer", root)
    for s in document["signatures"]:
        if s["role"] == "governance":            # the reviewer is a trusted human, but not governance
            s.update(key_id=reviewer.key_id, signature=reviewer.sign(canonical(document["payload"]).encode()))
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="governance signature is not from a trusted human governance"):
        recurring.verify(config, root)


def test_id_inputs_that_disagree_with_the_signed_scope_are_refused(series):
    from governance.production import recurring
    from governance.investigation.store import digest
    home, config_path = series
    config, root = _load(config_path)

    def mutate(payload):
        payload["authorisation_id_inputs"]["system_id"] = "SOME-OTHER-SYSTEM"
        payload["authorisation_id"] = recurring.authorisation_id(payload["authorisation_id_inputs"])
    resign(home, root, config, mutate)
    with pytest.raises(ValueError, match="derived from a different system_id"):
        recurring.verify(config, root)


@pytest.mark.parametrize("change, message", [
    (lambda c: c["periodic_evidence"]["periods"].popitem(), "periodic evidence layout differs"),
    (lambda c: c["periodic_evidence"]["evidence"][0].update(file="other.json"), "evidence file layout differs"),
    (lambda c: c["expected_heads"].update({"CHG-WEEKLY-2026-09-15": "0" * 64}), "is not the investigation that was signed"),
    (lambda c: c["periodic_evidence"].update(slack_minutes=600), "arrival slack window differs"),
    (lambda c: c.update(model_stages="enabled"), "model-stage setting differs"),
])
def test_configuration_that_drifts_from_what_was_signed_is_refused(series, change, message):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    change(config)
    with pytest.raises(ValueError, match=message):
        recurring.verify(config, root)


# ---------------------------------------------------------------------------------------------------------
# D8's signed mapping, the evidence-only reconciliation path, and the attestation guards
# ---------------------------------------------------------------------------------------------------------

def _signed_mapping_document(series):
    from tests.test_recurring import _signed_mapping_with_demo_keys
    home, _ = series
    return _signed_mapping_with_demo_keys(home, home.parent)


def test_a_mapping_document_signed_by_a_non_governance_identity_is_refused(series):
    sys.path.insert(0, str(ROOT / "tools"))
    import gaar_pilot
    from governance.investigation.store import canonical
    from governance.production.reconciliation import verify_signed_mapping
    home, config_path = series
    config, root = _load(config_path)
    path = _signed_mapping_document(series)
    document = json.loads(path.read_text())
    _, reviewer = gaar_pilot.load_human(str(home / ".gaar-test-keys/reviewer.key"), "Test Reviewer", "reviewer", root)
    document.update(key_id=reviewer.key_id, signature=reviewer.sign(canonical(document["payload"]).encode()))
    path.write_text(json.dumps(document))
    config["reconciliation_mapping_document"] = {"path": str(path), "control_id": "CHANGE.MGMT"}
    with pytest.raises(ValueError, match="not signed by a trusted human governance identity"):
        verify_signed_mapping(config, "CHANGE.MGMT", document["payload"]["mapping"])


def test_a_mapping_document_with_a_broken_signature_is_refused(series):
    from governance.production.reconciliation import verify_signed_mapping
    home, config_path = series
    config, root = _load(config_path)
    path = _signed_mapping_document(series)
    document = json.loads(path.read_text())
    document["payload"]["signed_by"] = "Someone Else"                 # changed after signing
    path.write_text(json.dumps(document))
    config["reconciliation_mapping_document"] = {"path": str(path), "control_id": "CHANGE.MGMT"}
    with pytest.raises(ValueError, match="mapping document signature is invalid"):
        verify_signed_mapping(config, "CHANGE.MGMT", document["payload"]["mapping"])


def test_evidence_only_reconciliation_refuses_without_the_signed_manifest(series):
    from governance.production import reconciliation
    from governance.production.journal import Journal
    from governance.operations.runtime import signers_for
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    case = recurring_case = root / "cases_probe"
    case.mkdir()
    journal = Journal(case / "operations.sqlite", config["trusted_keys"])
    executor = signers_for(config, root)["executor"]
    with pytest.raises(ValueError, match="examine is missing and no admitted evidence was supplied"):
        reconciliation.reconcile(config, "CHG-WEEKLY-2026-10-06", engine, journal, executor)
    with pytest.raises(ValueError, match="evidence must match the signed evidence manifest"):
        reconciliation.reconcile(config, "CHG-WEEKLY-2026-10-06", engine, journal, executor, evidence=[object()])


def test_attesting_before_the_record_is_ready_or_after_it_moved_is_refused(series):
    from governance import decisions
    from governance.production import recurring
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    iid = "CHG-WEEKLY-2026-09-29"
    head = engine.snapshot(iid)[0][-1]["record_hash"]
    probe = root / "cases_probe"
    probe.mkdir()
    from governance.production.journal import Journal
    empty = Journal(probe / "operations.sqlite", config["trusted_keys"])
    payload = decisions.build_payload(iid, head, "FAIL", "Attempting to sign before any record exists.")
    with pytest.raises(ValueError, match="deterministic attestation blocked"):
        decisions.attest_deterministic(config, root, iid, payload, engine, empty)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    recurring.tick(config, root, now=AFTER_WEEK3)
    journal = recurring._journal(config, root, iid)
    stale = decisions.build_payload(iid, "0" * 64, "NO_EXCEPTIONS_NOTED", "Signing against a stale head.",
                                    assurance_only_fail=True)
    with pytest.raises(ValueError, match="moved while you were deciding"):
        decisions.attest_deterministic(config, root, iid, stale, engine, journal)


# ---------------------------------------------------------------------------------------------------------
# The periodic collector's path and size guards
# ---------------------------------------------------------------------------------------------------------

def _scope(config, root, iid):
    from governance.investigation import InvestigationEngine, InvestigationStore
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    return engine.snapshot(iid)[1]["understand"].scope


def test_a_period_outside_the_authorisation_is_refused(series):
    from governance.operations.runtime import periodic_folder
    home, config_path = series
    config, root = _load(config_path)
    scope = _scope(config, root, "CHG-WEEKLY-2026-09-29").model_copy(update={"period": "2027-01-01T00:00:00+08:00"})
    with pytest.raises(ValueError, match="period is not covered by the standing authorisation"):
        periodic_folder(config, root, scope)


def test_a_period_folder_may_not_escape_the_inbox(series):
    from governance.operations.runtime import periodic_folder
    home, config_path = series
    config, root = _load(config_path)
    scope = _scope(config, root, "CHG-WEEKLY-2026-09-29")
    config["periodic_evidence"]["periods"][scope.period] = "../../elsewhere"
    with pytest.raises(ValueError, match="period folder escaped the approved inbox"):
        periodic_folder(config, root, scope)


def test_an_export_that_links_outside_its_folder_is_refused(series, tmp_path):
    from governance.operations.runtime import collect_periodic
    home, config_path = series
    config, root = _load(config_path)
    folder = root / config["periodic_evidence"]["inbox"] / "2026-09-29"
    folder.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    shutil.copyfile(WEEK3 / "changes.json", outside)
    (folder / "changes.json").symlink_to(outside)
    shutil.copyfile(WEEK3 / "population.json", folder / "population.json")
    scope = _scope(config, root, "CHG-WEEKLY-2026-09-29")
    with pytest.raises(ValueError, match="periodic export outside its period folder"):
        collect_periodic({**config, "simulated_clock": AFTER_WEEK3.isoformat()}, root, scope)


def test_an_oversized_export_is_refused(series):
    from governance.operations.runtime import collect_periodic
    home, config_path = series
    config, root = _load(config_path)
    folder = root / config["periodic_evidence"]["inbox"] / "2026-09-29"
    folder.mkdir(parents=True)
    with (folder / "changes.json").open("wb") as handle:
        handle.truncate(20_000_001)                                       # sparse: no real 20 MB written
    shutil.copyfile(WEEK3 / "population.json", folder / "population.json")
    scope = _scope(config, root, "CHG-WEEKLY-2026-09-29")
    with pytest.raises(ValueError, match="evidence export exceeds collector budget"):
        collect_periodic({**config, "simulated_clock": AFTER_WEEK3.isoformat()}, root, scope)


# ---------------------------------------------------------------------------------------------------------
# The remaining guards in code this programme built
# ---------------------------------------------------------------------------------------------------------

def test_the_collector_also_refuses_an_early_partial_export(series):
    from governance.operations.runtime import collect_periodic
    home, config_path = series
    config, root = _load(config_path)
    folder = root / config["periodic_evidence"]["inbox"] / "2026-09-29"
    folder.mkdir(parents=True)
    changes = json.loads((WEEK3 / "changes.json").read_text())
    changes["collection"]["complete"] = False
    (folder / "changes.json").write_text(json.dumps(changes))
    population = json.loads((WEEK3 / "population.json").read_text())
    for side in ("primary", "independent"):
        population[side]["complete"] = False
    (folder / "population.json").write_text(json.dumps(population))
    scope = _scope(config, root, "CHG-WEEKLY-2026-09-29")
    with pytest.raises(ValueError, match="arrived before its period ended; nothing is assessed until the period ends"):
        collect_periodic({**config, "simulated_clock": BEFORE_WEEK3_ENDS.isoformat()}, root, scope)


def test_a_period_end_without_a_time_zone_is_refused():
    from governance.production.recurring import plan_periods
    with pytest.raises(ValueError, match="period end must carry a timezone"):
        plan_periods("2026-09-15T00:00:00", 7, 4, "X")


def test_a_missing_pinned_mapping_document_stops_the_series(tmp_path):
    from governance.production import recurring
    from tests.test_recurring import _signed_mapping_with_demo_keys
    home = tmp_path / "home"
    home.mkdir()
    document = _signed_mapping_with_demo_keys(home, tmp_path)
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo", "--mapping", document).returncode == 0
    config, root = _load(home / "demo/operations.json")
    document.unlink()
    with pytest.raises(ValueError, match="pinned by the standing authorisation is missing"):
        recurring.verify(config, root)


def test_reconciliation_without_a_configured_mapping_is_refused(series):
    from governance.production import reconciliation
    from governance.production.journal import Journal
    from governance.operations.runtime import signers_for
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    probe = root / "cases_probe"
    probe.mkdir()
    with pytest.raises(ValueError, match="no reconciliation mapping configured for CHANGE.MGMT"):
        reconciliation.reconcile({**config, "reconciliation_map": {}}, "CHG-WEEKLY-2026-10-06", engine,
                                 Journal(probe / "operations.sqlite", config["trusted_keys"]),
                                 signers_for(config, root)["executor"])


@pytest.mark.parametrize("change, message", [
    (lambda p: p.update(public_key="AAAA"), "result approver key is not pinned by the trust policy"),
    (lambda p: p.update(roles=["owner"]), "this identity does not hold the result_approver role"),
    (lambda p: p.update(actor_type="service"), "a result decision requires a human identity"),
])
def test_the_attesting_identity_is_checked(series, change, message):
    import copy
    from governance.decisions import approver_signer
    home, config_path = series
    config, root = _load(config_path)
    config = copy.deepcopy(config)
    change(config["trusted_keys"][config["signers"]["result_approver"]["key_id"]])
    with pytest.raises(ValueError, match=message):
        approver_signer(config, root)


def test_a_pilot_attestation_on_an_unfinished_record_is_refused(series):
    from governance import decisions
    from governance.production.journal import Journal
    from governance.investigation import InvestigationEngine, InvestigationStore
    home, config_path = series
    config, root = _load(config_path)
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    iid = "CHG-WEEKLY-2026-10-06"
    head = engine.snapshot(iid)[0][-1]["record_hash"]
    probe = root / "cases_probe"
    probe.mkdir()
    payload = decisions.build_payload(iid, head, "FAIL", "Attempting a pilot attestation with no record at all.")
    with pytest.raises(ValueError, match="pilot attestation blocked"):
        decisions.attest(config, root, iid, payload, engine, Journal(probe / "operations.sqlite", config["trusted_keys"]))
