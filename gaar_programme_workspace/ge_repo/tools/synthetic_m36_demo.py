#!/usr/bin/env python3
"""Prepare a governed M3.6 dossier from the frozen synthetic experiment cases.

This command stops at the human admission checkpoint. It cannot claim MAS compliance,
impersonate an approver, create a human decision, or publish a CURRENT result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from governance.evidence_scout import EvidenceSource
from governance.evidence_scout.dossier import DossierStore, EvidenceAssemblyAgent, ImmutableBlobStore, render_markdown
from governance.evidence_scout.refresh import AcquisitionStore, RefreshAgent, RefreshPolicy


CASE_MAP = {
    "d": "M3.6_UC01_Retail_Credit_Validation.md",
    "e": "M3.6_UC02_Contact_Centre_GenAI.md",
    "f": "M3.6_UC03_AML_Alert_Prioritisation.md",
    "g": "M3.6_UC04_Customer_Eligibility.md",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_frozen_origins(evidence_root: Path) -> list[dict]:
    manifest = json.loads((ROOT / "eval/corpus/M3.6/AUTHORED_CASES.json").read_text(encoding="utf-8"))
    expected = {row["case"]: row for row in manifest["cases"]}
    out = []
    for case, target_name in CASE_MAP.items():
        source = (ROOT / "eval/corpus/M3.6" / expected[case]["file"]).read_bytes()
        target = (evidence_root / target_name).read_bytes()
        marker = target.find(b"# ")
        if marker < 0 or target[marker:] != source:
            raise RuntimeError(f"synthetic case {case} no longer preserves its frozen source narrative")
        if _sha(source) != expected[case]["sha256"]:
            raise RuntimeError(f"frozen corpus origin hash changed for case {case}")
        out.append({"case": case, "file": target_name, "origin_sha256": expected[case]["sha256"],
                    "pack_sha256": _sha(target)})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path,
                        default=WORKSPACE / "synthetic_evidence_v6/MAS/M3.6")
    parser.add_argument("--run-root", type=Path,
                        default=ROOT / "governance/synthetic_demo")
    args = parser.parse_args()

    evidence_root = args.evidence_root.expanduser().resolve(strict=True)
    run_root = args.run_root.expanduser().resolve()
    origins = verify_frozen_origins(evidence_root)
    contract = yaml.safe_load((ROOT / "eval/corpus/M3.6/elements.yaml").read_text(encoding="utf-8"))
    elements = tuple(str(row["text"]).strip() for row in contract["elements"])
    requirement = " ".join(elements)
    version = "SYNTHETIC-M3.6-DEMO-v1"
    acquisition_path = run_root / "evidence_acquisitions.jsonl"
    dossier_path = run_root / "evidence_dossiers.jsonl"
    blob_root = run_root / "evidence_blobs"

    receipt = RefreshAgent(
        [EvidenceSource("synthetic-m36-use-cases", evidence_root)],
        policy=RefreshPolicy(max_age_days=3650, min_sources=1),
        acquisition_store=AcquisitionStore(acquisition_path),
    ).run("M3.6", "MAS", requirement, elements, requirement_version_id=version)
    if receipt["recommended_action"] != "REVIEW_CANDIDATES":
        print(json.dumps({"status": "EVIDENCE_REQUIRED", "synthetic_only": True,
                          "acquisition_id": receipt["acquisition_id"], "gaps": receipt["gaps"]}, indent=2))
        return 2

    dossier = EvidenceAssemblyAgent(
        {"synthetic-m36-use-cases": evidence_root},
        blobs=ImmutableBlobStore(blob_root),
        dossiers=DossierStore(dossier_path),
    ).assemble(
        receipt,
        assertion=("Synthetic test assertion: the four experimental M3.6 cases and lifecycle policy "
                   "provide candidate evidence for evaluation and independent review controls."),
        required_elements=elements,
        template="synthetic_m36_experiment",
    )
    output = run_root / "M3.6_SYNTHETIC_DOSSIER.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(dossier), encoding="utf-8")
    result = {
        "status": "READY_FOR_HUMAN_REVIEW" if not dossier["gaps"] else "EVIDENCE_REQUIRED",
        "evidence_mode": "SYNTHETIC_DEMO_ONLY",
        "production_compliance_proof": False,
        "control_id": "M3.6",
        "framework": "MAS",
        "requirement_version_id": version,
        "governed_elements": len(elements),
        "frozen_use_cases": origins,
        "acquisition_id": receipt["acquisition_id"],
        "exact_control_candidates": receipt["retrieval_policy"]["match_counts"].get("EXACT_CONTROL", 0),
        "preflight": receipt["preflight"],
        "dossier_id": dossier["dossier_id"],
        "anchors": len(dossier["anchors"]),
        "gaps": dossier["gaps"],
        "dossier_path": str(output),
        "next_checkpoint": "NAMED_HUMAN_ADMISSION",
        "note": "Synthetic evidence can prove workflow behavior but cannot prove MAS compliance.",
    }
    summary = run_root / "latest_run.json"
    summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "READY_FOR_HUMAN_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())

