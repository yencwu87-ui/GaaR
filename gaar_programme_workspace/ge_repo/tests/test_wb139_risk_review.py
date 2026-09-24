import copy
import json
from types import SimpleNamespace

import pytest

from governance.risk_review import reconcile_assets, review, validate_review


def package():
    return {"synthetic": True, "snapshots": {
        k: {"scope": "credit-platform-v2.3", "as_of": "2026-09-20T00:00:00Z",
            "source_id": k + "-fixture", "assets": ids}
        for k, ids in {"inventory": ["a", "b", "retired"],
                       "discovery": ["a", "b", "c"],
                       "configuration": ["a", "b"],
                       "vulnerability": ["a", "b"]}.items()}}


def test_equal_counts_do_not_hide_identity_discrepancy():
    p = package()
    before = copy.deepcopy(p)
    r = reconcile_assets(p)
    assert r["inventory_count"] == r["discovered_count"] == 3
    assert r["unregistered_and_missing_both"] == ["c"]
    assert r["inventory_not_discovered_ids"] == ["retired"]
    assert "do not establish" in r["limitation"]
    assert p == before


def test_misaligned_time_is_not_compared():
    p = package()
    p["snapshots"]["discovery"]["as_of"] = "2026-09-19T00:00:00Z"
    assert reconcile_assets(p)["status"] == "NOT_COMPARABLE"


def test_missing_snapshot_is_not_treated_as_zero():
    p = package()
    del p["snapshots"]["configuration"]
    with pytest.raises(ValueError):
        reconcile_assets(p)


def test_zero_denominator_has_no_perfect_score():
    p = package()
    for s in p["snapshots"].values():
        s["assets"] = []
    assert reconcile_assets(p)["unregistered_fraction"] is None


def test_duplicates_do_not_inflate_population():
    p = package()
    p["snapshots"]["discovery"]["assets"].append("c")
    r = reconcile_assets(p)
    assert r["discovered_count"] == 3
    assert r["duplicate_rows"]["discovery"] == 1


def candidate():
    return {"hypotheses": [{"observation_quote": "Asset c is missing from the inventory export.",
            "possible_effect": "It may also be outside patch-management coverage.",
            "related_control_topic": "patch coverage",
            "alternative_explanation": "An ephemeral asset or delayed export could explain it.",
            "proposed_test": "Compare canonical IDs and times across discovery and patch exports.",
            "priority_reason": "A coverage gap may invalidate the patch reporting denominator."}]}


def test_hypothesis_is_not_a_test_or_verified_fact():
    p = candidate()
    r = validate_review(json.dumps(p), p["hypotheses"][0]["observation_quote"])
    assert r["hypotheses"][0]["test_status"] == "NOT_RUN"
    assert r["hypotheses"][0]["status"] == "HYPOTHESIS"
    assert not r["changes_control_verdict"]
    assert not r["independent_challenge"]


@pytest.mark.parametrize("mutation", ["fake_quote", "new_verdict", "executed_test", "no_alternative"])
def test_model_cannot_smuggle_conclusions_or_ungrounded_observations(mutation):
    p = candidate()
    evidence = p["hypotheses"][0]["observation_quote"]
    if mutation == "fake_quote":
        p["hypotheses"][0]["observation_quote"] = "All assets have unpatched critical vulnerabilities."
    elif mutation == "new_verdict":
        p["sufficiency"] = "full"
    elif mutation == "executed_test":
        p["hypotheses"][0]["test_status"] = "PASSED"
    else:
        p["hypotheses"][0]["alternative_explanation"] = ""
    with pytest.raises(ValueError):
        validate_review(json.dumps(p), evidence)


def test_failure_is_visible_not_clean_review():
    r = review(SimpleNamespace(id="M2.2", req="Inventory"), "Some evidence", lambda s, u: "broken")
    assert r["status"] == "UNAVAILABLE"


def test_empty_evidence_does_not_invoke_model():
    def fail(*args):
        raise AssertionError("must not invoke")
    assert review(SimpleNamespace(), "", fail)["status"] == "NOT_EVALUATED"
