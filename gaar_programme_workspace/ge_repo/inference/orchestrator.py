from __future__ import annotations

import os
import time
import uuid
from typing import Callable

from llm.client import model_for, observe
from llm.colibri import chat as call_colibri
from .policy import TaskSignals, InferencePlan, build_plan
from .telemetry import record_task


def _call_legacy_ollama(system: str, user: str) -> str:
    import assessor
    return assessor._ollama(system, user)


def _invoke_plan(plan: InferencePlan, system: str, user: str,
                 invoke: Callable[[str, str], str] | None) -> str:
    if plan.provider == "colibri":
        # The deterministic router owns inference depth. Colibri only receives the budget chosen
        # for this task/control plan; the transport adapter does not decide governance complexity.
        return call_colibri(system, user, model=plan.model, max_tokens=plan.num_predict)
    if plan.provider != "ollama":
        raise RuntimeError(f"unsupported inference provider '{plan.provider}'")
    return (invoke or _call_legacy_ollama)(system, user)


def _second_plan(signals: TaskSignals, first: InferencePlan) -> InferencePlan | None:
    """Build the governed retry/escalation plan with fallback policy actually enabled.

    The previous implementation built the second plan before setting `WB_INFERENCE_FALLBACK`,
    which meant a configured fallback provider/model was never visible to that plan. This helper
    makes the ordering explicit and keeps the environment restoration local to planning.
    """
    if first.max_attempts <= 1:
        return None
    if first.tier == "critical" and not signals.role.startswith("challenge"):
        return None
    old = os.environ.get("WB_INFERENCE_FALLBACK")
    if signals.role.startswith("challenge"):
        os.environ["WB_INFERENCE_FALLBACK"] = "1"
    try:
        second_signals = TaskSignals(**{**signals.__dict__, "prior_failures": signals.prior_failures + 1})
        second = build_plan(second_signals)
    finally:
        if old is None:
            os.environ.pop("WB_INFERENCE_FALLBACK", None)
        else:
            os.environ["WB_INFERENCE_FALLBACK"] = old
    if second.provider != first.provider or second.model != first.model or second.tier != first.tier:
        return second
    return None


def run_with_escalation(*, role: str, system: str, user: str,
                        signals: TaskSignals,
                        validate: Callable[[str], tuple[bool, str]] | None = None,
                        control_id: str = "", task_id: str = "",
                        invoke: Callable[[str, str], str] | None = None,
                        review_id: str | None = None) -> tuple[str, InferencePlan, dict]:
    """Run one inference task, re-running once at a stronger/fallback plan when needed.

    Provider choice is part of the plan and is recorded alongside the model. Colibri is therefore
    a real provider route, not a second UI button or an untracked side call.
    """
    task_id = task_id or f"INF-{uuid.uuid4().hex[:12]}"
    first = build_plan(signals)
    second = _second_plan(signals, first)
    plans = [first] + ([second] if second else [])
    calls = 0
    failures = 0
    escalated = False
    started = time.monotonic()
    last_error = ""
    raw = ""

    for idx, plan in enumerate(plans):
        if idx > 0:
            escalated = True
        try:
            old_fallback = os.environ.get("WB_INFERENCE_FALLBACK")
            if idx > 0 and role.startswith("challenge"):
                os.environ["WB_INFERENCE_FALLBACK"] = "1"
            try:
                if plan.provider == "ollama":
                    with model_for(role):
                        import assessor
                        saved = assessor.OLLAMA_MODEL
                        assessor.OLLAMA_MODEL = plan.model
                        try:
                            with observe(role, cycle_id=task_id, control_id=control_id,
                                          model=plan.model, provider=plan.provider):
                                raw = _invoke_plan(plan, system, user, invoke)
                        finally:
                            assessor.OLLAMA_MODEL = saved
                else:
                    with observe(role, cycle_id=task_id, control_id=control_id,
                                 model=plan.model, provider=plan.provider):
                        raw = _invoke_plan(plan, system, user, invoke)
            finally:
                if old_fallback is None:
                    os.environ.pop("WB_INFERENCE_FALLBACK", None)
                else:
                    os.environ["WB_INFERENCE_FALLBACK"] = old_fallback
            calls += 1
        except Exception as exc:
            calls += 1
            failures += 1
            last_error = f"{type(exc).__name__}: {exc}"
            if idx == len(plans) - 1:
                elapsed = round((time.monotonic() - started) * 1000)
                record_task(task_id=task_id, role=role, control_id=control_id, plan=plan,
                            calls=calls, escalated=escalated, validation_failures=failures,
                            completed=False, elapsed_ms=elapsed, extra={"error": last_error},
                            review_id=review_id)
                raise
            continue

        if validate is None:
            elapsed = round((time.monotonic() - started) * 1000)
            rec = record_task(task_id=task_id, role=role, control_id=control_id, plan=plan,
                              calls=calls, escalated=escalated, validation_failures=failures,
                              completed=True, elapsed_ms=elapsed, review_id=review_id)
            return raw, plan, rec

        ok, reason = validate(raw)
        if ok:
            elapsed = round((time.monotonic() - started) * 1000)
            rec = record_task(task_id=task_id, role=role, control_id=control_id, plan=plan,
                              calls=calls, escalated=escalated, validation_failures=failures,
                              completed=True, elapsed_ms=elapsed, review_id=review_id)
            return raw, plan, rec
        failures += 1
        last_error = reason

    elapsed = round((time.monotonic() - started) * 1000)
    record_task(task_id=task_id, role=role, control_id=control_id, plan=plans[-1],
                calls=calls, escalated=escalated, validation_failures=failures,
                completed=False, elapsed_ms=elapsed, extra={"error": last_error},
                review_id=review_id)
    raise RuntimeError(last_error or "inference quality gate failed")
