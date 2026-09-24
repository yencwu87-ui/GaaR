from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_difficult_challenge_routes_to_colibri_when_enabled(monkeypatch):
    from inference.policy import TaskSignals, build_plan
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    monkeypatch.delenv("WB_CHALLENGE_PROVIDER", raising=False)
    plan = build_plan(TaskSignals(
        role="challenge_disagreement",
        control_id="M3.6",
        reviewer_disagreement=True,
    ))
    assert plan.provider == "colibri"
    assert plan.model == "glm-5.2-colibri"


def test_routine_challenge_stays_on_ollama_when_colibri_policy_is_enabled(monkeypatch):
    from inference.policy import TaskSignals, build_plan
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    monkeypatch.delenv("WB_CHALLENGE_PROVIDER", raising=False)
    plan = build_plan(TaskSignals(role="challenge", control_id="M3.6"))
    assert plan.provider == "ollama"


def test_explicit_provider_override_wins(monkeypatch):
    from inference.policy import TaskSignals, build_plan
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    monkeypatch.setenv("WB_PROVIDER_CHALLENGE_DISAGREEMENT", "ollama")
    plan = build_plan(TaskSignals(
        role="challenge_disagreement", control_id="M3.6", reviewer_disagreement=True
    ))
    assert plan.provider == "ollama"


def test_orchestrator_executes_colibri_and_records_provider(monkeypatch, tmp_path):
    import inference.orchestrator as orch

    calls = []
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    monkeypatch.setattr(orch, "call_colibri", lambda system, user, model, max_tokens=None: calls.append((model, user, max_tokens)) or '{"ok":true}')

    raw, plan, rec = orch.run_with_escalation(
        role="challenge_disagreement",
        system="system",
        user="user",
        signals=orch.TaskSignals(role="challenge_disagreement", control_id="M3.6", reviewer_disagreement=True),
        control_id="M3.6",
        task_id="TEST-COLIBRI",
    )
    assert raw == '{"ok":true}'
    assert plan.provider == "colibri"
    assert plan.model == "glm-5.2-colibri"
    assert calls and calls[0][0] == "glm-5.2-colibri"
    assert rec["provider"] == "colibri"
    assert rec["model"] == "glm-5.2-colibri"
    assert "control_complexity_band" in rec
    assert "complexity_band" in rec
    assert "control_complexity_reasons" in rec
    assert "complexity_reasons" in rec


def test_failed_ollama_can_fallback_to_colibri(monkeypatch):
    import inference.orchestrator as orch

    attempts = []
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "0")
    monkeypatch.setenv("WB_CHALLENGE_FALLBACK_PROVIDER", "colibri")
    monkeypatch.delenv("WB_CHALLENGE_PROVIDER", raising=False)

    def bad_ollama(system, user):
        attempts.append("ollama")
        raise RuntimeError("ollama unavailable")

    def good_colibri(system, user, model, max_tokens=None):
        attempts.append("colibri")
        return '{"ok":true}'

    monkeypatch.setattr(orch, "_call_legacy_ollama", bad_ollama)
    monkeypatch.setattr(orch, "call_colibri", good_colibri)

    raw, plan, rec = orch.run_with_escalation(
        role="challenge",
        system="system",
        user="user",
        signals=orch.TaskSignals(role="challenge", control_id="M3.6"),
        control_id="M3.6",
        task_id="TEST-FALLBACK",
    )
    assert raw == '{"ok":true}'
    assert attempts == ["ollama", "colibri"]
    assert plan.provider == "colibri"
    assert rec["escalated"] is True
    assert rec["provider"] == "colibri"



def test_colibri_primary_can_fall_back_to_ollama(monkeypatch):
    import inference.orchestrator as orch

    attempts = []
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    monkeypatch.setenv("WB_CHALLENGE_FALLBACK_PROVIDER", "ollama")
    monkeypatch.delenv("WB_CHALLENGE_PROVIDER", raising=False)

    def bad_colibri(system, user, model, max_tokens=None):
        attempts.append("colibri")
        raise RuntimeError("colibri unavailable")

    def good_ollama(system, user):
        attempts.append("ollama")
        return '{"ok":true}'

    monkeypatch.setattr(orch, "call_colibri", bad_colibri)
    monkeypatch.setattr(orch, "_call_legacy_ollama", good_ollama)

    raw, plan, rec = orch.run_with_escalation(
        role="challenge_disagreement",
        system="system",
        user="user",
        signals=orch.TaskSignals(role="challenge_disagreement", control_id="M3.6", reviewer_disagreement=True),
        control_id="M3.6",
        task_id="TEST-COLIBRI-FALLBACK",
    )
    assert raw == '{"ok":true}'
    assert attempts == ["colibri", "ollama"]
    assert plan.provider == "ollama"
    assert rec["escalated"] is True


def test_colibri_transport_parses_openai_compatible_response(monkeypatch):
    import llm.colibri as C

    class Response:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": "hello"}}]}

    seen = {}
    monkeypatch.setattr(C.requests, "post", lambda url, **kwargs: seen.update({"url": url, "kwargs": kwargs}) or Response())
    monkeypatch.setenv("COLIBRI_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("COLIBRI_MODEL", "glm-test")
    assert C.chat("sys", "usr") == "hello"
    assert seen["url"].endswith("/chat/completions")
    assert seen["kwargs"]["json"]["model"] == "glm-test"


def test_colibri_transport_rejects_malformed_response(monkeypatch):
    import pytest
    import llm.colibri as C

    class Response:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {"bad": "shape"}

    monkeypatch.setattr(C.requests, "post", lambda *a, **k: Response())
    with pytest.raises(RuntimeError, match="unexpected response"):
        C.chat("sys", "usr")


class _ComplexControl:
    id = "M3.6"
    lib = "MAS"
    req = "Independent validation " * 50
    artefacts = "a1; a2; a3; a4; a5"
    elements = tuple((f"e{i}", f"element {i}") for i in range(14))


def test_control_complexity_is_explicit_and_routes_assessment_to_colibri(monkeypatch):
    from inference.policy import control_complexity, build_plan, signals_for_control
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    profile = control_complexity(_ComplexControl())
    assert profile["band"] == "critical"
    assert profile["score"] >= 3
    signals = signals_for_control(_ComplexControl(), role="assess", evidence_chars=500)
    plan = build_plan(signals)
    assert plan.complexity_band == "critical"
    assert plan.provider == "colibri"
    assert "many_control_elements" in plan.complexity_reasons


def test_simple_control_remains_routine_and_uses_ollama(monkeypatch):
    from inference.policy import control_complexity, build_plan, signals_for_control
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    class Simple: 
        id = "SIMPLE"; req = "Short requirement"; artefacts = "a1"; elements = (("e1", "one"),)
    profile = control_complexity(Simple())
    assert profile["band"] == "routine"
    plan = build_plan(signals_for_control(Simple(), role="assess"))
    assert plan.complexity_band == "routine"
    assert plan.provider == "ollama"


def test_plan_exposes_control_complexity_separately_from_aggregate_task_band(monkeypatch):
    from inference.policy import TaskSignals, build_plan
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    plan = build_plan(TaskSignals(
        role="challenge",
        control_id="M3.6",
        control_complexity_score=2,
        reviewer_disagreement=True,
    ))
    assert plan.control_complexity_band == "complex"
    assert plan.complexity_band == "critical"
    assert plan.provider == "colibri"


def test_colibri_transport_accepts_explicit_router_budget(monkeypatch):
    import llm.colibri as colibri
    captured = {}

    class Response:
        ok = True
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(url, timeout, json, headers):
        captured.update(json)
        return Response()

    monkeypatch.setattr(colibri.requests, "post", fake_post)
    assert colibri.chat("system", "user", model="m", max_tokens=4096) == "ok"
    assert captured["max_tokens"] == 4096


def test_orchestrator_passes_inference_plan_budget_to_colibri(monkeypatch):
    import inference.orchestrator as orch
    from inference.policy import InferencePlan

    captured = {}
    monkeypatch.setattr(orch, "call_colibri", lambda system, user, **kw: captured.update(kw) or "ok")
    plan = InferencePlan(tier="critical", provider="colibri", model="m", num_predict=4096)
    assert orch._invoke_plan(plan, "system", "user", None) == "ok"
    assert captured["max_tokens"] == 4096


def test_colibri_router_budget_remains_tier_configurable(monkeypatch):
    from inference.policy import TaskSignals, build_plan
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    monkeypatch.setenv("WB_NUM_PREDICT_CRITICAL", "4096")
    plan = build_plan(TaskSignals(role="challenge", reviewer_disagreement=True, high_risk=True))
    assert plan.provider == "colibri"
    assert plan.tier == "critical"
    assert plan.num_predict == 4096


def test_control_band_can_raise_router_generation_floor(monkeypatch):
    from inference.policy import TaskSignals, build_plan
    monkeypatch.setenv("WB_NUM_PREDICT_STRONG", "1500")
    monkeypatch.setenv("WB_CONTROL_BUDGET_COMPLEX", "3072")
    plan = build_plan(TaskSignals(
        role="assess", control_complexity_score=1,
        control_complexity_reasons=("multiple_control_elements",),
    ))
    assert plan.tier == "strong"
    assert plan.control_complexity_band == "complex"
    assert plan.num_predict == 3072
