from __future__ import annotations

from inference.policy import TaskSignals, build_plan, control_complexity, signals_for_control


class _FakeControl:
    def __init__(self, elements=(), req="", artefacts=""):
        self.elements = elements
        self.req = req
        self.artefacts = artefacts


def _elements(n):
    return tuple(f"element-{i}" for i in range(n))


def _artefacts(n):
    return ";".join(f"artefact-{i}" for i in range(n))


def test_score_zero_is_routine():
    result = control_complexity(_FakeControl(elements=_elements(7), req="", artefacts=""))
    assert result["score"] == 0
    assert result["band"] == "routine"
    assert result["reasons"] == ()


def test_score_one_is_complex():
    result = control_complexity(_FakeControl(elements=_elements(8), req="", artefacts=""))
    assert result["score"] == 1
    assert result["band"] == "complex"
    assert result["reasons"] == ("multiple_control_elements",)


def test_score_two_is_complex_not_critical():
    result = control_complexity(_FakeControl(elements=_elements(12), req="", artefacts=""))
    assert result["score"] == 2
    assert result["band"] == "complex"
    assert result["reasons"] == ("many_control_elements",)


def test_score_three_is_critical():
    result = control_complexity(
        _FakeControl(elements=_elements(12), req="", artefacts=_artefacts(5))
    )
    assert result["score"] == 3
    assert result["band"] == "critical"


def test_score_four_is_maximum_with_current_weights_and_is_critical():
    result = control_complexity(
        _FakeControl(elements=_elements(14), req="x" * 900, artefacts=_artefacts(5))
    )
    assert result["score"] == 4
    assert result["band"] == "critical"


def test_signal_boundaries_are_exact():
    assert control_complexity(_FakeControl(elements=_elements(7)))["score"] == 0
    assert control_complexity(_FakeControl(elements=_elements(8)))["score"] == 1
    assert control_complexity(_FakeControl(elements=_elements(11)))["score"] == 1
    assert control_complexity(_FakeControl(elements=_elements(12)))["score"] == 2
    assert control_complexity(_FakeControl(artefacts=_artefacts(4)))["score"] == 0
    assert control_complexity(_FakeControl(artefacts=_artefacts(5)))["score"] == 1
    assert control_complexity(_FakeControl(req="x" * 899))["score"] == 0
    assert control_complexity(_FakeControl(req="x" * 900))["score"] == 1


def test_control_band_is_distinct_from_runtime_task_band(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    control = _FakeControl(elements=_elements(12), req="", artefacts="")
    signals = signals_for_control(control, role="assess")
    plan = build_plan(signals)
    assert signals.control_complexity_score == 2
    assert plan.control_complexity_band == "complex"
    # Runtime `element_count > 8` adds another task signal, so the aggregate task tier
    # may become critical even though the control's structural band remains complex.
    assert plan.complexity_band == "critical"
    assert plan.provider == "colibri"


def test_score_one_control_alone_routes_to_colibri_when_enabled(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    signals = signals_for_control(
        _FakeControl(elements=_elements(8)), role="assess"
    )
    plan = build_plan(signals)
    assert plan.control_complexity_score == 1
    assert plan.control_complexity_band == "complex"
    assert plan.provider == "colibri"


def test_routine_control_with_runtime_disagreement_still_routes_to_colibri(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    signals = signals_for_control(
        _FakeControl(elements=_elements(3)),
        role="challenge_disagreement",
        reviewer_disagreement=True,
    )
    plan = build_plan(signals)
    assert plan.control_complexity_band == "routine"
    assert plan.provider == "colibri"


def test_provider_routing_uses_canonical_band_for_score_one(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    signals = TaskSignals(role="assess", control_complexity_score=1)
    plan = build_plan(signals)
    assert plan.control_complexity_band == "complex"
    assert plan.provider == "colibri"


def test_provider_routing_uses_critical_band_for_score_three(monkeypatch):
    monkeypatch.setenv("WB_COLIBRI_ENABLED", "1")
    signals = TaskSignals(role="assess", control_complexity_score=3)
    plan = build_plan(signals)
    assert plan.control_complexity_band == "critical"
    assert plan.provider == "colibri"


def test_dict_contract_shape_is_supported_without_attribute_assumptions():
    result = control_complexity({
        "control_id": "X",
        "requirement": "x" * 900,
        "elements": _elements(12),
        "expected_evidence": ["a", "b", "c", "d", "e"],
    })
    assert result["score"] == 4
    assert result["band"] == "critical"
