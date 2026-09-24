from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_copilot_probe_defines_all_acceptance_scenarios():
    src = (ROOT / "tools" / "live_copilot_probe.py").read_text(encoding="utf-8")
    for marker in ('"reference"', '"revise"', '"malformed"', '"fail"'):
        assert marker in src
    assert "copilot_rejected" in src
    assert "copilot_presented" in src
    assert "reviewer_read_unchanged" in src
    assert "control_complexity_band" in src
    assert "task_complexity_band" in src
    assert "task_id" in src


def test_live_probe_reports_review_correlation_and_raw_malformed_output():
    src = (ROOT / "tools" / "live_copilot_probe.py").read_text(encoding="utf-8")
    for marker in (
        "review_id", "RAW_MODEL_RESPONSE", "fallback_succeeded",
        "LIVE_COP_TASK_COUNT", "_print_review_metrics", "run_assessor=(scenario == \"revise\")",
    ):
        assert marker in src



def test_failure_probe_returns_nonzero_when_copilot_is_rejected(monkeypatch, capsys):
    import tools.live_copilot_probe as probe

    monkeypatch.setattr(probe, "_make_cycle", lambda control_id: "REV-D")
    monkeypatch.setattr(probe.cycle, "copilot_request", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(probe.events, "state", lambda cid: {"read": {"sufficiency": "partial"}})
    monkeypatch.setattr(probe.events, "cycle", lambda cid: [
        {"kind": "cycle_started"},
        {"kind": "read"},
        {"kind": "copilot_requested"},
        {"kind": "copilot_rejected"},
    ])
    monkeypatch.setattr(probe, "_count_task", lambda task_id: 0)
    monkeypatch.setattr(probe, "_print_tasks", lambda task_id: None)
    monkeypatch.setattr(probe, "_print_metrics", lambda task_id: None)
    monkeypatch.setattr(probe, "_print_review_metrics", lambda review_id: None)
    monkeypatch.setattr(probe, "_print_events", lambda cid: None)
    monkeypatch.setattr(probe, "build_plan", lambda signals: type("P", (), {"provider": "ollama", "model": "missing", "tier": "routine"})())
    monkeypatch.setattr(probe, "signals_for_control", lambda *a, **k: object())
    monkeypatch.setattr(probe, "fallback_state", lambda *a, **k: {"mode": "no_fallback_configured", "on_failure": "blocked"})
    assert probe._run_failure("M1.2") == 1
