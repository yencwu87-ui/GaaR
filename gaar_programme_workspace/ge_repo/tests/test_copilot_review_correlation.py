from inference.orchestrator import run_with_escalation
from inference.policy import signals_for_control


class _Control:
    id = "M1.2"
    lib = "MAS"
    elements = []
    req = "short"
    artefacts = []


def test_review_id_is_carried_to_inference_task_record(monkeypatch):
    captured = []

    def fake_record_task(**kwargs):
        captured.append(kwargs)
        return {"task_id": kwargs["task_id"], "review_id": kwargs.get("review_id")}

    monkeypatch.setattr("inference.orchestrator.record_task", fake_record_task)
    raw, plan, rec = run_with_escalation(
        role="copilot",
        system="test",
        user="test",
        signals=signals_for_control(_Control(), role="copilot", evidence_chars=10),
        control_id="M1.2",
        task_id="LIVE-COP-TEST-M1_2",
        review_id="M1-2-REVIEW-123",
        invoke=lambda _system, _user: '{"relevant_evidence":[],"requirement_context":[],"evidence_gaps":[],"questions":[],"rationale_draft":""}',
    )

    assert captured
    assert captured[-1]["task_id"] == "LIVE-COP-TEST-M1_2"
    assert captured[-1]["review_id"] == "M1-2-REVIEW-123"
    assert rec["review_id"] == "M1-2-REVIEW-123"


def test_assessor_and_copilot_task_records_share_review_id(monkeypatch, tmp_path):
    import core.cycle as cycle

    monkeypatch.setattr(cycle, "_control", lambda control_id, framework: _Control())
    monkeypatch.setattr(cycle.events, "state", lambda cid: {"cycle_id": cid, "control_id": "M1.2", "framework": "MAS", "evidence": {"text": "e"}})
    monkeypatch.setattr(cycle, "check_bundle_unchanged", lambda _cid: None)
    monkeypatch.setattr(cycle, "assert_contract_executable", lambda *_: None)
    monkeypatch.setattr(cycle.llm, "model_for", lambda _role: __import__('contextlib').nullcontext("llama3.2"))
    monkeypatch.setattr(cycle.llm, "observe", lambda *args, **kwargs: __import__('contextlib').nullcontext({}))

    captured = []
    monkeypatch.setattr("pipeline.propose", lambda *args, **kwargs: captured.append(kwargs) or {"status": "ok"})
    cycle.assess("REVIEW-123")

    assert captured[-1]["review_id"] == "REVIEW-123"
    assert captured[-1]["task_id"] == "ASSESS-REVIEW-123"
