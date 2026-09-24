from __future__ import annotations

import events
from collections import Counter


def decision_metrics() -> dict:
    rows = events.decided()
    framework = Counter(str(r.get("framework") or "Unknown") for r in rows)
    sufficiency = Counter(str((r.get("decision") or {}).get("sufficiency") or "unknown") for r in rows)
    return {"total": len(rows), "by_framework": dict(framework), "by_sufficiency": dict(sufficiency)}


def recent_decisions(limit: int = 20) -> list[dict]:
    out = []
    for r in events.decided()[-limit:][::-1]:
        d = r.get("decision") or {}
        out.append({
            "framework": r.get("framework"), "control_id": r.get("control_id"), "cycle_id": r.get("cycle_id"),
            "sufficiency": d.get("sufficiency"), "maturity": d.get("maturity"), "reviewer": r.get("decided_by"),
            "at": r.get("decision_recorded_at"), "governance_result_id": r.get("governance_result_id"),
        })
    return out
