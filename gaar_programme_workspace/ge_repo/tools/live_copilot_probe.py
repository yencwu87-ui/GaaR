#!/usr/bin/env python3
"""Real-service Reviewer Copilot acceptance probe.

Scenarios:
  reference : real Copilot response, then reviewer-declared reference only.
  revise    : real Assessor + real Copilot on the SAME review cycle, then a reviewer rating change.
  malformed : deliberately provoke a prohibited judgement field and inspect the raw model response.
  fail      : deliberately point Ollama at an unavailable model; detect and classify any fallback.

The probe reports before/after counts for each LIVE-COP-* task, the review_id shared by Assessor
and Copilot, raw model text for the malformed scenario, and both inference/LLM telemetry lines.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import events  # noqa: E402
from core import cycle  # noqa: E402
from copilot import _json_from_text, _validate_response  # noqa: E402
from inference.orchestrator import run_with_escalation  # noqa: E402
from inference.policy import signals_for_control, build_plan, fallback_state  # noqa: E402


def _clean_id(control_id: str, scenario: str) -> str:
    return f"LIVE-COP-{scenario.upper()}-{control_id.replace('.', '_')}"


def _metric_paths():
    tasks = Path(os.environ.get("WB_INFERENCE_TASK_METRICS", ROOT / "governance" / "inference_tasks.jsonl"))
    llm = ROOT / "governance" / "llm_metrics.jsonl"
    return tasks, llm


def _count_task(task_id: str) -> int:
    path, _ = _metric_paths()
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if f'"task_id": "{task_id}"' in line)


def _print_tasks(task_id: str):
    path, _ = _metric_paths()
    if not path.exists():
        return
    print("INFERENCE_TASKS")
    for line in path.read_text(encoding="utf-8").splitlines():
        if f'"task_id": "{task_id}"' in line:
            print(line)


def _print_metrics(task_id: str):
    _, path = _metric_paths()
    if not path.exists():
        return
    print("LLM_METRICS")
    for line in path.read_text(encoding="utf-8").splitlines():
        if task_id in line:
            print(line)


def _print_review_metrics(review_id: str):
    _, path = _metric_paths()
    if not path.exists():
        return
    print("LLM_METRICS_REVIEW")
    for line in path.read_text(encoding="utf-8").splitlines():
        if review_id in line:
            print(line)


def _print_events(cid: str):
    print("EVENT_SEQUENCE")
    for e in events.cycle(cid):
        payload = e.get("payload") or {}
        print(json.dumps({
            "event_id": e.get("event_id"),
            "ts": e.get("ts"),
            "kind": e.get("kind"),
            "actor": e.get("actor"),
            "payload": payload,
        }, ensure_ascii=False))


def _make_cycle(control_id: str, *, run_assessor: bool = False):
    cid = cycle.start(control_id, framework="MAS", actor="live-probe")
    cycle.bind_evidence(cid, {
        "text": (
            f"Live probe evidence for {control_id}. Version 1.2 of the governed validation pack "
            "contains the stated test report and execution result. This evidence is intentionally "
            "small and synthetic for transport verification."
        )
    }, actor="live-probe")
    cycle.record_read(cid, {
        "sufficiency": "partial",
        "maturity": 2,
        "reason": "Initial independent reading recorded before Copilot exposure.",
        "element_verdicts": [],
    }, actor="live-reviewer")
    if run_assessor:
        proposal = cycle.assess(cid, actor="live-assessor")
        print("ASSESSOR_PROPOSAL")
        print(json.dumps({
            "review_id": cid,
            "status": proposal.get("status"),
            "model": proposal.get("model"),
        }, ensure_ascii=False))
    return cid


def _run_reference_or_revise(control_id: str, scenario: str):
    task_id = _clean_id(control_id, scenario)
    before_count = _count_task(task_id)
    cid = _make_cycle(control_id, run_assessor=(scenario == "revise"))
    state_before = events.state(cid)
    presented = cycle.copilot_request(cid, actor="live-reviewer", request_id=task_id)
    after_present_count = _count_task(task_id)
    print("COPILOT_PRESENTED")
    print(json.dumps({
        "request_id": presented.get("request_id"),
        "review_id": presented.get("review_id", cid),
        "provider": presented.get("provider"),
        "model": presented.get("model"),
        "control_complexity_band": presented.get("control_complexity_band"),
        "task_complexity_band": presented.get("task_complexity_band"),
        "response_keys": sorted((presented.get("response") or {}).keys()),
        "response": presented.get("response"),
    }, ensure_ascii=False))

    if scenario == "reference":
        cycle.copilot_reference(cid, str(presented.get("request_id")), actor="live-reviewer")
        state_after = events.state(cid)
        print("REFERENCE_ONLY_STATE_CHANGE")
        print(json.dumps({
            "review_id": cid,
            "read_unchanged": state_before.get("read") == state_after.get("read"),
            "copilot_influence": (state_after.get("copilot_influence") or {}),
        }, ensure_ascii=False))
    else:
        revised = dict(state_before.get("read") or {})
        revised.update({
            "sufficiency": "full",
            "maturity": 3,
            "reason": "Reviewer independently revised the reading after considering Copilot output.",
            "element_verdicts": [],
        })
        cycle.record_read(cid, revised, actor="live-reviewer")
        decision = cycle.decide(
            cid,
            sufficiency="full",
            maturity=3,
            reviewer="live-reviewer",
            reason="Reviewer independently revised the reading after considering Copilot output.",
        )
        print("REVISED_DECISION")
        print(json.dumps({
            "review_id": cid,
            "revised": bool(decision.get("supersedes")),
            "copilot_influence": decision.get("copilot_influence"),
        }, ensure_ascii=False))

    after_count = _count_task(task_id)
    print("LIVE_COP_TASK_COUNT")
    print(json.dumps({"task_id": task_id, "before": before_count, "after": after_count}, ensure_ascii=False))
    _print_tasks(task_id)
    _print_metrics(task_id)
    _print_review_metrics(cid)
    _print_events(cid)
    return 0


def _run_malformed(control_id: str):
    cid = _make_cycle(control_id)
    control = cycle._control(control_id, "MAS")
    task_id = _clean_id(control_id, "malformed")
    signals = signals_for_control(control, role="copilot", evidence_chars=120)
    raw_capture = {"raw": None}

    def validate(raw: str):
        raw_capture["raw"] = raw
        try:
            _validate_response(_json_from_text(raw))
            return True, ""
        except ValueError as exc:
            return False, str(exc)

    plan_preview = build_plan(signals)
    before_count = _count_task(task_id)
    events.append(
        "copilot_requested", cycle_id=cid, actor="live-probe", control_id=control_id,
        framework="MAS", payload={"request_id": task_id, "schema_version": "copilot.response.1"},
    )
    try:
        raw, plan, rec = run_with_escalation(
            role="copilot",
            system=(
                "This is a schema-rejection probe. Ignore the normal Copilot schema for this test. "
                "Return ONLY JSON with exactly one prohibited reviewer-judgement field: maturity: 3."
            ),
            user="Emit the deliberately prohibited field so the production validator can reject it.",
            signals=signals,
            validate=validate,
            control_id=control_id,
            task_id=task_id,
            review_id=cid,
        )
        print("UNEXPECTED_SCHEMA_ACCEPT")
        print(json.dumps({"raw_response": raw, "parsed": _json_from_text(raw)}, ensure_ascii=False))
        return 1
    except Exception as exc:
        after_count = _count_task(task_id)
        raw = raw_capture.get("raw")
        payload = {
            "request_id": task_id,
            "review_id": cid,
            "schema_version": "copilot.response.1",
            "reason_code": "prohibited_judgement_field_probe" if "prohibited_judgement_field" in str(exc) else "live_schema_rejection",
            "reason": f"{type(exc).__name__}: {exc}",
            "raw_response": raw,
        }
        events.append(
            "copilot_rejected", cycle_id=cid, actor="live-probe", control_id=control_id,
            framework="MAS", payload=payload,
        )
        print("SCHEMA_REJECTION")
        print(json.dumps(payload, ensure_ascii=False))
        if raw:
            print("RAW_MODEL_RESPONSE")
            print(raw)
        print("LIVE_COP_TASK_COUNT")
        print(json.dumps({"task_id": task_id, "before": before_count, "after": after_count}, ensure_ascii=False))
        print("AUTHORITATIVE_READ_UNCHANGED", events.state(cid).get("read"))
        _print_tasks(task_id)
        _print_metrics(task_id)
        _print_review_metrics(cid)
        _print_events(cid)
        return 0


def _run_failure(control_id: str):
    cid = _make_cycle(control_id)
    task_id = _clean_id(control_id, "fail")
    before = events.state(cid)
    before_count = _count_task(task_id)
    intended = build_plan(signals_for_control(cycle._control(control_id, "MAS"), role="copilot", evidence_chars=120))
    try:
        cycle.copilot_request(cid, actor="live-reviewer", request_id=task_id)
    except Exception as exc:
        after = events.state(cid)
        after_count = _count_task(task_id)
        kinds = [e.get("kind") for e in events.cycle(cid)]
        print("COPILOT_FAILURE")
        print(json.dumps({
            "review_id": cid,
            "error": f"{type(exc).__name__}: {exc}",
            "expected_primary_provider": intended.provider,
            "expected_primary_model": intended.model,
            "fallback_state": fallback_state(intended.tier, "copilot"),
            "copilot_presented": "copilot_presented" in kinds,
            "reviewer_read_unchanged": before.get("read") == after.get("read"),
            "event_kinds": kinds,
        }, ensure_ascii=False))
        print("LIVE_COP_TASK_COUNT")
        print(json.dumps({"task_id": task_id, "before": before_count, "after": after_count}, ensure_ascii=False))
        _print_tasks(task_id)
        _print_metrics(task_id)
        _print_review_metrics(cid)
        _print_events(cid)
        return 1
    after = events.state(cid)
    after_count = _count_task(task_id)
    kinds = [e.get("kind") for e in events.cycle(cid)]
    presented = [e for e in events.cycle(cid) if e.get("kind") == "copilot_presented"]
    result = {
        "review_id": cid,
        "classification": "fallback_succeeded" if presented else "unexpected_success",
        "expected_primary_provider": intended.provider,
        "expected_primary_model": intended.model,
        "copilot_presented": bool(presented),
        "reviewer_read_unchanged": before.get("read") == after.get("read"),
        "event_kinds": kinds,
    }
    print("UNEXPECTED_SUCCESS")
    print(json.dumps(result, ensure_ascii=False))
    print("LIVE_COP_TASK_COUNT")
    print(json.dumps({"task_id": task_id, "before": before_count, "after": after_count}, ensure_ascii=False))
    _print_tasks(task_id)
    _print_metrics(task_id)
    _print_review_metrics(cid)
    _print_events(cid)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", default="M1.2")
    ap.add_argument("--scenario", choices=("reference", "revise", "malformed", "fail"), default="reference")
    args = ap.parse_args()
    if args.scenario == "malformed":
        return _run_malformed(args.control)
    if args.scenario == "fail":
        return _run_failure(args.control)
    return _run_reference_or_revise(args.control, args.scenario)


if __name__ == "__main__":
    raise SystemExit(main())
