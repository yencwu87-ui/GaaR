"""Integration boundary — one semantic authority, consumed by every stage.

The semantic layer proved Source → Canonical Control → Elements → Derived Views. This proves the
next chain: that the assessor, the challenge validator and the comparison all resolve the element
set from the canonical contract rather than rebuilding it from a control description, a legacy
field or a verification procedure.

The invariant that matters: ids agreeing while texts differ is worse than disagreement, because
it looks like agreement.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.integration_audit import audit, static_checks, trace

FW = {"MAS": "Control Library - MAS", "MGF Agentic": "Control Library - MGF Agentic",
      "SAFR": "Control Library - SAFR", "NIST AI RMF": "Control Library - NIST AI RMF",
      "ISO 42001": "Control Library - ISO 42001"}

#: Deliberately hostile: every framework, the re-authored controls, the ones whose element count
#: changed during the SAFR repair, and the one carrying an out-of-band element.
HOSTILE = [("M1.1", FW["MAS"]), ("M3.6", FW["MAS"]), ("M3.12", FW["MAS"]),
           ("D1.1", FW["MGF Agentic"]), ("D1.2", FW["MGF Agentic"]),
           ("S1.1", FW["SAFR"]), ("S1.2", FW["SAFR"]), ("S3.1", FW["SAFR"]),
           ("GOVERN 1.1", FW["NIST AI RMF"]), ("A.2.2", FW["ISO 42001"])]


def _lib():
    return yaml.safe_load((ROOT / "governance/knowledge/control_contracts.yaml")
                          .read_text(encoding="utf-8"))["controls"]


def test_the_hostile_corpus_exposes_no_alternate_semantic_authority():
    a = audit(HOSTILE)
    assert a["clean"], a["findings"]


def test_every_stage_sees_the_same_element_ids():
    """human_element_id == assessor_element_id == challenge_element_id."""
    for cid, fw in HOSTILE:
        t = trace(cid, fw)
        assert t["ids_agree"], f"{cid}: {t['stages']}"


def test_every_stage_sees_the_same_element_text():
    """Resolved from one source, not three copies that happen to match today."""
    for cid, fw in HOSTILE:
        t = trace(cid, fw)
        assert not [f for f in t["findings"] if f["mode"] == "F06"], t["findings"]


def test_the_static_failure_modes_are_absent():
    """Properties of the code rather than of any one control — prompt labelling, id-keyed
    comparison, reviewer-centred decision, no UI-held semantic copy, no reverse sync."""
    assert static_checks() == []


def test_it_holds_across_all_195_controls():
    """The hostile corpus is the argument; this is the sweep that makes it a claim."""
    bad = []
    for c in _lib():
        t = trace(c["control_id"], FW[c["framework"]])
        if t["findings"]:
            bad.append((c["control_id"], [f["mode"] for f in t["findings"]]))
    assert not bad, bad[:10]


def test_the_audit_does_not_reconstruct_the_element_set_itself():
    """A tracer that rebuilds the elements is the twelfth failure mode it looks for."""
    import ast
    src = (ROOT / "governance" / "integration_audit.py").read_text(encoding="utf-8")
    assert "get_control_contract" in src, "the audit must resolve via the pipeline's own loader"

    # Mentioning a filename is fine — the F09 detector looks for those strings inside app.py.
    # Parsing one is not. Check for the act, not the word.
    tree = ast.parse(src)
    loaders = {"safe_load", "load", "read_yaml"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in loaders, \
                f"the audit parses a contract file itself: {node.func.attr}"
    assert "import yaml" not in src, "the audit must not load YAML at all"


def test_the_baseline_checkpoint_is_recorded():
    """So a later tree change is attributable to the concurrent writer, not to this audit."""
    import json
    cp = json.loads((ROOT / "governance" / "SEMANTIC_BASELINE.json").read_text(encoding="utf-8"))
    b = cp["semantic_baseline"]
    assert b["controls"] == 195 and b["elements"] == 538
    assert b["decomposition_errors"] == 0 and b["canonical_drift"] == 0
    assert cp["frozen_for_this_pass"]["exception"].startswith("a demonstrated integration defect")
