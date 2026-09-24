"""One canonical requirement text, and three separate verification facts."""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance import semantic_canon as sc
from governance import verification_semantics as vs


# ------------------------------------------------------------------ canonical text

def test_every_derived_view_agrees_with_the_canon():
    """The D1.2 drift class: same element, three files, two repaired, one missed."""
    c = sc.check()
    assert c["clean"], sc.report(c)


def test_all_seven_derived_views_are_actually_walked():
    c = sc.check()
    assert len(c["views"]) == 7
    assert sum(v["elements"] for v in c["views"]) > 1000


def test_sync_only_runs_one_direction():
    """A derived file must not be able to promote its own wording to canonical."""
    src = (ROOT / "governance" / "semantic_canon.py").read_text(encoding="utf-8")
    assert "def sync" in src
    for reverse in ("def reverse_sync", "def promote", "canonical_from_derived"):
        assert f"{reverse}(" not in src


def test_drift_is_detected_not_tolerated(tmp_path):
    canon = tmp_path / "governance/knowledge/control_contracts.yaml"
    canon.parent.mkdir(parents=True)
    canon.write_text(yaml.safe_dump({"controls": [
        {"control_id": "X", "elements": [{"id": "e1", "text": "Records are kept."}]}]}))
    view = tmp_path / "governance/knowledge/contracts/mas.yaml"
    view.parent.mkdir(parents=True)
    view.write_text(yaml.safe_dump({"controls": [
        {"control_id": "X", "elements": [{"id": "e1", "text": "Records are retained."}]}]}))
    c = sc.check(tmp_path)
    assert c["drift"] == 1 and not c["clean"]
    sc.sync(tmp_path)
    assert sc.check(tmp_path)["clean"]


# ------------------------------------------------------------------ verification semantics

def test_predicate_presence_alone_does_not_make_an_element_deterministic():
    """`verification_reason` was literally "Executable predicate specification exists."."""
    r = vs.resolve({"predicate_spec": {"present": True, "requires": ["reviewer_identity"]}})
    assert r["predicate_available"] is True
    assert r["verification"] == vs.HUMAN_JUDGEMENT
    assert "no declared provider supplies" in r["verification_reason"]


def test_a_declared_provider_that_supplies_the_observations_makes_it_deterministic():
    caps = [{"provider": "IdentityPlugin", "observes": ["reviewer_identity", "developer_identity"]}]
    r = vs.resolve({"predicate_spec": {"present": True,
                                       "requires": ["reviewer_identity", "developer_identity"]}},
                   capabilities=caps)
    assert r["verification"] == vs.DETERMINISTIC


def test_partial_capability_is_not_enough():
    caps = [{"provider": "IdentityPlugin", "observes": ["reviewer_identity"]}]
    r = vs.resolve({"predicate_spec": {"present": True,
                                       "requires": ["reviewer_identity", "developer_identity"]}},
                   capabilities=caps)
    assert r["verification"] == vs.HUMAN_JUDGEMENT


def test_out_of_band_survives_a_capability():
    caps = [{"provider": "P", "observes": ["x"]}]
    r = vs.resolve({"predicate_spec": {"present": True, "requires": ["x"]},
                    "verification": vs.OUT_OF_BAND}, capabilities=caps,
                   observability="out_of_band")
    assert r["verification"] == vs.OUT_OF_BAND


def test_a_registry_corpus_conflict_is_recorded_not_resolved():
    caps = [{"provider": "P", "observes": ["x"]}]
    r = vs.resolve({"predicate_spec": {"present": True, "requires": ["x"]}},
                   capabilities=caps, observability="ordinary")
    assert r["verification"] == vs.DETERMINISTIC
    assert r["corpus_observability"] == "ordinary"
    assert "Both are retained" in r["verification_conflict"]


def test_the_live_registry_claims_no_deterministic_elements():
    """With no providers declared, nothing is deterministically evaluable — the honest answer.

    Nineteen elements previously claimed DETERMINISTIC on the strength of a predicate existing,
    including M3.6 e6 ("reviewed by parties not involved in its development"), which the
    adjudicated corpus treats as human judgement.
    """
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    modes = [e.get("verification") for c in doc["controls"] for e in c["elements"]]
    assert modes.count(vs.DETERMINISTIC) == 0
    assert modes.count(vs.OUT_OF_BAND) == 1


def test_m36_elements_carry_their_corpus_observability():
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    m36 = next(c for c in doc["controls"] if c["control_id"] == "M3.6")
    obs = [e.get("corpus_observability") for e in m36["elements"]]
    assert obs.count("ordinary") == 7
    assert obs.count("conditional") == 6
    assert obs.count("out_of_band") == 1


def test_predicate_availability_is_still_recorded():
    """Downgrading the mode must not lose the fact that the predicate exists."""
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    m36 = next(c for c in doc["controls"] if c["control_id"] == "M3.6")
    assert sum(1 for e in m36["elements"] if e.get("predicate_available")) == 14


def test_the_registry_summary_is_not_a_stale_cache():
    """It claimed 562 elements and 19 deterministic after both had changed.

    A denormalised summary nobody recomputes is the same drift class as a derived element text
    nobody syncs — it just fails later and more confusingly, because a count looks authoritative.
    """
    import collections
    doc = yaml.safe_load((ROOT / "governance/knowledge/semantic_registry.yaml")
                         .read_text(encoding="utf-8"))
    els = [e for c in doc["controls"] for e in (c.get("elements") or [])]
    ver = collections.Counter(e.get("verification") for e in els)
    s = doc["summary"]
    assert s["elements_total"] == len(els)
    assert s["deterministic_elements"] == ver.get("DETERMINISTIC", 0)
    assert s["human_judgement_elements"] == ver.get("HUMAN_JUDGEMENT", 0)
    assert s["out_of_band_elements"] == ver.get("OUT_OF_BAND", 0)
    # Both facts, as agreed: the machinery exists, the evidence boundary does not yet feed it.
    #
    # 20, not the 19 the old headline reported. 19 counted M3.6's 13 plus D1.2's 6 and dropped
    # M3.6.e14, which has a predicate specification and is out-of-band. Predicate availability
    # and verification mode are different facts, so the count of the first must not be reduced
    # by the second — that reduction was the original conflation in miniature.
    assert s["predicate_specifications_available"] == 20
    assert s["deterministic_elements"] == 0
    assert s["out_of_band_elements"] == 1


def test_structural_drift_is_detected_not_only_text_drift():
    """A text-only canonicaliser is a partial one.

    Re-authoring S2.1 from four elements to five left `safr.yaml` and `semantic_registry.yaml`
    at four. Every text comparison passed, because the fifth element simply was not there to
    compare — and `coverage_summary()` reported 85 SAFR elements while the canon held 86.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        canon = root / "governance/knowledge/control_contracts.yaml"
        canon.parent.mkdir(parents=True)
        canon.write_text(yaml.safe_dump({"controls": [{"control_id": "X", "elements": [
            {"id": "e1", "text": "One."}, {"id": "e2", "text": "Two."}]}]}))
        view = root / "governance/knowledge/contracts/safr.yaml"
        view.parent.mkdir(parents=True)
        view.write_text(yaml.safe_dump({"controls": [{"control_id": "X", "elements": [
            {"id": "e1", "text": "One."}]}]}))
        c = sc.check(root)
        assert c["drift"] == 0, "text matches on every shared element"
        assert c["missing"] == 1 and not c["clean"]
        sc.sync(root)
        assert sc.check(root)["clean"]


def test_structural_sync_adds_only_the_id_and_the_text():
    """A derived view's own fields are regenerated by the module that owns them.

    Inventing a verification mode or an expected-evidence list here would put a guess into a
    governed file.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        canon = root / "governance/knowledge/control_contracts.yaml"
        canon.parent.mkdir(parents=True)
        canon.write_text(yaml.safe_dump({"controls": [{"control_id": "X", "elements": [
            {"id": "e1", "text": "One.", "verification": "HUMAN_JUDGEMENT",
             "expected_evidence": ["a"]}]}]}))
        view = root / "governance/knowledge/contracts/safr.yaml"
        view.parent.mkdir(parents=True)
        view.write_text(yaml.safe_dump({"controls": [{"control_id": "X", "elements": []}]}))
        sc.sync(root)
        added = yaml.safe_load(view.read_text())["controls"][0]["elements"]
        assert added == [] or set(added[0]) == {"id", "text"}
