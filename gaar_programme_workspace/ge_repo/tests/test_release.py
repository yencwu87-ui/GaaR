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
