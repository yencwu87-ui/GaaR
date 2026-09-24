import json
from pathlib import Path


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_operations_snapshot_projects_durable_metrics(monkeypatch, tmp_path):
    import ui.operations_dashboard as D

    monkeypatch.setattr(D, "GOV", tmp_path)
    _write(tmp_path / "inference_tasks.jsonl", [
        {"completed": True, "escalated": False, "provider": "ollama", "tier": "routine", "role": "assess", "elapsed_ms": 100, "generation_budget": 1200},
        {"completed": True, "escalated": True, "provider": "colibri", "tier": "critical", "role": "challenge", "elapsed_ms": 400, "generation_budget": 4096},
        {"completed": False, "escalated": False, "provider": "ollama", "tier": "strong", "role": "copilot", "elapsed_ms": 200, "generation_budget": 1800},
    ])
    _write(tmp_path / "llm_metrics.jsonl", [
        {"ok": True, "provider": "ollama", "ms": 90},
        {"ok": False, "provider": "colibri", "ms": 410},
    ])

    class State:
        def __init__(self, rid, state):
            self.result_id = rid
            self.to_state = state
    class V:
        def __init__(self, value): self.value = value
    class Case:
        def __init__(self, status): self.status = status

    monkeypatch.setattr(D, "_integrity_projection", lambda: {
        "checks": {"result_store": {"ok": True, "records": 2, "error": ""}},
        "results": [object(), object()],
        "state_events": [State("R1", V("SUPERSEDED")), State("R2", V("CURRENT"))],
        "change_rows": [{"record_type": "GovernanceChange"}, {"record_type": "ImpactAssessment"}],
        "reassessment_rows": [Case("RESOLVED")],
    })

    snap = D.snapshot()
    assert snap["inference"]["tasks"] == 3
    assert snap["inference"]["completed"] == 2
    assert snap["inference"]["failed"] == 1
    assert snap["inference"]["escalated"] == 1
    assert snap["inference"]["providers"] == {"ollama": 2, "colibri": 1}
    assert snap["inference"]["budget_min"] == 1200
    assert snap["inference"]["budget_max"] == 4096
    assert snap["calls"]["success_rate"] == 0.5
    assert snap["gaar"]["results"] == 2
    assert snap["gaar"]["states"] == {"SUPERSEDED": 1, "CURRENT": 1}
    assert snap["gaar"]["reassessment_status"] == {"RESOLVED": 1}


def test_app_exposes_operations_dashboard_and_theme_aware_outcomes():
    root = Path(__file__).resolve().parents[1]
    src = (root / "app.py").read_text(encoding="utf-8")
    assert '"Operations"' in src
    assert "render_operations_dashboard(THEME)" in src
    assert "background:{_STICKY_BG}" in src
    assert "border:1px solid {_STICKY_LINE}" in src
