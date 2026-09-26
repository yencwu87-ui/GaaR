"""Runbook U1, step 2: a record blocked only by a software upgrade is rerun under the current software.

Found on the Mac (kit v19): v19 changed code inside the software fingerprint, so week 3, produced under v18, could
no longer be attested, while the milestone tool told the reviewer to go and sign it. The rerun is what the runbook
prescribes; these tests pin what it may and may not do.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_guards_exercised import _cli, _load, series  # noqa: F401  (series is a fixture)
from tests.test_recurring import _attest

SGT = timezone(timedelta(hours=8))
AFTER_WEEK3 = datetime(2026, 10, 1, 9, 0, tzinfo=SGT)
WEEK3 = "CHG-WEEKLY-2026-09-29"


def _upgrade(monkeypatch, part="code_sha256"):
    """Simulate installing new software: the fingerprint the records were bound to no longer matches."""
    import governance.production.orchestrator as orch
    import governance.production.qualification as qual
    original = qual.fingerprint
    upgraded = lambda config: {**original(config), part: "0" * 64}
    monkeypatch.setattr(qual, "fingerprint", upgraded)          # read by the change check
    monkeypatch.setattr(orch, "fingerprint", upgraded)          # read by the run's binding: one software, both places


def _ready(config, root, iid=WEEK3):
    from governance import decisions
    from governance.investigation import InvestigationEngine, InvestigationStore
    from governance.production import recurring
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    return decisions.deterministic_preflight(config, root, iid, engine, recurring._journal(config, root, iid))


def _week3(series):
    from governance.production import recurring
    home, config_path = series
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    recurring.tick(config, root, now=AFTER_WEEK3)
    return home, config, root


def test_a_record_blocked_only_by_an_upgrade_is_rerun_and_the_old_one_kept_intact(series, monkeypatch):
    from governance.production import recurring
    home, config, root = _week3(series)
    case = recurring._case(config, root, WEEK3)
    old_sha = hashlib.sha256((case / "operations.sqlite").read_bytes()).hexdigest()
    old_head = recurring._journal(config, root, WEEK3).read()[-1]["event_hash"]
    _upgrade(monkeypatch)
    blocked = _ready(config, root)
    assert not blocked["ready"] and any("software was updated" in p for p in blocked["problems"])

    notices = []
    summary = {s["label"]: s for s in recurring.tick(config, root, notify=notices.append)}   # real clock
    week3 = summary["2026-09-29"]
    assert week3["state"] == "AWAITING_ATTESTATION" and week3["superseded"]["changed_parts"] == ["code_sha256"]
    kept = root / week3["superseded"]["superseded_to"] / "operations.sqlite"
    assert hashlib.sha256(kept.read_bytes()).hexdigest() == old_sha == week3["superseded"]["superseded_journal_sha256"]
    journal = recurring._journal(config, root, WEEK3)
    first = journal.read()[0]
    assert first["kind"] == "record_superseded" and first["payload"]["superseded_head"] == old_head
    assert _ready(config, root)["ready"], _ready(config, root)["problems"]
    assert any("rerun under the current software (runbook U1)" in n for n in notices)


def test_the_rerun_uses_the_clock_the_record_was_assessed_on(series, monkeypatch):
    """Rerun on today's real clock, week 3 (ending 2026-09-29) would be quarantined as a premature export."""
    from governance.production import recurring
    home, config, root = _week3(series)
    _upgrade(monkeypatch)
    week3 = {s["label"]: s for s in recurring.tick(config, root, now=datetime(2026, 9, 24, 12, tzinfo=SGT))}["2026-09-29"]
    assert week3["superseded"]["clock_reused"] == AFTER_WEEK3.isoformat() and not week3.get("integrity_event")
    rec = recurring._journal(config, root, WEEK3).latest("obligation_reconciliation")["payload"]
    assert rec["clock_simulated"] == AFTER_WEEK3.isoformat()


def test_an_attested_record_is_never_rerun(series, monkeypatch):
    from governance.production import recurring
    home, config, root = _week3(series)
    _attest(config, root, WEEK3, "NO_EXCEPTIONS_NOTED", True, "Week 3 checked with corroborated coverage; nothing raised.")
    _upgrade(monkeypatch)
    week3 = {s["label"]: s for s in recurring.tick(config, root)}["2026-09-29"]
    assert week3["state"] == "ATTESTED" and not week3.get("superseded")
    assert not (recurring._case(config, root, WEEK3).parent.parent / "superseded").exists()


def test_a_changed_evidence_export_is_never_rerun_away(series, monkeypatch):
    """A rerun would launder a changed export: it stays blocked as a potential integrity event (runbook E1)."""
    from governance.production import recurring
    home, config, root = _week3(series)
    _upgrade(monkeypatch)
    export = root / config["periodic_evidence"]["inbox"] / "2026-09-29" / "changes.json"
    export.write_text(export.read_text().replace("}", " }", 1))
    week3 = {s["label"]: s for s in recurring.tick(config, root)}["2026-09-29"]
    assert not week3.get("superseded")
    assert any("was changed after this run" in p for p in _ready(config, root)["problems"])


def test_a_policy_change_is_not_an_upgrade_rerun(series, monkeypatch):
    from governance.production import recurring
    home, config, root = _week3(series)
    _upgrade(monkeypatch, part="quality_policy_sha256")
    week3 = {s["label"]: s for s in recurring.tick(config, root)}["2026-09-29"]
    assert not week3.get("superseded")


def test_a_failed_rerun_restores_the_previous_record(series, monkeypatch):
    """Otherwise an empty case would read as unassessed, and on a real clock its exports could be quarantined."""
    import governance.production.orchestrator as orch
    from governance.production import recurring
    home, config, root = _week3(series)
    old_sha = hashlib.sha256((recurring._case(config, root, WEEK3) / "operations.sqlite").read_bytes()).hexdigest()
    _upgrade(monkeypatch)
    monkeypatch.setattr(orch, "run", lambda *a, **k: {"checkpoint": "ACTION_REQUIRED"})
    week3 = {s["label"]: s for s in recurring.tick(config, root)}["2026-09-29"]
    assert "produced no record" in week3["rerun_failed"] and week3["state"] == "AWAITING_ATTESTATION"
    restored = recurring._case(config, root, WEEK3) / "operations.sqlite"
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == old_sha
    assert (root / config["periodic_evidence"]["inbox"] / "2026-09-29").exists()          # nothing quarantined


def test_the_upgrade_check_itself_refuses_an_attested_record(series, monkeypatch):
    """Defence in depth: the tick never offers an attested period, and the check refuses one on its own."""
    from governance.operations.runtime import signers_for
    from governance.production import recurring
    home, config, root = _week3(series)
    _attest(config, root, WEEK3, "NO_EXCEPTIONS_NOTED", True, "Week 3 checked with corroborated coverage; nothing raised.")
    _upgrade(monkeypatch)
    period = next(p for p in recurring.verify(config, root)["periods"] if p["investigation_id"] == WEEK3)
    assert recurring.upgrade_only(config, root, period, signers_for(config, root)["executor"]) is None


def test_a_rerun_refuses_a_simulated_clock_outside_a_constructed_demo(series, monkeypatch):
    from governance.operations.runtime import signers_for
    from governance.production import recurring
    home, config, root = _week3(series)
    period = next(p for p in recurring.verify(config, root)["periods"] if p["investigation_id"] == WEEK3)
    with pytest.raises(ValueError, match="^a simulated clock is allowed only for a signed constructed demonstration series$"):
        recurring.rerun_after_upgrade(config, root, period, signers_for(config, root)["executor"], ["code_sha256"],
                                      constructed_demo=False)
    assert recurring._record(recurring._journal(config, root, WEEK3)) is not None       # nothing moved
