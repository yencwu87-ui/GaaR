"""The workbench (app.py) after kit v21: six destinations instead of sixteen tabs, only the open section runs."""
import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"


def _literal(name):
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)
    return ast.literal_eval(node.value)


def test_every_classic_tab_has_exactly_one_home_in_the_new_navigation():
    views = {v: [k for k, _ in spec[3]] for v, spec in _literal("VIEWS").items()}
    sections = {f"{v}/{s}" for v, ss in views.items() for s in ss}
    tabs = _literal("TAB_SECTIONS")
    source = APP.read_text(encoding="utf-8")
    assert len(tabs) == 16 and set(tabs.values()) <= sections
    for tab in tabs:
        assert f"if {tab}.shown:\n    with {tab}:" in source, tab
    custom = {"review/decide", "watch/intel", "settings/general", "results/impact", "reports/arena", "results/basis"}
    assert sections == set(tabs.values()) | custom          # nothing unreachable, nothing without a body


def test_one_ledger_read_serves_every_cycle(tmp_path, monkeypatch):
    import events
    monkeypatch.setattr(events, "LOG", tmp_path / "events.jsonl")
    for control in ("M1.1", "M3.6"):
        cid = events.new_cycle_id(control)
        events.append("cycle_started", cycle_id=cid, actor="t", control_id=control, framework="MAS", payload={"title": control})
        events.append("proposed", cycle_id=cid, actor="t", control_id=control, framework="MAS",
                      payload={"sufficiency": "partial", "maturity": 2})
    per_cycle = [events.state(c) for c in events.cycles()]
    reads = []
    original = events.read_all
    monkeypatch.setattr(events, "read_all", lambda path=None: reads.append(1) or original(path))
    assert json.dumps(list(events.iter_states()), sort_keys=True) == json.dumps(per_cycle, sort_keys=True)
    assert reads == [1]


def test_the_playbook_is_parsed_once_and_each_caller_gets_its_own_copy(monkeypatch):
    import playbook
    from core import cycle
    calls = []
    original = playbook.load_controls
    monkeypatch.setattr(playbook, "load_controls", lambda p: calls.append(p) or original(p))
    cycle._CONTROLS_CACHE.clear()
    first = cycle._control("M1.1", "MAS")
    first.title = "changed by a caller"
    second = cycle._control("M1.1", "MAS")
    assert len(calls) == 1 and second.title != "changed by a caller"


@pytest.fixture(scope="module")
def workbench(tmp_path_factory):
    """The workbench runs in a throwaway folder: it saves data/assessments.json relative to where it runs, and a test
    must never overwrite the reviewer's real state or ledger."""
    import os
    import shutil
    from streamlit.testing.v1 import AppTest
    home = tmp_path_factory.mktemp("workbench")
    (home / "data").mkdir()
    for book in (ROOT / "data").glob("*.xlsx"):
        shutil.copy(book, home / "data" / book.name)
    ledger = ROOT / "governance" / "events.jsonl"
    if ledger.exists():
        shutil.copy(ledger, home / "events.jsonl")
    patch = pytest.MonkeyPatch()
    patch.chdir(home)                                   # belt and braces: nothing should be cwd-relative any more
    patch.setenv("GAAR_WORKBENCH_DATA", str(home / "data"))
    patch.setenv("WB_EVENT_LOG", str(home / "events.jsonl"))
    import events
    from core import cycle
    patch.setattr(events, "LOG", home / "events.jsonl")
    cycle._CONTROLS_CACHE.clear()
    yield AppTest.from_file(str(APP), default_timeout=300)
    patch.undo()


def test_the_tests_never_touch_the_real_workbench_state(workbench):
    before = (ROOT / "data" / "assessments.json").read_bytes() if (ROOT / "data" / "assessments.json").exists() else None
    workbench.run()
    after = (ROOT / "data" / "assessments.json").read_bytes() if (ROOT / "data" / "assessments.json").exists() else None
    assert before == after


def test_today_is_a_short_page_with_one_next_step(workbench):
    workbench.run()
    assert not workbench.exception
    assert len(workbench.button) <= 8
    assert any("Here is what needs you." in m.value for m in workbench.markdown)


def test_with_no_name_the_next_step_points_at_the_name_box_not_somewhere_else(workbench):
    workbench.run()
    workbench.text_input(key="reviewer-name").input("").run()
    assert any("Type your name in the box on the left" in c.value for c in workbench.caption)


def test_the_next_step_button_opens_the_right_place(workbench):
    workbench.run()
    workbench.text_input(key="reviewer-name").input("Test Reviewer").run()
    workbench.session_state["nav"] = "today"
    workbench.run()
    workbench.button(key="today-go").click().run()
    assert workbench.session_state["nav"] != "today" and not workbench.exception


@pytest.mark.parametrize("view, section", [
    ("review", "scan"), ("review", "assess"), ("review", "decide"), ("results", "live"), ("results", "impact"), ("results", "basis"), ("results", "outcomes"),
    ("results", "history"), ("results", "lifecycle"), ("watch", "intel"), ("watch", "change"), ("watch", "sources"),
    ("reports", "report"), ("reports", "audit"), ("reports", "measure"), ("reports", "arena"), ("settings", "general"), ("settings", "ai"),
    ("settings", "autopilot"), ("settings", "engine"), ("settings", "ops")])
def test_every_section_renders(workbench, view, section):
    workbench.session_state["nav"] = view
    workbench.session_state[f"sec_{view}"] = section
    workbench.run()
    assert not workbench.exception, [e.message for e in workbench.exception]


def test_what_if_shows_what_a_lapse_would_flag_and_where_its_cause_may_sit(workbench):
    workbench.session_state["nav"] = "results"
    workbench.session_state["sec_results"] = "impact"
    workbench.run()
    workbench.radio(key="impact-source").set_value("What if…").run()
    workbench.multiselect(key="impact-lapsed").set_value(["MAS:M2.2"]).run()
    workbench.multiselect(key="impact-weak").set_value(["MAS:M3.6"]).run()
    assert not workbench.exception
    metrics = {m.label: m.value for m in workbench.metric}
    assert metrics["Lapsed or weak"] == "2" and int(metrics["Other controls flagged"]) >= 4
    assert any("likely common cause" in w.value for w in workbench.warning)
    tables = [t.value for t in workbench.dataframe]
    assert any("Before relying, corroborate" in t.columns for t in tables)


def test_workbench_state_resolves_to_one_absolute_place(tmp_path, monkeypatch):
    """D19's root cause: state resolved relative to the working directory. It never is now."""
    from governance.paths import workbench_data
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GAAR_WORKBENCH_DATA", raising=False)
    assert workbench_data() == (ROOT / "data").resolve() and workbench_data().is_absolute()
    monkeypatch.setenv("GAAR_WORKBENCH_DATA", str(tmp_path / "elsewhere"))
    assert workbench_data() == (tmp_path / "elsewhere").resolve()
    source = APP.read_text(encoding="utf-8")
    assert 'DATA = Path("data")' not in source and "DATA = workbench_data()" in source


# Paths that may legitimately follow the working directory, each with its reason. Anything else that resolves
# state relative to where a program was started fails this test (D19's root cause, enforced).
CWD_ALLOWED = {
    "governance_stress_demo.py": "--repo names the repository to analyse; the current one is the natural default",
    "governance/operations/runtime.py": "signing keys named relative to the caller's own root; no state is written",
}
CWD_STATE = re.compile(r"(Path|open)\(f?[\"'](\./)?(data|governance|reports|packs|runs|var|\.test_runs|\.cache)[/\"']"
                       r"|os\.getcwd\(\)|Path\.cwd\(\)")


def test_no_runtime_state_is_resolved_relative_to_the_working_directory():
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".", "venv")) or "/." in rel or rel.split("/")[-1].startswith("test_"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if CWD_STATE.search(line) and rel not in CWD_ALLOWED:
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert offenders == []


def test_two_installed_copies_sharing_one_state_folder_are_reported(tmp_path, monkeypatch):
    from governance import paths
    data = tmp_path / "shared-state"
    data.mkdir()
    assert paths.shared_state_warning(data) is None                        # first use claims the folder
    assert (data / paths.MARKER).read_text().strip() == str(paths.PACKAGE)
    other = tmp_path / "another-copy"
    other.mkdir()
    (data / paths.MARKER).write_text(str(other))
    assert "also used by another installed copy at " + str(other) in paths.shared_state_warning(data)
    other.rmdir()                                                          # that copy was removed or replaced in place
    assert paths.shared_state_warning(data) is None and (data / paths.MARKER).read_text().strip() == str(paths.PACKAGE)
