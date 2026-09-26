from __future__ import annotations

from pathlib import Path
import hashlib
import json


ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_pack_preserves_all_four_frozen_case_narratives():
    from tools.synthetic_m36_demo import verify_frozen_origins
    rows = verify_frozen_origins(ROOT.parent / "synthetic_evidence_v6/MAS/M3.6")
    assert [row["case"] for row in rows] == ["d", "e", "f", "g"]


def test_synthetic_pack_is_explicitly_non_production():
    evidence_root = ROOT.parent / "synthetic_evidence_v6/MAS/M3.6"
    documents = sorted(evidence_root.glob("*.md"))
    assert documents, f"no evidence documents under {evidence_root}: the pack must sit next to ge_repo"
    for path in documents:
        text = path.read_text(encoding="utf-8")
        assert "Evidence Mode: SYNTHETIC_DEMO_ONLY" in text
        assert "Control ID: M3.6" in text


def test_synthetic_pack_has_out_of_band_revalidation_evidence():
    path = ROOT.parent / "synthetic_evidence_v6/MAS/M3.6/M3.6_Lifecycle_Revalidation_Standard.md"
    text = path.read_text(encoding="utf-8").lower()
    assert "revalidation triggers" in text
    assert "risk materiality" in text
    assert "scheduled interval" in text


def test_dossier_linking_uses_scout_significant_terms(tmp_path):
    from governance.evidence_scout.agent import _terms
    element = "The testing approach considers sub-population, fairness or other stakeholder-impact dimensions where relevant to the AI use case, system or model."
    significant = _terms(element)
    assert "the" not in significant
    assert "fairness" in significant


def test_synthetic_manifest_matches_pack_bytes():
    pack_root = ROOT.parent / "synthetic_evidence_v6"
    manifest = json.loads((pack_root / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["production_compliance_proof"] is False
    for row in manifest["files"]:
        assert hashlib.sha256((pack_root / row["path"]).read_bytes()).hexdigest() == row["sha256"]
