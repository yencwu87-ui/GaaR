"""Control impact graph (kit v21): a lapse flags dependants and points at likely causes; it never changes a verdict."""
import json

import pytest

from governance.impact import FINDING_LINKS, ImpactGraph, status_of


@pytest.fixture(scope="module")
def graph():
    return ImpactGraph()


def test_a_lapse_flags_its_dependants_and_the_flag_weakens_with_each_step(graph):
    flags = {f["control"]: f for f in graph.downstream("MAS:M2.2", "none")}
    assert flags["MAS:M2.3"]["flag"] == "RELIANCE_REDUCED" and flags["MAS:M2.3"]["depth"] == 1
    assert flags["MAS:M3.6"]["flag"] == "WATCH" and flags["MAS:M3.6"]["path"] == ["MAS:M2.2", "MAS:M2.3", "MAS:M3.6"]
    assert all(f["depth"] <= 2 for f in flags.values())                       # three steps away: too weak to flag
    assert flags["MAS:M2.3"]["corroborate"] and flags["MAS:M2.3"]["edge_status"] == ["PROPOSED"]


def test_an_effective_control_flags_nothing(graph):
    assert graph.downstream("MAS:M2.2", "full") == [] and graph.downstream("MAS:M2.2", "unknown") == []


def test_a_proposed_edge_can_never_carry_a_complete_weakness_flag(graph):
    assert all(f["flag"] != "RELIANCE_IMPAIRED" for f in graph.downstream("MAS:M2.2", "none"))
    assert graph.edge_cap({"review_status": "PROPOSED", "reliance": "complete"}) == 2
    assert graph.edge_cap({"review_status": "APPROVED", "reliance": "complete"}) == 3      # the unlock: approval


def test_cycles_in_the_catalogue_do_not_loop(graph):
    flags = graph.downstream("MAS:M3.12", "none")                             # M3.12 -> M3.11 -> M3.12
    assert "MAS:M3.12" not in {f["control"] for f in flags}


def test_root_cause_ranks_lapsed_ancestors_first_and_rules_out_effective_ones(graph):
    causes = {c["control"]: c["assessment"] for c in
              graph.root_cause("MAS:M3.6", {"MAS:M3.6": "partial", "MAS:M2.2": "none", "MAS:M3.1": "full"})}
    assert causes["MAS:M2.2"] == "LIKELY_ROOT_CAUSE" and causes["MAS:M3.1"] == "RULED_OUT_ON_THIS_PATH"
    assert causes["MAS:M2.1"] == "UNVERIFIED_TEST_NEXT"


def test_finding_codes_are_the_evidence_for_a_root_cause(graph):
    key = "INTERNAL:CHANGE.MGMT"
    result = graph.analyse({key: "ADVERSE"}, {key: ["SELF_APPROVAL", "CREDENTIAL_NOT_APPROVED_FOR_CHANGE"]})["lapses"][key]
    causes = {c["control"]: c for c in result["root_cause"]}
    assert causes["INTERNAL:CHANGE.APPROVAL"]["assessment"] == "LIKELY_ROOT_CAUSE"
    assert causes["INTERNAL:CHANGE.APPROVAL"]["evidenced_by"] == ["SELF_APPROVAL"]
    assert causes["INTERNAL:CHANGE.FREEZE"]["assessment"] == "UNVERIFIED_TEST_NEXT"          # no finding points there
    down = {f["control"]: f for f in result["downstream"]}
    assert down["INTERNAL:ACCESS.PRIVILEGED"]["evidenced_by"] == ["CREDENTIAL_NOT_APPROVED_FOR_CHANGE"]
    assert set(FINDING_LINKS.values()) <= set(graph.down) | set(graph.up)                    # every link is a real node


def test_a_shared_ancestor_of_two_lapses_is_a_likely_common_cause(graph):
    result = graph.analyse({"MAS:M2.3": "none", "MAS:M3.10": "partial"})
    assert {"control": "MAS:M2.2", "explains": ["MAS:M2.3", "MAS:M3.10"], "status": "UNASSESSED"} in result["common_causes"]


def test_peers_in_another_framework_are_put_on_watch(graph):
    peers = graph.peers("MAS:M3.6")
    assert peers and all(p["flag"] == "WATCH" and p["shared_capabilities"] for p in peers)


def test_nothing_is_a_verdict(graph):
    result = graph.analyse({"MAS:M2.2": "none"})
    assert result["changes_control_verdict"] is False and "not a finding" in result["non_inference"]
    assert "not the same as none" in result["coverage_statement"]
    assert graph.dot({"MAS:M2.2": "none"}).startswith("digraph impact {")


@pytest.mark.parametrize("raw, expected", [("none", "LAPSED"), ("ADVERSE", "LAPSED"), ("partial", "WEAK"),
                                           ("INCONCLUSIVE", "WEAK"), ("full", "EFFECTIVE"),
                                           ("NO_EXCEPTIONS_FOUND", "EFFECTIVE"), (None, "UNASSESSED")])
def test_every_way_a_result_is_written_maps_to_one_state(raw, expected):
    assert status_of(raw) == expected


def test_the_pilot_series_feeds_its_verdicts_and_findings(tmp_path):
    from datetime import datetime, timedelta, timezone
    from tests.test_guards_exercised import _cli, _load
    from governance.impact import statuses_from_pilot
    from governance.production import recurring
    home = tmp_path / "home"
    home.mkdir()
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo").returncode == 0
    config, root = _load(home / "demo/operations.json")
    _cli(home, "demo-inbox", "--config", home / "demo/operations.json", "--week", 1)
    recurring.tick(config, root, now=datetime(2026, 10, 1, 9, tzinfo=timezone(timedelta(hours=8))))
    statuses, findings = statuses_from_pilot(config, root)
    assert statuses == {"INTERNAL:CHANGE.MGMT": "ADVERSE"} and "SELF_APPROVAL" in findings["INTERNAL:CHANGE.MGMT"]
