"""Kit v20: one scheduler, a derived inbox, the simple view, frozen packs.

The acceptance conditions are pinned here:
1. inbox items age, under a signed rule, and name the journal event they come from;
2. an empty inbox is trustworthy only while the scheduler is alive, so its health is on the inbox itself;
3. packs for outside readers are frozen, not live;
4. the UI reads journals and hosts signed human actions; machine work runs in the scheduler; no second path.
And the migration risks: the reading order (evidence before any decision), per-job isolation, job stop semantics,
and that nothing the classic view reaches is lost in the simple one.
"""
import ast
import re
import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_guards_exercised import _cli, _load, series  # noqa: F401  (series is a fixture)
from tests.test_recurring import _attest

ROOT = Path(__file__).resolve().parents[1]
SGT = timezone(timedelta(hours=8))
AFTER_WEEK3 = datetime(2026, 10, 1, 9, 0, tzinfo=SGT)
WEEK3 = "CHG-WEEKLY-2026-09-29"


def _ticked(series, weeks=(3,)):
    from governance.production import scheduler
    home, config_path = series
    for week in weeks:
        _cli(home, "demo-inbox", "--config", config_path, "--week", week)
    result = scheduler.tick(config_path, now=AFTER_WEEK3)
    return home, config_path, result


def _journal_bytes(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(root).rglob("*.sqlite")}


# ---------------------------------------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------------------------------------

def test_a_job_that_reaches_a_gate_stops_there_and_yields_exactly_one_item(series):
    from governance.production import inbox, recurring
    home, config_path, result = _ticked(series)
    assert result["jobs"]["series"]["stopped_at_gate"] == ["2026-09-29"]
    items = [i for i in inbox.items(config_path, AFTER_WEEK3) if i.get("investigation_id") == WEEK3]
    assert [i["kind"] for i in items] == ["attest"]
    config, root = _load(config_path)
    kinds = [e["kind"] for e in recurring._journal(config, root, WEEK3).read()]
    assert "pilot_attestation" not in kinds                  # the job wrote nothing past the gate


def test_one_job_crashing_does_not_stop_the_others_and_becomes_work(series):
    from governance.production import inbox, scheduler
    home, config_path = series
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)

    def boom(ctx):
        raise RuntimeError("watcher source unreachable")
    result = scheduler.tick(config_path, now=AFTER_WEEK3,
                            jobs=[("boom", boom), ("series", scheduler.job_series)])
    assert result["jobs"]["boom"]["status"] == "FAILED" and result["jobs"]["series"]["status"] == "OK"
    config, root = _load(config_path)
    outcomes = [e["payload"] for e in scheduler.journal_for(config, root).read() if e["kind"] == "job_outcome"]
    assert {o["job"]: o["status"] for o in outcomes} == {"boom": "FAILED", "series": "OK"}
    failed = [i for i in inbox.items(config_path) if i["kind"] == "job_failed"]
    assert len(failed) == 1 and "watcher source unreachable" in failed[0]["why"]
    assert failed[0]["origin"]["event_hash"] == result["jobs"]["boom"]["event_hash"]


def test_an_empty_inbox_says_whether_the_scheduler_is_alive(series):
    from governance.production import inbox, scheduler
    home, config_path = series
    never = inbox.items(config_path)
    assert never[0]["id"] == "scheduler:never"                       # first: it decides whether the rest is trusted
    assert [i["id"] for i in never if i["who"] == "SYSTEM"] == ["scheduler:never"]
    assert "scheduler has never run" in inbox.status_line(config_path)["text"]
    scheduler.tick(config_path, now=AFTER_WEEK3)
    assert not [i for i in inbox.items(config_path) if i["who"] == "SYSTEM"]
    later = datetime.now().astimezone() + timedelta(hours=3)          # two intervals missed
    stale = [i for i in inbox.items(config_path, later) if i["id"] == "scheduler:stale"]
    assert stale and "STALE" in inbox.status_line(config_path, later)["text"]


def test_a_series_that_drifted_from_what_was_signed_is_a_system_item(series):
    from governance.production import inbox, scheduler
    home, config_path = series
    scheduler.tick(config_path, now=AFTER_WEEK3)
    config = json.loads(Path(config_path).read_text())
    config["periodic_evidence"]["slack_minutes"] = 600
    Path(config_path).write_text(json.dumps(config))
    refused = [i for i in inbox.items(config_path) if i["id"] == "series:refused"]
    assert refused and "arrival slack window differs" in refused[0]["why"]


# ---------------------------------------------------------------------------------------------------------
# The inbox
# ---------------------------------------------------------------------------------------------------------

def test_items_age_under_the_signed_cadence_and_name_their_origin(series):
    from governance.production import inbox, recurring
    home, config_path, _ = _ticked(series)
    config, root = _load(config_path)
    item = next(i for i in inbox.items(config_path) if i["id"] == "attest:2026-09-29")
    report = next(e for e in recurring._journal(config, root, WEEK3).read() if e["event_key"] == "deterministic_run_report")
    assert item["origin"]["event_hash"] == report["event_hash"] and item["since"] == report["at"]
    ready = datetime.fromisoformat(report["at"])
    assert datetime.fromisoformat(item["due"]) == ready + timedelta(days=7) and not item["overdue"]
    assert "7 days, signed in SA2-" in item["due_rule"]
    late = inbox.items(config_path, ready + timedelta(days=8))
    overdue = next(i for i in late if i["id"] == "attest:2026-09-29")
    assert overdue["overdue"] and overdue["age_days"] == 8.0
    humans = [i for i in late if i["who"] == "HUMAN"]
    assert humans[0]["id"] == "attest:2026-09-29"                     # overdue first


def test_an_attested_period_leaves_the_inbox(series):
    from governance.production import inbox
    home, config_path, _ = _ticked(series)
    config, root = _load(config_path)
    _attest(config, root, WEEK3, "NO_EXCEPTIONS_NOTED", True, "Week 3 checked with corroborated coverage; nothing raised.")
    assert not [i for i in inbox.items(config_path) if i.get("investigation_id") == WEEK3]


def test_reading_the_inbox_and_status_line_writes_nothing(series):
    from governance.production import inbox
    home, config_path, _ = _ticked(series)
    config, root = _load(config_path)
    before = _journal_bytes(root)
    inbox.items(config_path)
    inbox.status_line(config_path)
    assert _journal_bytes(root) == before


def test_the_status_line_reports_governance_and_says_it_is_not_governance(series):
    from governance.production import inbox
    home, config_path, _ = _ticked(series)
    line = inbox.status_line(config_path)
    assert line["text"].startswith("Gates: ") and " item(s) waiting" in line["text"] and "scheduler last ran" in line["text"]
    assert "it is not the gates" in line["help"] and "never typed in by hand" in line["help"]
    assert "tools/gaar_gate_status.py verify" in line["help"]


# ---------------------------------------------------------------------------------------------------------
# The UI invariant: no governed work in the inbox or the simple view
# ---------------------------------------------------------------------------------------------------------

FORBIDDEN_CALLS = {"tick", "_tick", "run", "run_investigation", "reconcile", "collect", "collect_periodic", "seal",
                   "quarantine", "rerun_after_upgrade", "authorise", "attest", "attest_deterministic", "freeze"}
JOURNAL_WRITE = re.compile(r"(journal|Journal\([^)]*\))\w*\.append\(")


def _calls(source):
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None))
    return names


def test_the_inbox_module_performs_no_governed_work():
    source = (ROOT / "governance/production/inbox.py").read_text()
    assert not _calls(source) & FORBIDDEN_CALLS
    assert not JOURNAL_WRITE.search(source) and "orchestrator" not in source


def test_the_simple_view_has_no_execution_path():
    import app_gaar
    source = inspect.getsource(app_gaar.render_simple)
    assert not _calls(source) & FORBIDDEN_CALLS and not JOURNAL_WRITE.search(source)
    labels = [n.args[0].value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", None) == "button" and n.args and isinstance(n.args[0], ast.Constant)]
    assert labels and set(labels) == {"Open"}                           # every button only opens an item


def _simple_app(monkeypatch, config_path):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("GAAR_UI", "simple")
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=90).run()
    app.text_input[0].input("t").run()
    assert not app.exception
    return app


def _in_order(app):
    out = []

    def walk(node):
        kids = getattr(node, "children", None)
        if isinstance(kids, dict) and kids:
            for k in sorted(kids):
                walk(kids[k])
        else:
            out.append((node.type, str(getattr(node, "value", "")), getattr(node, "key", None)))
    walk(app._tree[0])
    return out


def test_the_simple_view_shows_the_inbox_and_offers_no_run(series, monkeypatch):
    home, config_path, _ = _ticked(series)
    config, root = _load(config_path)
    before = _journal_bytes(root)
    app = _simple_app(monkeypatch, config_path)
    assert any(s.value == "Inbox" for s in app.subheader)
    assert any("Attest 2026-09-29" in m.value for m in app.markdown)
    assert not [b for b in app.button if "Run" in (b.label or "")]
    app.button(key="open-attest:2026-09-29").click().run()
    assert not app.exception and not [b for b in app.button if "Run" in (b.label or "")]
    assert _journal_bytes(root) == before                                # rendering and opening wrote nothing


def test_the_reviewer_reads_the_evidence_before_the_decision_form(series, monkeypatch):
    """Anti-anchoring order (policy 1.3 §8): a UI merge must not put the decision above what it decides on."""
    home, config_path, _ = _ticked(series, weeks=(2, 3))
    app = _simple_app(monkeypatch, config_path)
    app.button(key="open-attest:2026-09-29").click().run()
    order = _in_order(app)
    position = lambda test: next(i for i, e in enumerate(order) if test(e))
    reconciliation = position(lambda e: e[0] == "subheader" and e[1] == "Reconciled against the deterministic tests")
    delta = position(lambda e: e[1].startswith("#### Since the previous period"))
    form = position(lambda e: e[2] == "deterministic-decision")
    assert delta < reconciliation < form


def test_a_record_rerun_while_the_reviewer_reads_resets_their_confirmation(series, monkeypatch):
    import governance.production.orchestrator as orch
    import governance.production.qualification as qual
    from governance.production import recurring
    home, config_path, _ = _ticked(series)
    app = _simple_app(monkeypatch, config_path)
    app.button(key="open-attest:2026-09-29").click().run()
    app.text_area(key="deterministic-rationale").input(
        "Week 3 checked with corroborated coverage; nothing raised this period.").run()
    confirm = next(c for c in app.checkbox if (c.key or "").startswith("deterministic-confirm-"))
    confirm.check().run()
    assert not app.button(key="deterministic-sign").disabled
    original = qual.fingerprint
    upgraded = lambda config: {**original(config), "code_sha256": "0" * 64}
    monkeypatch.setattr(qual, "fingerprint", upgraded)
    monkeypatch.setattr(orch, "fingerprint", upgraded)
    config, root = _load(config_path)
    recurring.tick(config, root)                                         # the scheduler reruns week 3 (U1)
    app.run()
    assert not app.exception
    assert app.button(key="deterministic-sign").disabled                 # read again, confirm again


def test_every_assessment_the_classic_view_lists_is_reachable_in_the_simple_view(series, monkeypatch):
    import app_gaar
    home, config_path, _ = _ticked(series)
    config, root = _load(config_path)
    classic = [r["investigation_id"] for r in app_gaar.portfolio(config, root)]
    app = _simple_app(monkeypatch, config_path)
    options = app.selectbox(key="all-periods").options
    assert set(classic) <= set(options) and len(classic) == 4


# ---------------------------------------------------------------------------------------------------------
# Frozen packs
# ---------------------------------------------------------------------------------------------------------

def test_a_pack_is_frozen_from_a_verified_report_and_detects_any_later_edit(series, tmp_path):
    import importlib
    from governance.production import gate_status
    pack_tool = importlib.import_module("tools.gaar_pack")
    home, config_path, _ = _ticked(series)
    report = gate_status.generate(str(config_path))
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    frozen = pack_tool.freeze(path, out=tmp_path / "packs")
    check = pack_tool.verify(frozen["pack"])
    assert check["valid"] and "not a live regeneration" in check["reason"]
    folder = Path(frozen["folder"])
    edited = folder / "gate_status.md"
    edited.chmod(0o644)
    edited.write_text(edited.read_text() + "\nedited\n")
    assert not pack_tool.verify(folder)["valid"]
    tampered = json.loads(path.read_text())
    tampered["gates"][0]["state"] = "HELD" if tampered["gates"][0]["state"] != "HELD" else "OPEN"
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="a pack is never frozen from it"):
        pack_tool.freeze(path, out=tmp_path / "packs2")


def test_two_ticks_never_run_at_once(series):
    import fcntl
    from governance.production import scheduler
    home, config_path = series
    config, root = _load(config_path)
    folder = root / "scheduler"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / "tick.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(scheduler.SchedulerBusy, match="^another scheduler tick is running on this workspace$"):
            scheduler.tick(config_path)
