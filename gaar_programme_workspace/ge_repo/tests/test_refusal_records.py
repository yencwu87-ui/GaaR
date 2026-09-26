"""Refusal-record matrix (kit v31, after D27).

The guard trace proves every refusal line is reached. It never proved that the record a refusal leaves behind can be
read by everything downstream. D27 was exactly that gap: the test runner's ENVIRONMENT NOT READY record had no pass
counts, the gate report read them, and the scheduler's gate-status job failed on every tick.

Here every record shape the test runner and the tracer can write is built by the writer's own builder, and each
reader must take it and render a sensible state: the gate report, the scheduler's gate-status job, the milestone's
record reader, and the round summary. The shape the v28 round left on the Mac, from before the builder, stays in the
matrix so an old record can never crash a new reader.

Refusals whose records have other readers are tested beside those readers: arena early stops and SCORER_SUSPECT in
tests/test_arena.py, INSTRUMENT_UNAVAILABLE and bulk refusal in tests/test_basis.py, placeholder signers in
tests/test_twin.py and tests/test_basis.py, install refusals (BLOCKED) in tests/test_round.py.
"""
import importlib
import json

import pytest

from tests.test_gate_status import isolated  # noqa: F401  (fixture)
from tests.test_guards_exercised import _load, series  # noqa: F401  (fixture)

runner = importlib.import_module("tools.run_all_tests")
tracer = importlib.import_module("tools.trace_unreached_guards")
milestone = importlib.import_module("tools.gaar_milestone")
round_tool = importlib.import_module("tools.gaar_round")

LEGACY_ENVIRONMENT_STOP = {"at": None, "python": "/opt/anaconda3/bin/python", "python_version": "3.14.6",
                           "conda_env": "base", "environment_missing": ["pytest==9.0.2"],
                           "environment_mismatched": [], "verdict": "ENVIRONMENT NOT READY", "collected": 0,
                           "executed": 0}

RUNS = {  # name -> (record fields, expected state of "A valid test run", text the evidence must carry)
    "environment stop": (dict(verdict="ENVIRONMENT NOT READY", environment_missing=["pytest==9.0.2"]),
                         "OPEN", "stopped before any test: environment not ready (1 package(s) missing"),
    "environment stop, v28 shape": (None, "OPEN", "stopped before any test: environment not ready"),
    "files failed to load": (dict(verdict="INCOMPLETE RUN", collected=10, executed=8, passed=8,
                                  files_failed_to_load=["tests/test_x.py"]), "OPEN", "INCOMPLETE RUN: 10 collected"),
    "failing tests": (dict(verdict="COMPLETE RUN, NOT PASSING", collected=10, executed=10, passed=8, failed=2),
                      "OPEN", "COMPLETE RUN, NOT PASSING: 10 collected, 8 passed"),
    "all passed": (dict(verdict="COMPLETE RUN, ALL PASSED", collected=10, executed=10, passed=9, skipped=1),
                   "HELD", "COMPLETE RUN, ALL PASSED: 10 collected, 9 passed, 1 skipped"),
}
TRACES = {  # name -> (tracer arguments, expected state of "A refusal or integrity rule")
    "every refusal reached": ((0, "339 passed", 0, [], None), "HELD"),
    "unreached but registered": ((0, "339 passed", 2, [], None), "PARTIAL"),
    "unreached and unexplained": ((0, "339 passed", 1, ["x.py: raise ValueError('no')"], None), "OPEN"),
    "traced tests failed": ((1, "1 failed, 338 passed", 0, [], None), "OPEN"),
}


def _run(name):
    fields, _, _ = RUNS[name]
    if fields is None:
        from datetime import datetime
        return {**LEGACY_ENVIRONMENT_STOP, "at": datetime.now().astimezone().isoformat()}
    return runner.run_record(**fields)


def _write(folder, name, record):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(record))


def _gate(report, gate):
    return next(g for g in report["gates"] if g["gate"] == gate)


def test_the_runner_names_every_verdict_it_can_write_and_the_matrix_covers_them():
    covered = {(RUNS[n][0] or LEGACY_ENVIRONMENT_STOP)["verdict"] for n in RUNS}
    assert covered == set(runner.VERDICTS)
    with pytest.raises(ValueError, match=r"^run record fields not in the record shape: \['pass_count'\]$"):
        runner.run_record("INCOMPLETE RUN", pass_count=3)


def test_every_record_shape_has_every_field_a_reader_uses():
    for name in RUNS:
        if RUNS[name][0] is not None:
            record = _run(name)
            assert {"at", "verdict", "collected", "passed", "skipped", "environment_missing"} <= set(record)


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_gate_report_renders_every_run_record(isolated, name):
    from governance.production import gate_status as gs
    _write(gs.RUNS, "run.json", _run(name))
    gate = _gate(gs.generate(), "A valid test run")
    _, state, text = RUNS[name]
    assert gate["state"] == state and text in gate["evidence"]


@pytest.mark.parametrize("name", sorted(TRACES))
def test_the_gate_report_renders_every_trace_record(isolated, name):
    from governance.production import gate_status as gs
    args, state = TRACES[name]
    _write(gs.RUNS, "trace-x.json", tracer.trace_record(*args))
    assert _gate(gs.generate(), "A refusal or integrity rule")["state"] == state


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_scheduler_gate_status_job_survives_every_run_record(isolated, series, name):
    from governance.production import gate_status as gs, scheduler
    home, config_path = series
    _write(gs.RUNS, "run.json", _run(name))
    _write(gs.RUNS, "trace-x.json", tracer.trace_record(*TRACES["traced tests failed"][0]))
    result = scheduler.tick(config_path, jobs=[("gate_status", scheduler.job_gate_status)])
    assert result["jobs"]["gate_status"]["status"] == "OK"
    assert result["jobs"]["gate_status"]["gates"]["A valid test run"] == RUNS[name][1]


@pytest.mark.parametrize("name", sorted(RUNS))
def test_the_milestone_reads_every_run_record_and_trusts_only_a_passing_one(tmp_path, monkeypatch, name):
    monkeypatch.setattr(milestone, "ROOT", tmp_path)
    _write(tmp_path / ".test_runs", "2026-09-25T130500_0800.json", _run(name))
    _write(tmp_path / ".test_runs", "trace-2026-09-25T130500_0800.json", tracer.trace_record(0, "", 0, [], None))
    path, record = milestone._latest(False)
    assert path.name.startswith("2026") and record["verdict"] == (RUNS[name][0] or LEGACY_ENVIRONMENT_STOP)["verdict"]
    assert milestone._latest(True)[1]["verdict"] == "PASS"


ROUND_OUTCOMES = {  # milestone exit code and last lines -> what the round summary must say
    "all as expected": (0, "RESULT: ALL GATES AS EXPECTED\n", "milestone: RESULT: ALL GATES AS EXPECTED"),
    "differs": (1, "RESULT: DIFFERS: A valid test run\n", "milestone: RESULT: DIFFERS: A valid test run"),
    "stopped": (1, "VERDICT: ENVIRONMENT NOT READY — 1 required package(s) missing\n",
                "milestone: STOPPED. The last lines of milestone.txt:\n  VERDICT: ENVIRONMENT NOT READY"),
    "waiting on you": (3, "4. attestation: none yet.\n", "milestone: WAITING ON YOU: sign in the inbox"),
    "machine not ready": (None, "", "milestone: not run (the machine is not ready"),
}


@pytest.mark.parametrize("name", sorted(ROUND_OUTCOMES))
def test_the_round_summary_renders_every_milestone_outcome(tmp_path, name):
    code, text, expected = ROUND_OUTCOMES[name]
    folder = tmp_path / "round-x"
    folder.mkdir()
    if code is not None:
        (folder / "milestone.txt").write_text(text)
    summary = round_tool.summarise(folder, {"verdict": "READY", "checks": []}, code, None, None)
    assert expected in summary


def test_no_test_reads_this_machines_run_history_packs_pilot_or_raas(tmp_path):
    # D27 was a test outcome decided by the machine's own run history; this fails if the isolation ever lapses.
    from governance import raas, realrecords
    from governance.production import gate_status
    for path in (gate_status.RUNS, gate_status.PACKS, realrecords.home(), raas.home()):
        assert str(path).startswith(str(tmp_path)), f"{path} is outside this test's own folder"


def test_no_test_undoes_its_monkeypatch(tmp_path):
    # D29: monkeypatch.undo() also undoes the autouse fixtures that keep tests off the real state folders.
    import re
    from pathlib import Path
    tests = Path(__file__).resolve().parent
    call = re.compile(r"^\s*monkeypatch\.undo\(\)", re.M)                 # a statement, not a comment or a string
    assert call.search("    monkeypatch.undo()\n") and not call.search("    # never monkeypatch.undo()\n")
    assert [p.name for p in sorted(tests.glob("*.py")) if call.search(p.read_text())] == []
