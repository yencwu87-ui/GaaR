"""Inference-engineering control plane.

The inference layer decides how much model compute to spend and when to escalate. It never
creates or records governance decisions by itself.
"""
from .policy import InferencePlan, TaskSignals, build_plan, control_complexity, signals_for_control
from .orchestrator import run_with_escalation

__all__ = ["InferencePlan", "TaskSignals", "build_plan", "control_complexity", "signals_for_control", "run_with_escalation"]
