
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_cycle_challenge_is_the_single_production_entrypoint():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    stress = (ROOT / "governance_stress_demo.py").read_text(encoding="utf-8")
    assert "challenge_disagreement as run_challenge2" not in app
    assert "governance_cycle.challenge(" in app
    assert 'is_harness = site_path.name == "governance_stress_demo.py"' in stress


def test_decision_boundary_has_explicit_reviewer_decision_record():
    src = (ROOT / "core" / "cycle.py").read_text(encoding="utf-8")
    assert "reviewer_decision = {" in src
    assert "reviewer_decision=reviewer_decision" in src
    assert 'events.append("decided"' in src


def test_declared_freshness_expires_at_decision_boundary():
    from core import cycle

    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")

    assert cycle._decision_time_freshness({"evidence": {"fresh_until": future}})["status"] == "known"
    result = cycle._decision_time_freshness({"evidence": {"fresh_until": past}})
    assert result["status"] == "stale"
    assert result["stale"][0]["source"] == "evidence"


def test_missing_freshness_is_unknown_not_blocked():
    from core import cycle
    result = cycle._decision_time_freshness({"evidence": {"text": "manual evidence"}})
    assert result["status"] == "unknown"
    assert result["stale"] == []


def test_evidence_packet_carries_observation_freshness():
    from governance.observation import Observation
    from observations import observation_to_evidence_packet

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
    obs = Observation(
        observation_id="obs-1",
        subject="repo:org/repo",
        source="plugin",
        observed_at=now,
        payload={"fact": "x"},
        provenance={"target": {"id": "org/repo"}, "resource": "repo"},
        fresh_until=future,
    )
    packet = observation_to_evidence_packet(obs)
    assert packet.fresh_until == future


def test_ui_challenge_my_reading_delegates_to_cycle_entrypoint():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "governance_cycle.challenge_read(" in app
    assert "run_challenge(" not in app


def test_cycle_challenge_does_not_wrap_provider_owned_transport():
    src = (ROOT / "core" / "cycle.py").read_text(encoding="utf-8")
    start = src.index("def challenge_read(")
    end = src.index("def record_challenge(", start)
    read_block = src[start:end]
    start2 = src.index("def challenge(")
    end2 = src.index("def _last_challenge_run(", start2)
    disagreement_block = src[start2:end2]
    assert 'with llm.model_for("challenge")' not in read_block
    assert 'with llm.model_for("challenge_disagreement")' not in disagreement_block


def test_decide_itself_blocks_expired_freshness(monkeypatch):
    from core import cycle
    import pytest
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    state = {
        "control_id": "M3.6", "framework": "MAS",
        "evidence": {"fresh_until": past},
        "read": {"sufficiency": "partial", "maturity": 2, "reason": "Evidence does not show the required element."},
    }
    appended = []
    monkeypatch.setattr(cycle.events, "state", lambda _cid: state)
    monkeypatch.setattr(cycle.events, "iter_states", lambda: iter(()))
    monkeypatch.setattr(cycle.events, "append", lambda *a, **k: appended.append((a, k)) or {})
    with pytest.raises(cycle.CycleError, match="stale"):
        cycle.decide("C-STale", sufficiency="partial", maturity=2,
                     reason="Evidence does not show the required element.", reviewer="tester")
    assert appended == []


def test_decide_itself_blocks_malformed_freshness(monkeypatch):
    from core import cycle
    import pytest
    state = {
        "control_id": "M3.6", "framework": "MAS",
        "evidence": {"fresh_until": "not-a-timestamp"},
        "read": {"sufficiency": "partial", "maturity": 2, "reason": "Evidence does not show the required element."},
    }
    monkeypatch.setattr(cycle.events, "state", lambda _cid: state)
    monkeypatch.setattr(cycle.events, "iter_states", lambda: iter(()))
    with pytest.raises(cycle.CycleError, match="malformed evidence freshness"):
        cycle.decide("C-BAD-FRESH", sufficiency="partial", maturity=2,
                     reason="Evidence does not show the required element.", reviewer="tester")


def test_decide_missing_freshness_remains_unknown(monkeypatch):
    from core import cycle
    import pytest
    state = {
        "control_id": "M3.6", "framework": "MAS",
        "evidence": {"text": "manual evidence"},
        "read": {"sufficiency": "partial", "maturity": 2, "reason": "Evidence does not show the required element."},
    }
    monkeypatch.setattr(cycle.events, "state", lambda _cid: state)
    monkeypatch.setattr(cycle.events, "iter_states", lambda: iter(()))
    monkeypatch.setattr(cycle.events, "append", lambda *a, **k: {})
    monkeypatch.setattr(cycle, "_control", lambda *a, **k: object())
    monkeypatch.setattr("reasons.reason_error", lambda *a, **k: None)
    # Missing freshness itself is not the blocker; the test therefore reaches governance evaluation.
    monkeypatch.setattr("governance.decision_engine.evaluate", lambda **k: {"decision_eligible": True, "blockers": []})
    result = cycle.decide("C-NO-FRESH", sufficiency="partial", maturity=2,
                          reason="Evidence does not show the required element.", reviewer="tester")
    assert result["decision_time_freshness"]["status"] == "unknown"
