"""SAFR authoring standard — S1.2 and S2.1 as the calibration pair.

Element count is not a target. Semantic distinction is. Both happen to yield five elements from
the source; that is a result, not a shape either was made to fit.
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.contract_integrity import validate_contract
from governance.decomposition_audit import audit_library

AUTHORED = ("S1.2", "S2.1")
PROCEDURE = re.compile(r"^(obtain|sample|inspect|trace|verify that|confirm that|compare|"
                       r"review the|re-?perform|walk through)\b", re.I)


def _lib():
    return yaml.safe_load((ROOT / "governance/knowledge/control_contracts.yaml")
                          .read_text(encoding="utf-8"))["controls"]


def _by_id():
    return {c["control_id"]: c for c in _lib()}


def test_both_authored_controls_pass_the_decomposition_audit():
    a = audit_library(_lib())
    for cid in AUTHORED:
        found = [f for f in a["findings"] if f["ref"] == cid or f["ref"].startswith(cid + ".")]
        assert not found, f"{cid}: {found}"


def test_contract_integrity_blocks_neither():
    lib = _lib()
    for cid in AUTHORED:
        r = validate_contract(_by_id()[cid], artefacts=[], others=lib)
        assert r["error_count"] == 0, r["findings"]


def test_every_authored_element_cites_the_source_with_a_verbatim_quote():
    """A line range says where to look; a quote says what was read.

    This asserted a `source_locator` string. The stricter standard already present in
    test_safr_s12_s21_authoring.py requires a dict carrying a supporting quote, and that is the
    better bar — a range can be right about the page and wrong about the sentence. Adopted here,
    with the extra check that the quote is actually in the instrument.
    """
    source = (ROOT / "instruments" / "SAFR.txt").read_text(encoding="utf-8")
    for cid in AUTHORED:
        for e in _by_id()[cid]["elements"]:
            loc = e.get("source_locator") or {}
            assert loc.get("instrument", "").endswith("SAFR.txt"), f"{cid}.{e['id']}"
            support = loc.get("support", "")
            assert len(support) > 40, f"{cid}.{e['id']} quote too short to support anything"
            assert support in source, f"{cid}.{e['id']} quote is not verbatim in the instrument"


def test_no_requirement_text_embeds_a_test_procedure():
    """The requirement says what must be true; how to check it lives elsewhere."""
    for cid in AUTHORED:
        for e in _by_id()[cid]["elements"]:
            assert not PROCEDURE.match(e["text"]), f"{cid}.{e['id']}: {e['text'][:60]}"


def test_every_element_carries_requirement_intent_evidence_and_verification():
    for cid in AUTHORED:
        for e in _by_id()[cid]["elements"]:
            assert e.get("text") and e.get("intent")
            assert e.get("expected_evidence")
            assert e["verification"] in {"HUMAN_JUDGEMENT", "DETERMINISTIC", "OUT_OF_BAND"}


def test_verification_is_human_judgement_until_a_provider_exists():
    """Authoring an element does not create an evidence boundary that can decide it."""
    for cid in AUTHORED:
        for e in _by_id()[cid]["elements"]:
            assert e["verification"] == "HUMAN_JUDGEMENT"
            assert e["predicate_available"] is False


def test_the_two_controls_share_no_element_text():
    b = _by_id()
    a, c = {e["text"] for e in b["S1.2"]["elements"]}, {e["text"] for e in b["S2.1"]["elements"]}
    assert not (a & c)


def test_neither_reuses_the_other_element_set_shape():
    """The defect being repaired: same four obligations with a different noun dropped in."""
    b = _by_id()

    def skel(cid):
        t = " ".join(b[cid]["title"].lower().split())
        return tuple(sorted(" ".join(e["text"].lower().split()).replace(t, "<T>")
                            for e in b[cid]["elements"]))
    assert skel("S1.2") != skel("S2.1")


def test_each_element_answers_a_question_the_others_do_not():
    """Weak proxy for semantic distinction: no element's content words subsume another's."""
    stop = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "is", "are", "that", "its",
            "which", "it", "by", "with", "be", "on", "at", "from", "under", "within"}
    for cid in AUTHORED:
        sets = [{w for w in re.findall(r"[a-z]+", e["text"].lower()) if w not in stop and len(w) > 3}
                for e in _by_id()[cid]["elements"]]
        for i, a in enumerate(sets):
            for j, b_ in enumerate(sets):
                if i != j:
                    assert not a <= b_, f"{cid}: element {i+1} is subsumed by element {j+1}"


def test_the_authored_pair_did_not_shrink_the_library():
    assert sum(len(c.get("elements") or []) for c in _lib()) == 538


def test_the_remaining_safr_backlog_is_explicit():
    """Backlog closed: 17 templated controls at the start of this pass, 0 now."""
    a = audit_library(_lib())
    templated = sorted({f["ref"] for f in a["findings"] if f["code"] == "TEMPLATED_SET"})
    assert templated == [], (
        "the SAFR archetype backlog is closed — all 21 controls are now source-decomposed")
