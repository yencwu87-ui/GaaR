"""WB-115 governed AI Auditor runtime.

The package exports are resolved lazily so read-only projections and WB-116 quality-gate
modules can depend on each other without import-time cycles.
"""
from __future__ import annotations

__all__ = ["ReviewConductor", "living_view", "enabled", "load_policy"]


def __getattr__(name: str):
    if name == "ReviewConductor":
        from .conductor import ReviewConductor
        return ReviewConductor
    if name == "living_view":
        from .living_view import living_view
        return living_view
    if name in {"enabled", "load_policy"}:
        from .policy import enabled, load_policy
        return {"enabled": enabled, "load_policy": load_policy}[name]
    raise AttributeError(name)
