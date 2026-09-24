"""A source upload is evidence for change analysis, never an authorisation to change."""
import ast
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance import mas_change_review as CR

PAPER = ROOT / "instruments/Final_Consultation_Paper_on_Guidelines_on_AI_Risk_Management_ForRelease.txt"


def _lib():
    return yaml.safe_load((ROOT / "governance/knowledge/control_contracts.yaml")
                          .read_text(encoding="utf-8"))["controls"]


# ------------------------------------------------------------------ the asymmetry

def test_the_module_cannot_write_to_the_canon():
    """The thing that analyses a change must not be the thing authorised to make it."""
    tree = ast.parse((ROOT / "governance/mas_change_review.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"write_text", "write_bytes", "safe_dump", "dump"}, \
                f"the review module writes: {node.func.attr}"


def test_the_artefact_declares_itself_review_only():
    a = CR.review(_lib(), PAPER, uploaded_by="t")
    assert a["artefact"] == "REVIEW_ONLY"
    assert a["canon_modified"] is False
    assert a["source"]["authorises_change"] is False
    assert a["source"]["status"] == "SOURCE_UNDER_REVIEW"


def test_the_canon_is_byte_identical_after_a_review():
    import hashlib
    p = ROOT / "governance/knowledge/control_contracts.yaml"
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    CR.review(_lib(), PAPER, uploaded_by="t")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before


# ------------------------------------------------------------------ the four states stay apart

def test_semantic_change_is_never_populated_by_the_tool():
    """Lexical matching cannot tell a changed obligation from a differently worded one."""
    a = CR.review(_lib(), PAPER, uploaded_by="t")
    for c in a["controls"]:
        for e in c["elements"]:
            assert e["semantic_change"] is None
            assert e["proposed_revision"] is None
            assert e["approved_revision"] is None


def test_the_tool_reports_source_match_only():
    a = CR.review(_lib(), PAPER, uploaded_by="t")
    bands = {e["source_match"] for c in a["controls"] for e in c["elements"]}
    assert bands <= {"STRONG", "PARTIAL", "NONE"}


def test_a_partial_match_is_a_prompt_to_read_not_a_change_claim():
    a = CR.review(_lib(), PAPER, uploaded_by="t")
    partial = next(e for c in a["controls"] for e in c["elements"]
                   if e["source_match"] == "PARTIAL")
    assert "read it before concluding anything" in partial["basis"]
    assert partial["review_required"] is True
    assert "not a claim that the obligation changed" in a["note"]


# ------------------------------------------------------------------ provenance

def test_the_source_is_fingerprinted_before_comparison():
    fp = CR.fingerprint(PAPER, uploaded_by="wu yenching")
    assert len(fp["sha256"]) == 64 and fp["bytes"] > 0
    assert fp["uploaded_by"] == "wu yenching" and fp["uploaded_at"]


def test_an_unattributed_upload_is_recorded_as_such():
    assert CR.fingerprint(PAPER)["uploaded_by"] == "unrecorded"


def test_the_artefact_names_the_source_it_ran_against():
    a = CR.review(_lib(), PAPER, uploaded_by="t")
    assert a["source"]["file"] == PAPER.name
    assert a["source"]["sha256"]


# ------------------------------------------------------------------ the matcher

def test_containment_is_asymmetric_by_design():
    """Jaccard scored every element CHANGED against the paper they came from."""
    el = "independent validation is performed before deployment"
    passage = ("Where the risk materiality is assessed as high, an FI should perform formal "
               "independent validation before deployment by competent personnel.")
    assert CR._overlap(el, passage) > CR._overlap(passage, el)
    assert CR._overlap(el, passage) >= 0.6


def test_an_element_absent_from_the_source_gets_no_candidates():
    pool = CR.passages("Wholly unrelated text about maritime insurance and cargo manifests. " * 4)
    r = CR.compare_element({"id": "e1", "text": "The board approves the AI risk appetite annually."},
                           pool)
    assert r["source_match"] == "NONE" and r["candidates"] == []


def test_passages_are_addressable():
    pool = CR.passages(PAPER.read_text(encoding="utf-8", errors="replace"))
    assert pool and all(p["passage_id"].startswith("p") for p in pool)
    assert len({p["passage_id"] for p in pool}) == len(pool)


# ------------------------------------------------------------------ reviewer determination

def _row(match="PARTIAL", score=0.43):
    return {"element_id": "e2", "governed_text": "The board approves the AI risk appetite annually.",
            "source_match": match, "match_score": score, "semantic_change": None,
            "proposed_revision": None, "approved_revision": None}


def test_unchanged_is_a_human_determination_not_a_score():
    """A matcher scoring 0.92 has retrieved a passage, not determined that nothing changed."""
    assert CR.UNCHANGED in CR.DETERMINATIONS
    r = CR.record_determination(_row("STRONG", 0.92), determination=CR.UNCHANGED,
                                rationale="Paragraph 2.1 states the same obligation as governed.",
                                reviewer="wu yenching")
    assert r["reviewer_determination"]["determination"] == CR.UNCHANGED
    assert r["reviewer_determination"]["source_match_at_determination"] == "STRONG"


def test_a_determination_must_name_its_reviewer():
    with pytest.raises(CR.DeterminationError):
        CR.record_determination(_row(), determination=CR.UNCHANGED,
                                rationale="a rationale long enough", reviewer="  ")


def test_a_determination_needs_a_rationale_that_can_be_reargued():
    with pytest.raises(CR.DeterminationError):
        CR.record_determination(_row(), determination=CR.UNCHANGED, rationale="fine",
                                reviewer="wu yenching")


def test_changed_and_new_must_name_the_passages_read():
    """Both assert what the source now says; an assertion about a document names the part read."""
    for d in (CR.CHANGED, CR.NEW):
        with pytest.raises(CR.DeterminationError):
            CR.record_determination(_row(), determination=d,
                                    rationale="the wording differs materially here",
                                    reviewer="wu yenching")


def test_unchanged_and_removed_do_not_require_passages():
    for d in (CR.UNCHANGED, CR.REMOVED):
        CR.record_determination(_row(), determination=d,
                                rationale="the obligation no longer appears in the source",
                                reviewer="wu yenching")


# ------------------------------------------------------------------ ordering is the control

def test_a_revision_cannot_precede_a_determination():
    """A revision proposed before anyone determined the obligation changed is a rewrite in
    search of a justification, and the tool should not be able to express it."""
    with pytest.raises(CR.DeterminationError):
        CR.propose_revision(_row(), text="new text", author="a", basis="b")


def test_a_revision_cannot_follow_an_unchanged_determination():
    r = CR.record_determination(_row(), determination=CR.UNCHANGED,
                                rationale="the obligation is unchanged in the new source",
                                reviewer="wu yenching")
    with pytest.raises(CR.DeterminationError):
        CR.propose_revision(r, text="new text", author="a", basis="b")


def test_the_author_of_a_revision_cannot_approve_it():
    r = CR.record_determination(_row(), determination=CR.CHANGED,
                                rationale="paragraph 3.2 adds a tolerance statement requirement",
                                reviewer="wu yenching", passages_read=["p0042"])
    r = CR.propose_revision(r, text="The board approves appetite and tolerance annually.",
                            author="wu yenching", basis="para 3.2")
    with pytest.raises(CR.DeterminationError):
        CR.approve_revision(r, approver="wu yenching", authority="Head of MRM")
    ok = CR.approve_revision(r, approver="r menon", authority="Model Risk Committee chair")
    assert ok["approved_revision"]["supersedes"] == _row()["governed_text"]


def test_approval_still_writes_nothing_to_the_canon():
    import hashlib
    p = ROOT / "governance/knowledge/control_contracts.yaml"
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    r = CR.record_determination(_row(), determination=CR.CHANGED, rationale="materially different",
                                reviewer="w", passages_read=["p1"])
    r = CR.propose_revision(r, text="t", author="a", basis="b")
    CR.approve_revision(r, approver="b", authority="chair")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before


# ------------------------------------------------------------------ the right objective

def test_retrieval_adequacy_is_not_computable_before_determinations_exist():
    """Which is why the matcher should not be tuned first."""
    a = CR.review(_lib(), PAPER, uploaded_by="t")
    r = CR.retrieval_adequacy(a)
    assert r["measurable"] is False
    assert "against what a reviewer needed" in r["reason"]


def test_a_retrieval_miss_is_defined_against_the_reviewer_not_the_score():
    """A miss requires the reviewer to say where they found it.

    An earlier version of this test counted `source_match == NONE` plus any determination as a
    miss. That is too loose: a reviewer may determine UNCHANGED from a passage retrieval *did*
    surface elsewhere in the control, or from knowing the paper. Only `reviewer_found_passages`
    establishes that they needed something retrieval did not show them, so the conservative
    definition is the correct one — a miss is a claim about retrieval and needs evidence.
    """
    a = {"controls": [{"elements": [
        CR.record_determination(_row("NONE", 0.0), determination=CR.UNCHANGED,
                                rationale="found the obligation at section 4 by reading",
                                reviewer="w", reviewer_found_passages=["p0099"]),
        CR.record_determination(_row("STRONG", 0.9), determination=CR.UNCHANGED,
                                rationale="the retrieved passage states it", reviewer="w")]}]}
    r = CR.retrieval_adequacy(a)
    assert r["measurable"] and r["retrieval_misses"] == 1 and r["miss_rate"] == 0.5
    assert "not raising similarity scores" in r["note"]


def test_a_determination_without_a_located_passage_is_not_counted_as_a_miss():
    a = {"controls": [{"elements": [
        CR.record_determination(_row("NONE", 0.0), determination=CR.UNCHANGED,
                                rationale="the obligation is unchanged in the new source",
                                reviewer="w")]}]}
    assert CR.retrieval_adequacy(a)["retrieval_misses"] == 0


def test_progress_reports_what_is_outstanding():
    a = {"controls": [{"elements": [_row(), CR.record_determination(
        _row(), determination=CR.UNCHANGED, rationale="unchanged in the new source",
        reviewer="w")]}]}
    p = CR.determination_progress(a)
    assert p["rows"] == 2 and p["determined"] == 1 and p["outstanding"] == 1
    assert p["ready_for_new_version"] is False


# ------------------------------------------------------------------ the review surface

def _tab():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return src.split("with tab_c:")[1]


def test_the_surface_shows_the_canonical_element_not_a_regenerated_one():
    """Rule 1. Regenerating from the source or the control title is the F01/F03 failure mode."""
    tab = _tab()
    assert 'st.info(_row["governed_text"])' in tab
    for rebuild in ("yaml.safe_load", "control_contracts.yaml", "c['title']"):
        assert rebuild not in tab


def test_it_shows_passages_exactly_as_retrieved():
    """Rule 2. This is what makes source_match_at_determination meaningful."""
    tab = _tab()
    assert 'st.text(_c["text"])' in tab
    assert "_row[\"candidates\"]" in tab
    assert "Retrieval surfaced nothing for this element." in tab


def test_the_score_is_labelled_as_retrieval_not_as_a_recommendation():
    """Rule 3. 0.92 is retrieval information, not evidence that UNCHANGED is correct."""
    tab = _tab()
    assert "This is retrieval information" in tab
    assert "not evidence that any particular" in tab


def test_no_determination_is_defaulted():
    """Rule 4. The initial state must be genuinely unset."""
    tab = _tab()
    assert "index=None" in tab
    for preset in ('index=0', 'value="UNCHANGED"', 'default="UNCHANGED"'):
        assert preset not in tab


def test_the_ui_enforces_the_same_contract_as_the_determination_layer():
    """Rule 5. CHANGED/NEW require passages read — enforced, not collected optionally."""
    tab = _tab()
    assert '_need = _det in ("CHANGED", "NEW")' in tab
    assert "required for CHANGED / NEW" in tab
    assert "except CR.DeterminationError" in tab, "the layer's refusal must surface to the user"


def test_the_surface_offers_the_retrieval_miss_path():
    """The observation retrieval_adequacy is built from."""
    tab = _tab()
    assert "Passages you found that retrieval did not surface" in tab
    assert "reviewer_found_passages=" in tab
    assert "reviewer_found_basis=" in tab


def test_the_surface_calls_only_the_non_mutating_entry_point():
    tab = _tab()
    assert "CR.record_determination" in tab
    for mutation in ("modify_control", "update_element", "rewrite_contract", "write_text",
                     "safe_dump"):
        assert mutation not in tab


def test_the_surface_resolves_contracts_through_the_canonical_loader():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    fn = src[src.index("def _contracts_for_review"):][:600]
    assert "load_contracts" in fn and "_framework_path" in fn
    assert "yaml" not in fn


def test_retrieval_adequacy_is_surfaced_with_its_caveat():
    tab = _tab()
    assert "CR.retrieval_adequacy" in tab
    assert "_adq['reason']" in tab, "the not-yet-measurable case must be shown, not hidden"
