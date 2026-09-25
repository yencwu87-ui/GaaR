"""The release rule (kit v32): the zip that ships is the zip that was rehearsed; the practice series matches the Mac's."""
import hashlib
import importlib
import json

import pytest

release = importlib.import_module("tools.release_check")
CLEAN = ("install: v32 installed; 14 ledger(s) unchanged (digest before a, after a)\n"
         "milestone: RESULT: ALL GATES AS EXPECTED\nexpected counts: met\n")


def _rehearsal(tmp_path, zip_bytes=b"kit", summary=CLEAN):
    kit = tmp_path / "kit.zip"
    kit.write_bytes(zip_bytes)
    folder = tmp_path / "round-x"
    folder.mkdir(exist_ok=True)
    (folder / "install.json").write_text(json.dumps({"kit_sha256": hashlib.sha256(b"kit").hexdigest()}))
    (folder / "summary.txt").write_text(summary)
    return kit, folder


def test_the_rehearsed_zip_is_releasable(tmp_path):
    assert release.check(*_rehearsal(tmp_path)) == {"releasable": True, "kit_sha256": hashlib.sha256(b"kit").hexdigest(),
                                                   "problems": []}


def test_a_zip_rebuilt_after_the_rehearsal_is_not(tmp_path):
    result = release.check(*_rehearsal(tmp_path, zip_bytes=b"kit, rebuilt with one small fix"))
    assert not result["releasable"]
    assert result["problems"][0].endswith("is not the one the rehearsal installed "
                                          f"({hashlib.sha256(b'kit').hexdigest()[:16]}): rebuild means rehearse again")


@pytest.mark.parametrize("summary, problem", [
    (CLEAN.replace("unchanged", "CHANGED: governance/events.jsonl"), "a ledger changed during the rehearsal's install"),
    (CLEAN.replace("expected counts: met", "expected counts: DIFFER: tests_collected: expected 10, this machine 9"),
     "the kit's expected counts were not met on the rehearsal machine"),
    (CLEAN.replace("ALL GATES AS EXPECTED", "DIFFERS: Independent mapping review"),
     "the rehearsal summary reports a difference: milestone: RESULT: DIFFERS: Independent mapping review"),
    (CLEAN.replace("milestone: RESULT: ALL GATES AS EXPECTED", "milestone: STOPPED: see milestone.txt"),
     "the rehearsal's milestone did not end ALL GATES AS EXPECTED or WAITING ON YOU"),
])
def test_an_unclean_rehearsal_is_not_releasable(tmp_path, summary, problem):
    result = release.check(*_rehearsal(tmp_path, summary=summary))
    assert not result["releasable"] and problem in result["problems"]


def test_a_missing_kit_or_rehearsal_is_not_releasable(tmp_path):
    assert release.check(tmp_path / "none.zip", tmp_path) == {
        "releasable": False, "problems": [f"{tmp_path} is not a rehearsal round with an install"]}
    kit, folder = _rehearsal(tmp_path)
    assert release.check(tmp_path / "none.zip", folder)["problems"][0] == f"no kit at {tmp_path / 'none.zip'}"


def test_the_install_records_the_sha256_of_the_zip_itself(tmp_path):
    import zipfile
    round_tool = importlib.import_module("tools.gaar_round")
    root = tmp_path / "ws" / "ge_repo"
    root.mkdir(parents=True)
    kit = tmp_path / "kit.zip"
    with zipfile.ZipFile(kit, "w") as z:
        z.writestr("ge_repo/README.md", "x")
    result = round_tool.install(kit, root=root, snapshots=tmp_path / "snap", stamp="t")
    assert result["kit_sha256"] == hashlib.sha256(kit.read_bytes()).hexdigest()


def test_the_practice_series_carries_a_signed_mapping_and_an_independent_review(tmp_path):
    from governance.production import gate_status
    rehearsal = importlib.import_module("tools.rehearsal_series")
    home = tmp_path / "home"
    home.mkdir()
    built = rehearsal.build(tmp_path / "demo", home=home)
    assert built["status"] == "REHEARSAL_SERIES_BUILT" and built["mapping_review"].endswith(".json")
    report = gate_status.generate(built["config"])
    gate = next(g for g in report["gates"] if g["gate"] == "Independent mapping review")
    assert gate["state"] == "HELD", gate["evidence"]
    with pytest.raises(ValueError, match=r"already holds a series; a rehearsal series is built fresh"):
        rehearsal.build(tmp_path / "demo", home=home)


def _zip_with_manifest(path, files, manifest_files=None):
    import zipfile
    listed = manifest_files if manifest_files is not None else {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
    manifest = json.dumps({"kit": "v32", "file_sha256": listed}).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            z.writestr("ge_repo/" + name, body)
        z.writestr("ge_repo/KIT_MANIFEST.json", manifest)
    return hashlib.sha256(manifest).hexdigest()


def _old_installer_rehearsal(tmp_path, integrity="OK"):
    # v32 upgrading an install from v31: v31's installer ran and recorded no zip hash (the first v32 rehearsal).
    tmp_path.mkdir(parents=True, exist_ok=True)
    kit = tmp_path / "kit.zip"
    manifest = _zip_with_manifest(kit, {"README.md": b"x", "tools/a.py": b"a"})
    folder = tmp_path / "round-x"
    folder.mkdir()
    (folder / "install.json").write_text(json.dumps({"kit": "v32", "manifest_sha256": manifest}))
    (folder / "doctor.json").write_text(json.dumps({"checks": [{"check": "install integrity", "state": integrity}]}))
    (folder / "summary.txt").write_text(CLEAN)
    return kit, folder


def test_an_install_by_an_older_installer_is_matched_by_its_manifest(tmp_path):
    kit, folder = _old_installer_rehearsal(tmp_path)
    assert release.check(kit, folder)["releasable"]


def test_by_manifest_a_rebuilt_or_inconsistent_zip_or_an_unverified_install_is_not_releasable(tmp_path):
    kit, folder = _old_installer_rehearsal(tmp_path)
    _zip_with_manifest(kit, {"README.md": b"x", "tools/a.py": b"a, with one small fix"})
    assert "is not the one the rehearsal installed" in release.check(kit, folder)["problems"][0]
    install = json.loads((folder / "install.json").read_text())
    stale = {"README.md": hashlib.sha256(b"x").hexdigest(), "tools/a.py": hashlib.sha256(b"a").hexdigest()}
    install["manifest_sha256"] = _zip_with_manifest(kit, {"README.md": b"x", "tools/a.py": b"b"}, stale)
    (folder / "install.json").write_text(json.dumps(install))
    assert release.check(kit, folder)["problems"] == ["this zip's files do not match its own manifest (tools/a.py)"]
    kit, folder = _old_installer_rehearsal(tmp_path / "second", integrity="FAIL")
    assert release.check(kit, folder)["problems"] == [
        "the rehearsal's doctor did not find the install to be exactly the kit's files"]


def test_a_resumed_round_records_the_manifest_an_older_installer_left(tmp_path):
    round_tool = importlib.import_module("tools.gaar_round")
    root = tmp_path / "ge_repo"
    root.mkdir()
    (root / "KIT_MANIFEST.json").write_text('{"kit": "v32"}')
    done = round_tool.self_contained({"kit": "v32", "ledgers_before": "a"}, root)
    assert done["manifest_sha256"] == hashlib.sha256(b'{"kit": "v32"}').hexdigest()
    assert done["kit_sha256_source"] == "not recorded: the installer that ran predates v32"
    assert round_tool.self_contained({"kit_sha256": "z", "ledgers_before": "a"}, root) == {
        "kit_sha256": "z", "ledgers_before": "a"}
