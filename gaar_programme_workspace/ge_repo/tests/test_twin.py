"""The digital twin (kit v22): seeded, randomly placed violations; a sealed key; the pipeline's own checks scored."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

from governance.twin.generator import KNOWN_BLIND, VIOLATIONS, generate_period, load_key, run_checks, score, seal


def test_the_checks_catch_every_planted_violation_and_nothing_else_across_many_random_weeks():
    planted = detected = false_positives = 0
    kinds = set()
    for seed in range(120):
        g = generate_period(seed, "2026-09-29T00:00:00+08:00")
        r = score(run_checks(g), g["answer_key"], [c["event_id"] for c in g["changes"]["changes"]])
        planted, detected, false_positives = planted + r["planted"], detected + r["detected"], false_positives + len(r["false_positives"])
        kinds |= {p["violation"] for p in g["answer_key"]["planted"]}
    assert planted > 250 and detected == planted and false_positives == 0
    assert kinds == set(VIOLATIONS)                                          # every violation type was exercised


def _weeks(n=400):
    for seed in range(n):
        g = generate_period(seed, ("2026-09-29T00:00:00+08:00", "2026-10-06T00:00:00+08:00")[seed % 2])
        yield g, score(run_checks(g), g["answer_key"], [c["event_id"] for c in g["changes"]["changes"]])


def test_a_change_that_slides_into_a_freeze_must_be_caught_for_both():
    """Adjudication A-001: the incidental freeze breach is a real violation, so the key requires it, not tolerates it."""
    incidental = 0
    for g, r in _weeks():
        for p in g["answer_key"]["planted"]:
            if p["incidental"]:
                incidental += 1
                assert "FREEZE_WITHOUT_PRIOR_EXCEPTION" in p["expected"] and "FREEZE_WITHOUT_PRIOR_EXCEPTION" not in p["permitted"]
                assert p["event_id"] not in {m["event_id"] for m in r["missed"]}
        assert r["incidental_codes"] == sum(len(p["incidental"]) for p in g["answer_key"]["planted"] if not p["known_blind"])
    assert incidental > 0


def test_a_namesake_grant_is_a_measured_blind_spot_not_a_detection():
    """Adjudication A-002: two people with one name defeat a names-only check. Planted on purpose, scored apart."""
    blind = detected = 0
    for g, r in _weeks():
        collisions = [p for p in g["answer_key"]["planted"] if p["violation"] == "IDENTITY_COLLISION"]
        assert all(p["known_blind"] for p in collisions)
        assert not {p["event_id"] for p in collisions} & {m["event_id"] for m in r["missed"]}    # not in the headline
        blind, detected = blind + r["known_blind"]["planted"], detected + r["known_blind"]["detected"]
        for p in collisions:                         # the records really do show two different people
            change = next(c for c in g["changes"]["changes"] if c["event_id"] == p["event_id"])
            grant = next(x for x in g["changes"]["privilege_grants"] if x["grant_id"] == f"PG-{p['event_id']}")
            assert grant["actor_id"] == change["actor_id"] and grant["actor_uid"] != change["actor_uid"]
    assert blind > 20 and detected == 0 and "unique actor IDs" in KNOWN_BLIND["IDENTITY_COLLISION"]


def test_the_adjudication_log_follows_the_rule_and_needs_a_named_person():
    from governance.twin import adjudication
    ids = [e["id"] for e in adjudication.entries()]
    assert ids == ["A-001", "A-002"]
    for e in adjudication.entries():
        test_file, test_name = e["regression_test"].split("::")
        assert f"def {test_name}(" in (ROOT / test_file).read_text()
    assert {s["state"] for s in adjudication.status()} == {"AWAITING_A_NAMED_PERSON"}
    adjudication.confirm("A-001", "Test Owner", "read seed 54")
    assert [s["state"] for s in adjudication.status()] == ["HUMAN_ADJUDICATED", "AWAITING_A_NAMED_PERSON"]
    with pytest.raises(ValueError, match="^unknown adjudication A-999$"):
        adjudication.confirm("A-999", "Test Owner")
    with pytest.raises(ValueError, match="^a confirmation needs the name of the person who read the data$"):
        adjudication.confirm("A-002", " ")


@pytest.mark.parametrize("change, message", [
    ({"classification": "both"}, "A-001: classification must be one of key_error, check_error, generator_artifact"),
    ({"fix_side": "check"}, "A-001: a key_error is fixed on the key side only"),
    ({"regression_test": ""}, "A-001: an adjudication needs the reading of the data and a regression test"),
])
def test_an_adjudication_that_breaks_the_rule_is_refused(tmp_path, change, message):
    import yaml
    from governance.twin import adjudication
    data = yaml.safe_load(adjudication.LOG.read_text())
    data["entries"][0].update(change)
    log = tmp_path / "log.yaml"
    log.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="^" + message + "$"):
        adjudication.entries(log)


def test_the_same_seed_gives_the_same_week_and_different_seeds_do_not():
    a, b, c = (generate_period(s, "2026-09-29T00:00:00+08:00") for s in (5, 5, 6))
    assert a == b and a["answer_key"]["planted"] != c["answer_key"]["planted"]


def test_the_scorer_notices_a_miss_and_a_false_positive():
    g = generate_period(11, "2026-09-29T00:00:00+08:00", violation_rate=0.6)
    found = run_checks(g)
    victim = g["answer_key"]["planted"][0]["event_id"]
    found.pop(victim, None)                                                  # pretend a check went blind
    clean = next(c["event_id"] for c in g["changes"]["changes"] if c["event_id"] not in {p["event_id"] for p in g["answer_key"]["planted"]})
    found[clean] = {"SELF_APPROVAL"}                                         # and one fired on a clean change
    r = score(found, g["answer_key"], [c["event_id"] for c in g["changes"]["changes"]])
    assert [m["event_id"] for m in r["missed"]] == [victim] and r["false_positives"] == [{"event_id": clean, "codes": ["SELF_APPROVAL"]}]


def test_every_export_is_marked_constructed():
    g = generate_period(1, "2026-09-29T00:00:00+08:00")
    assert g["changes"]["synthetic"] is True and g["changes"]["data_classification"] == "CONSTRUCTED_TEST_DATA"
    assert "not independent truth" in g["answer_key"]["provenance"]


def test_a_sealed_key_that_is_changed_afterwards_is_refused(tmp_path):
    g = generate_period(2, "2026-09-29T00:00:00+08:00")
    sealed = seal(g["answer_key"], tmp_path / "keys")
    assert load_key(sealed["key"]) == json.loads(json.dumps(g["answer_key"]))
    path = tmp_path / "keys" / sealed["key"].split("/")[-1]
    path.write_text(path.read_text().replace('"seed": 2', '"seed": 3'))
    with pytest.raises(ValueError, match="^answer key does not match its sealed commitment; it was changed after sealing$"):
        load_key(path)


def test_twin_weeks_run_through_the_real_pilot_and_score_perfectly(tmp_path):
    import importlib
    from types import SimpleNamespace
    from tests.test_guards_exercised import _cli, _load
    from governance.production import recurring
    tool = importlib.import_module("tools.gaar_twin")
    home = tmp_path / "home"
    home.mkdir()
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "twin", "--periods", 5).returncode == 0
    config_path = home / "twin/operations.json"
    for week in range(1, 6):
        tool.inbox(SimpleNamespace(config=str(config_path), week=week, seed=100 + week))
    config, root = _load(config_path)
    recurring.tick(config, root, now=datetime(2026, 11, 1, 9, tzinfo=timezone(timedelta(hours=8))))
    result = tool.score_series(SimpleNamespace(config=str(config_path)))
    assert len(result["periods"]) == 5 and result["totals"]["planted"] == result["totals"]["detected"] > 0
    assert result["totals"]["false_positives"] == 0 and "self-authored" in result["provenance"]
    assert not list((root / config["periodic_evidence"]["inbox"]).rglob("key-*.json"))     # keys never in the evidence
