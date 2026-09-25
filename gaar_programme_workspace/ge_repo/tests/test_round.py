"""gaar round (kit v28): one command per round, with a doctor that names every setup problem and its fix."""
import importlib
import json
import zipfile
from pathlib import Path

import pytest

from governance import doctor
from tests.test_guards_exercised import series  # noqa: F401  (fixture)

round_tool = importlib.import_module("tools.gaar_round")


def test_the_doctor_names_each_problem_with_its_fix(tmp_path, monkeypatch):
    root = tmp_path / "install" / "ge_repo"
    root.mkdir(parents=True)
    assert doctor.evidence_pack(root)["state"] == "FAIL"
    assert "synthetic_evidence_v6" in doctor.evidence_pack(root)["fix"]
    (root.parent / "synthetic_evidence_v6").mkdir()
    assert doctor.evidence_pack(root)["state"] == "OK"
    assert doctor.series(tmp_path / "missing.json")["state"] == "FAIL"
    assert doctor.kit(root)["state"] == "WARN"
    (root / "KIT_MANIFEST.json").write_text(json.dumps({"kit": "v28", "built_at": "2026-09-25T00:00:00"}))
    assert doctor.kit(root)["detail"].startswith("v28")

    def down(*a, **k):
        raise ConnectionError("refused")
    assert doctor.ollama(get=down) == {"check": "ollama", "state": "WARN",
                                       "detail": "not running: local model contestants are unavailable",
                                       "fix": "open -a Ollama"}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert doctor.anthropic_key()["state"] == "WARN"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    row = doctor.anthropic_key()
    assert row == {"check": "anthropic key", "state": "OK", "detail": "set (value not shown)", "fix": ""}


def test_the_wrong_environment_stops_the_round_before_any_test(monkeypatch, tmp_path):
    import run_all_tests
    monkeypatch.setattr(run_all_tests, "requirement_problems", lambda path=None: (["streamlit==1.63.0"], []))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "gaar")
    row = doctor.python_environment()
    assert row["state"] == "FAIL" and "missing in gaar" in row["detail"] and row["fix"].startswith("conda activate gaar")
    report = doctor.run(tmp_path / "missing.json", get=lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert report["verdict"] == "NOT READY"
    assert "fix: conda activate gaar" in doctor.render(report)


def test_a_mail_password_variable_that_is_not_loaded_is_a_warning_never_a_value(monkeypatch):
    import yaml
    from governance.watcher import intel
    intel.subscriptions()
    path = intel.home_path() / "subscriptions.yaml"
    subs = yaml.safe_load(path.read_text())
    subs["mail"] = {"imap_host": "imap.example.com", "imap_user": "a@example.com", "password_env": "GAAR_MAIL_PASSWORD"}
    path.write_text(yaml.safe_dump(subs))
    monkeypatch.delenv("GAAR_MAIL_PASSWORD", raising=False)
    rows = {r["check"]: r for r in doctor.watch()}
    assert rows["mail password"]["state"] == "WARN" and rows["mail password"]["fix"].startswith("source ~/.zshrc")
    monkeypatch.setenv("GAAR_MAIL_PASSWORD", "hunter2")
    rows = {r["check"]: r for r in doctor.watch()}
    assert rows["mail password"]["state"] == "OK" and "hunter2" not in json.dumps(rows)


def _install(tmp_path):
    root = tmp_path / "install" / "ge_repo"
    (root / "governance").mkdir(parents=True)
    (root / "governance" / "events.jsonl").write_text('{"event": 1}\n')
    return root


def _kit(tmp_path, entries):
    kit = tmp_path / "kit.zip"
    with zipfile.ZipFile(kit, "w") as z:
        for name, body in entries.items():
            z.writestr(name, body)
    return kit


def test_install_snapshots_the_ledgers_and_proves_they_are_untouched(tmp_path):
    root = _install(tmp_path)
    kit = _kit(tmp_path, {"ge_repo/KIT_MANIFEST.json": json.dumps({"kit": "v28"}), "ge_repo/tools/new.py": "x = 1\n"})
    done = round_tool.install(kit, root=root, snapshots=tmp_path / "snaps", stamp="t1")
    assert done["kit"] == "v28" and done["ledgers_checked"] == 1
    assert (root / "tools" / "new.py").read_text() == "x = 1\n"
    assert (tmp_path / "snaps/t1/governance/events.jsonl").read_text() == '{"event": 1}\n'


@pytest.mark.parametrize("entries, message", [
    ({"ge_repo/governance/events.jsonl": "{}\n"}, "the kit carries runtime state (governance/events.jsonl)"),
    ({"other/readme.txt": "x"}, "this zip is not a GaaR kit: every entry must sit under ge_repo/"),
])
def test_install_refuses_a_kit_that_could_overwrite_records(tmp_path, entries, message):
    root = _install(tmp_path)
    with pytest.raises(ValueError, match="^" + __import__("re").escape(message)):
        round_tool.install(_kit(tmp_path, entries), root=root, snapshots=tmp_path / "snaps", stamp="t1")
    assert (root / "governance" / "events.jsonl").read_text() == '{"event": 1}\n'
    with pytest.raises(ValueError, match="^no kit at "):
        round_tool.install(tmp_path / "missing.zip", root=root, snapshots=tmp_path / "snaps", stamp="t2")


def test_a_ledger_that_changes_during_install_is_reported_with_its_snapshot(tmp_path, monkeypatch):
    root = _install(tmp_path)
    real = zipfile.ZipFile.extractall

    def tamper(self, path=None, *a, **k):
        real(self, path, *a, **k)
        (root / "governance" / "events.jsonl").write_text("overwritten\n")
    monkeypatch.setattr(zipfile.ZipFile, "extractall", tamper)
    kit = _kit(tmp_path, {"ge_repo/KIT_MANIFEST.json": "{}"})
    with pytest.raises(ValueError, match=r"^1 ledger\(s\) changed during the install \(governance/events.jsonl\); "
                                         r"restore them from .*snaps/t3$"):
        round_tool.install(kit, root=root, snapshots=tmp_path / "snaps", stamp="t3")


def test_the_summary_is_one_readable_page(tmp_path):
    folder = tmp_path / "round-20260925T100000"
    folder.mkdir()
    (folder / "milestone.txt").write_text("...\nRESULT: ALL GATES AS EXPECTED\n")
    report = {"verdict": "READY WITH WARNINGS",
              "checks": [{"check": "ollama", "state": "WARN", "detail": "not running", "fix": "open -a Ollama"}]}
    watch = [{"source_id": "cisa-kev", "state": "OK"}, {"source_id": "mas-email-alerts", "state": "FAILING",
                                                         "error": "no alert emails from mas.gov.sg yet"}]
    text = round_tool.summarise(folder, report, 0, watch, {"kit": "v28", "ledgers_checked": 16, "snapshot": "/s"})
    assert "install: v28 installed; 16 ledger(s) unchanged" in text and "DOCTOR: READY WITH WARNINGS" in text
    assert "fix: open -a Ollama" in text and "milestone: RESULT: ALL GATES AS EXPECTED" in text
    assert "watch: 1 of 2 source(s) OK" in text and "mas-email-alerts" in text
    waiting = round_tool.summarise(folder, report, 3, None, None).replace("RESULT", "")
    assert "milestone:" in waiting
    (folder / "milestone.txt").write_text("stopped\n")
    assert "WAITING ON YOU: sign in the inbox" in round_tool.summarise(folder, report, 3, None, None)
    assert "not run (the machine is not ready" in round_tool.summarise(folder, report, None, None, None)


def test_an_old_python_stops_the_round_with_its_fix():
    row = doctor.python_environment(version=(3, 11))
    assert row["state"] == "FAIL" and "needs 3.12" in row["detail"] and row["fix"].startswith("conda activate gaar")


def test_a_machine_that_is_not_ready_still_packs_one_file_and_exits_2(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(doctor, "run", lambda config: {"verdict": "NOT READY", "checks": [
        {"check": "series", "state": "FAIL", "detail": "no series", "fix": "authorise one"}]})
    folder = tmp_path / "round-20260925T090000"
    monkeypatch.setattr("sys.argv", ["gaar_round.py", "--config", str(tmp_path / "none.json"), "--resume", str(folder)])
    with pytest.raises(SystemExit) as stop:
        round_tool.main()
    assert stop.value.code == 2
    assert "milestone: not run" in (folder / "summary.txt").read_text()
    with zipfile.ZipFile(tmp_path / "Desktop" / "gaar-round-20260925T090000.zip") as z:
        assert {"doctor.json", "summary.txt"} <= set(z.namelist())


def test_a_refused_kit_is_reported_as_blocked_and_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gaar_round.py", "--kit", str(tmp_path / "absent.zip"),
                                     "--resume", str(tmp_path / "round-x")])
    with pytest.raises(SystemExit) as stop:
        round_tool.cli()
    assert stop.value.code == 2
    blocked = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert blocked == {"status": "BLOCKED", "reason": f"no kit at {tmp_path / 'absent.zip'}"}


def test_the_base_environment_is_refused_even_when_its_packages_look_right(monkeypatch):
    # v28 round: `source ~/.zshrc` after `conda activate gaar` ran the round in base, on Python 3.14.
    import run_all_tests
    monkeypatch.setattr(run_all_tests, "requirement_problems", lambda path=None: ([], []))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    row = doctor.python_environment(version=(3, 14))
    assert row["state"] == "FAIL" and "'base', not 'gaar'" in row["detail"] and "3.14" in row["detail"]
    assert row["fix"] == "conda activate gaar   (after any source ~/.zshrc)"
    monkeypatch.setenv("GAAR_CONDA_ENV", "base")
    assert doctor.python_environment(version=(3, 12))["state"] == "OK"


def test_a_stopped_milestone_puts_its_last_lines_in_the_summary(tmp_path):
    folder = tmp_path / "round-x"
    folder.mkdir()
    (folder / "milestone.txt").write_text("step 1 ok\n\nSTOP: 3 test(s) failed in tests/test_twin.py\n")
    text = round_tool.summarise(folder, {"verdict": "READY", "checks": []}, 1, None, None)
    assert "milestone: STOPPED. The last lines of milestone.txt:\n  step 1 ok\n  STOP: 3 test(s) failed" in text


def test_a_mistyped_kit_name_points_to_the_newest_kit_in_that_folder(tmp_path):
    (tmp_path / "GaaR_RaaS_Kit_v28.zip").write_bytes(b"")
    with pytest.raises(ValueError, match=r"^no kit at .*v29\.zip; the newest kit in that folder is GaaR_RaaS_Kit_v28\.zip$"):
        round_tool.install(tmp_path / "GaaR_RaaS_Kit_v29.zip")


def test_the_doctor_and_the_runner_call_one_readiness_check(monkeypatch):
    # D28, the class: two readiness lists can drift; one function cannot disagree with itself.
    import run_all_tests
    monkeypatch.setattr(run_all_tests, "readiness", lambda: (["coverage>=7"], []))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "gaar")
    row = doctor.python_environment(version=(3, 12))
    assert row["state"] == "FAIL" and "coverage>=7" in row["detail"]
    source = Path(run_all_tests.__file__).read_text()
    assert source.count("readiness()") == 2 and "requirement_problems(dev)" in source   # defined once, used once
    assert "requirement_problems" not in Path(doctor.__file__).read_text()


def test_the_doctor_checks_the_same_requirements_file_as_the_test_runner(monkeypatch):
    # D28 (v28 round): the doctor read requirements.txt and said "requirements met" in base; the runner read
    # requirements-dev.txt (pytest, coverage) and stopped with ENVIRONMENT NOT READY.
    import run_all_tests
    seen = []
    monkeypatch.setattr(run_all_tests, "requirement_problems",
                        lambda path=None: seen.append(path) or (["pytest==9.0.2"], []))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "gaar")
    row = doctor.python_environment(version=(3, 12))
    assert seen and seen[0].name == "requirements-dev.txt"
    assert row["state"] == "FAIL" and "pytest==9.0.2" in row["detail"]


def test_the_doctor_says_which_python_the_unattended_scheduler_runs(tmp_path):
    import plistlib
    assert doctor.launchd(tmp_path) == []                              # not installed: nothing to check
    python = tmp_path / "gaar" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    plist = tmp_path / "com.gaar.scheduler.plist"
    plist.write_bytes(plistlib.dumps({"ProgramArguments": [str(python), "tools/gaar_scheduler.py", "tick"]}))
    assert doctor.launchd(tmp_path, executable=python)[0]["state"] == "OK"
    other = doctor.launchd(tmp_path, executable=tmp_path / "base-python")[0]
    assert other["state"] == "WARN" and f"launchd runs {python}" in other["detail"]
    python.unlink()
    gone = doctor.launchd(tmp_path, executable=python)[0]
    assert gone["state"] == "FAIL" and "no longer exists" in gone["detail"]
    plist.write_bytes(b"not a plist")
    assert doctor.launchd(tmp_path)[0]["state"] == "WARN"


def test_the_doctor_puts_scheduler_health_first(series, monkeypatch):
    from governance.production import scheduler
    home, config_path = series
    assert doctor.scheduler_health(home / "absent.json") == []
    assert doctor.scheduler_health(config_path)[0]["detail"] == "has never run for this workspace"

    def boom(ctx):
        raise RuntimeError("down")
    scheduler.tick(config_path, jobs=[("gate_status", boom)])
    row = doctor.scheduler_health(config_path)[0]
    assert row["state"] == "WARN" and "gate_status: FAILING since" in row["detail"]
    scheduler.tick(config_path, jobs=[("gate_status", lambda ctx: {"status": "OK"})])
    row = doctor.scheduler_health(config_path)[0]
    assert row["state"] == "OK" and "was failing from" in row["detail"]
    report = doctor.run(config_path, get=lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert report["checks"][0]["check"] == "scheduler"


def test_the_round_compares_this_machine_with_the_counts_the_kit_states(tmp_path):
    from tools.run_all_tests import run_record
    from tools.trace_unreached_guards import trace_record
    runs = tmp_path / ".test_runs"
    runs.mkdir()
    expected = {"tests_collected": 10, "trace_modules": len(trace_record(0, "", 0, [], None)["modules"]),
                "trace_unreached": 0}
    assert round_tool.compare(None, tmp_path) == []
    assert round_tool.compare(expected, tmp_path) == ["tests_collected: expected 10, this machine None",
                                                      f"trace_modules: expected {expected['trace_modules']}, this machine None",
                                                      "trace_unreached: expected 0, this machine None"]
    (runs / "2026-09-25T1.json").write_text(json.dumps(run_record("COMPLETE RUN, ALL PASSED", collected=10)))
    (runs / "trace-2026-09-25T1.json").write_text(json.dumps(trace_record(0, "", 0, [], None)))
    assert round_tool.compare(expected, tmp_path) == []
    (runs / "2026-09-25T2.json").write_text(json.dumps(run_record("COMPLETE RUN, ALL PASSED", collected=9)))
    assert round_tool.compare(expected, tmp_path) == ["tests_collected: expected 10, this machine 9"]
    folder = tmp_path / "round-x"
    folder.mkdir()
    (folder / "milestone.txt").write_text("RESULT: ALL GATES AS EXPECTED\n")
    text = round_tool.summarise(folder, {"verdict": "READY", "checks": []}, 0, None, None,
                                ["tests_collected: expected 10, this machine 9"],
                                [{"id": "A-001", "state": "HUMAN_ADJUDICATED", "confirmed_by": ["Wu Yen Ching"]},
                                 {"id": "A-002", "state": "AWAITING_A_NAMED_PERSON", "confirmed_by": []}])
    assert "expected counts: DIFFER: tests_collected: expected 10, this machine 9" in text
    assert "twin adjudications: A-001 HUMAN_ADJUDICATED by Wu Yen Ching, A-002 AWAITING_A_NAMED_PERSON" in text


def test_install_prints_one_digest_of_every_ledger_before_and_after(tmp_path):
    root = tmp_path / "ws" / "ge_repo"
    (root / "governance").mkdir(parents=True)
    (root / "governance" / "events.jsonl").write_text('{"x":1}\n')
    kit = tmp_path / "kit.zip"
    with zipfile.ZipFile(kit, "w") as z:
        z.writestr("ge_repo/README.md", "x")
        z.writestr("ge_repo/KIT_MANIFEST.json", json.dumps({"kit": "v31", "expected": {"tests_collected": 5}}))
    result = round_tool.install(kit, root=root, snapshots=tmp_path / "snap", stamp="t")
    assert result["ledgers_before"] == result["ledgers_after"] == round_tool.digest(round_tool.ledgers(root))
    assert result["expected"] == {"tests_collected": 5}


def test_an_install_done_by_the_previous_kits_installer_says_why_it_has_no_digest(tmp_path):
    folder = tmp_path / "round-x"
    folder.mkdir()
    old = {"kit": "v31", "ledgers_checked": 14, "snapshot": "/s/t"}                  # written by the v30 installer
    text = round_tool.summarise(folder, {"verdict": "READY", "checks": []}, None, None, old)
    assert "install: v31 installed; 14 ledger(s) unchanged (no prior baseline); snapshot /s/t" in text
    new = {**old, "ledgers_before": "a" * 64, "ledgers_after": "a" * 64}
    assert "(digest before aaaaaaaaaaaaaaaa, after aaaaaaaaaaaaaaaa)" in \
        round_tool.summarise(folder, {"verdict": "READY", "checks": []}, None, None, new)


def test_an_older_installers_install_is_digested_here_from_its_snapshot(tmp_path):
    root = tmp_path / "ge_repo"
    (root / "governance").mkdir(parents=True)
    (root / "governance" / "events.jsonl").write_text('{"x":1}\n')
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "ledgers.sha256.json").write_text(json.dumps(round_tool.ledgers(root)))
    old = {"kit": "v31", "ledgers_checked": 1, "snapshot": str(snap)}
    done = round_tool.self_contained(old, root)
    assert done["ledgers_before"] == done["ledgers_after"] and done["ledgers_changed"] == []
    assert done["digest_source"].startswith("computed by this kit from the snapshot")
    (root / "governance" / "events.jsonl").write_text('{"x":2}\n')
    assert round_tool.self_contained(old, root)["ledgers_changed"] == ["governance/events.jsonl"]
    text = round_tool.summarise(tmp_path, {"verdict": "READY", "checks": []}, None, None,
                                round_tool.self_contained(old, root))
    assert "1 ledger(s) CHANGED: governance/events.jsonl" in text
    assert round_tool.self_contained({**old, "snapshot": str(tmp_path / "none")}, root)["digest_source"] == \
        "no prior baseline: the installer that ran wrote no ledger hashes"
    assert round_tool.self_contained({**old, "ledgers_before": "a"}, root) == {**old, "ledgers_before": "a"}


def test_the_round_prints_each_skip_with_its_reason(tmp_path):
    from tools.run_all_tests import run_record
    (tmp_path / ".test_runs").mkdir()
    (tmp_path / ".test_runs" / "2026-09-25T1.json").write_text(json.dumps(run_record(
        "COMPLETE RUN, ALL PASSED", skipped_with_reasons=["SKIPPED [1] tests/test_folder_picker_wb038.py:50: root "
                                                          "ignores directory permissions"])))
    skips = round_tool.skipped(tmp_path)
    assert round_tool.skipped(tmp_path / "none") == []
    text = round_tool.summarise(tmp_path, {"verdict": "READY", "checks": []}, 0, None, None, [], None, skips)
    assert "  skipped: [1] tests/test_folder_picker_wb038.py:50: root ignores directory permissions" in text


def _install_with_manifest(root, files):
    import hashlib
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    manifest = {"kit": "v32", "file_sha256": {r: hashlib.sha256(t.encode()).hexdigest() for r, t in files.items()}}
    (root / "KIT_MANIFEST.json").write_text(json.dumps(manifest))


def test_the_doctor_refuses_an_install_holding_code_no_kit_shipped(tmp_path):
    # D30 (v31 round): a module and 17 tests that no kit shipped sat in the Mac's install and changed its test count.
    root = tmp_path / "ge_repo"
    root.mkdir()
    assert doctor.install_integrity(root)["state"] == "WARN"                  # a kit with no file list
    _install_with_manifest(root, {"governance/doctor.py": "x", "tests/test_a.py": "t"})
    (root / "governance" / "events.jsonl").write_text("runtime state, never compared\n")
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "site.py").write_text("an environment, never compared")
    assert doctor.install_integrity(root) == {"check": "install integrity", "state": "OK",
                                              "detail": "exactly the 2 files the kit shipped", "fix": ""}
    (root / "governance" / "raas").mkdir()
    (root / "governance" / "raas" / "warranty.py").write_text("unreviewed")
    (root / "tests" / "test_raas.py").write_text("unreviewed")
    (root / "tests" / "test_a.py").write_text("edited")
    row = doctor.install_integrity(root)
    assert row["state"] == "FAIL" and row["fix"].startswith("python tools/gaar_round.py --quarantine")
    assert row["detail"] == ("2 file(s) no kit shipped: governance/raas/warranty.py, tests/test_raas.py; "
                             "1 shipped file(s) changed: tests/test_a.py")


def test_quarantine_moves_unshipped_code_out_and_keeps_a_copy_of_changed_files(tmp_path):
    root = tmp_path / "ge_repo"
    root.mkdir()
    with pytest.raises(ValueError, match=r"^the installed kit carries no file list"):
        round_tool.quarantine(root, tmp_path / "q", "t")
    _install_with_manifest(root, {"governance/doctor.py": "x", "tests/test_a.py": "t"})
    assert round_tool.quarantine(root, tmp_path / "q", "t0")["status"] == "NOTHING_TO_QUARANTINE"
    (root / "tests" / "test_raas.py").write_text("unreviewed")
    (root / "tests" / "test_a.py").write_text("edited")
    done = round_tool.quarantine(root, tmp_path / "q", "t1")
    assert done["moved"] == ["tests/test_raas.py"] and done["copied_changed"] == ["tests/test_a.py"]
    assert not (root / "tests" / "test_raas.py").exists()
    assert (tmp_path / "q" / "t1" / "tests" / "test_raas.py").read_text() == "unreviewed"
    assert (tmp_path / "q" / "t1" / "changed" / "tests" / "test_a.py").read_text() == "edited"
    assert (root / "tests" / "test_a.py").read_text() == "edited"             # copied, not taken away
    assert done["next"].startswith("reinstall the kit with --kit")
