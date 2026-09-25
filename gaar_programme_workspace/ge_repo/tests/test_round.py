"""gaar round (kit v28): one command per round, with a doctor that names every setup problem and its fix."""
import importlib
import json
import zipfile

import pytest

from governance import doctor

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
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    row = doctor.python_environment()
    assert row["state"] == "FAIL" and "base" in row["detail"] and row["fix"].startswith("conda activate gaar")
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
