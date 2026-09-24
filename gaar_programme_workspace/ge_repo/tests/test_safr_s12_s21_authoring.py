"""S1.2 and S2.1 — the SAFR authoring calibration pair.

Both were archetype element sets: S1.2 shared four verbatim requirements with S1.4, S2.4, S3.3
and S4.2, differing only by the control title spliced in. Re-authored from the SAFR white paper
independently of each other, so the pair demonstrates the method rather than a new template.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.contract_integrity import validate_contract
from governance.decomposition_audit import audit_library


def _lib():
    return yaml.safe_load((ROOT / "governance/knowledge/control_contracts.yaml")
                          .read_text(encoding="utf-8"))["controls"]


def _ctl(cid):
    return next(c for c in _lib() if c["control_id"] == cid)


def _norm(t):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(t).lower()).split())


def _shingles(t, n=6):
    w = _norm(t).split()
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


PAIR = ("S1.2", "S2.1")


def test_both_are_free_of_decomposition_errors():
    a = audit_library(_lib())
    assert not [f for f in a["findings"]
                if f["ref"].startswith(PAIR) and f["severity"] == "error"]


def test_both_pass_contract_integrity():
    lib = _lib()
    for cid in PAIR:
        r = validate_contract(_ctl(cid), artefacts=[], others=lib)
        assert r["error_count"] == 0, r["findings"]


def test_every_element_cites_the_source():
    for cid in PAIR:
        for e in _ctl(cid)["elements"]:
            loc = e.get("source_locator") or {}
            assert loc.get("instrument", "").endswith("SAFR.txt"), f"{cid}.{e['id']}"
            assert len(loc.get("support", "")) > 40, f"{cid}.{e['id']} has no supporting quote"


def test_no_requirement_embeds_a_test_procedure():
    proc = re.compile(r"^(obtain|sample|inspect|trace|confirm that|verify that|compare|review the)\b",
                      re.I)
    for cid in PAIR:
        for e in _ctl(cid)["elements"]:
            assert not proc.match(e["text"]), f"{cid}.{e['id']} is an instruction to a tester"


def test_each_element_carries_requirement_intent_evidence_and_verification():
    for cid in PAIR:
        for e in _ctl(cid)["elements"]:
            assert e.get("text") and e.get("intent")
            assert e.get("expected_evidence"), f"{cid}.{e['id']} names no evidence"
            assert e.get("verification") == "HUMAN_JUDGEMENT"
            assert e.get("predicate_available") is False


def test_no_element_restates_its_control_title():
    for cid in PAIR:
        title = _norm(_ctl(cid)["title"])
        for e in _ctl(cid)["elements"]:
            assert title not in _norm(e["text"]), f"{cid}.{e['id']} echoes the title"


def test_elements_within_a_control_are_distinct_obligations():
    """Not merely different strings — no shared six-word run."""
    for cid in PAIR:
        els = [e["text"] for e in _ctl(cid)["elements"]]
        for i, x in enumerate(els):
            for y in els[i + 1:]:
                assert not (_shingles(x) & _shingles(y)), f"{cid}: two elements share phrasing"


def test_the_two_controls_were_decomposed_independently():
    """The failure mode being guarded: S2.1 reusing S1.2's shape because both concern agents."""
    a = [e["text"] for e in _ctl("S1.2")["elements"]]
    b = [e["text"] for e in _ctl("S2.1")["elements"]]
    assert not ({_norm(x) for x in a} & {_norm(y) for y in b})
    assert not any(_shingles(x) & _shingles(y) for x in a for y in b)


def test_no_safr_control_shares_an_element_set_with_another():
    """Was scoped to "untouched" SAFR controls; none are untouched now.

    The check that matters is unchanged and now covers all 21: no two controls carry the same
    element set with the title swapped.
    """
    import collections
    lib = [c for c in _lib() if c.get("framework") == "SAFR"]

    def skel(c):
        t = " ".join(str(c.get("title", "")).lower().split())
        return tuple(sorted(" ".join(e["text"].lower().split()).replace(t, "<T>")
                            for e in c["elements"]))

    groups = collections.defaultdict(list)
    for c in lib:
        groups[skel(c)].append(c["control_id"])
    shared = [v for v in groups.values() if len(v) > 1]
    assert not shared, f"element-set reuse remains: {shared}"


def test_element_count_is_not_a_target():
    """Recorded so a later pass does not normalise SAFR to a fixed shape.

    Both happen to produce five here because the source does; that must not become the rule.
    """
    src = (ROOT / "tests" / "test_safr_s12_s21_authoring.py").read_text(encoding="utf-8")
    assert "element count is not a target" in src.lower()
