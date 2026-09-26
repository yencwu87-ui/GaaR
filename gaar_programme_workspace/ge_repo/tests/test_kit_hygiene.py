"""D19: a kit must never carry the installing machine's runtime state (ledgers, watch history, approvals, records)."""
import importlib
import zipfile


def test_the_kit_leaves_out_every_runtime_store(tmp_path):
    build = importlib.import_module("tools.build_kit")
    result = build.build(tmp_path / "kit.zip", "test")
    names = zipfile.ZipFile(result["kit"]).namelist()
    assert "ge_repo/app.py" in names and "ge_repo/tools/gaar_milestone.py" in names and "ge_repo/KIT_MANIFEST.json" in names
    shipped_state = [n for n in names if n.startswith("ge_repo/governance/") and n.count("/") == 2 and n.endswith(".jsonl")]
    assert shipped_state == []                                  # events.jsonl, watcher_*.jsonl, ... never shipped
    for prefix in ("ge_repo/docs/quality/approvals/", "ge_repo/.test_runs/", "ge_repo/reports/", "ge_repo/packs/",
                   "ge_repo/governance/watcher_blobs/", "ge_repo/governance/evidence_blobs/"):
        assert not [n for n in names if n.startswith(prefix)], prefix
    assert "ge_repo/data/assessments.json" not in names and not [n for n in names if "__pycache__" in n]
