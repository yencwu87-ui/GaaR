from __future__ import annotations

from collections import defaultdict
from typing import Any

import events
from governance.result_contract import ResultStateLog, ValidityState
from governance.result_store import ResultStore
from governance.quality_gate import QualityGateLog


def _result_to_cycle_map() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in events.decided():
        rid = str(row.get("governance_result_id") or "").strip()
        if not rid:
            continue
        out[rid] = {
            "cycle_id": str(row.get("cycle_id") or ""),
            "control_id": str(row.get("control_id") or ""),
            "framework": str(row.get("framework") or ""),
        }
    return out


def living_view(control_id: str, framework: str | None = None, *, result_store: ResultStore | None = None,
                state_log: ResultStateLog | None = None) -> dict[str, Any]:
    """Read-only living projection over immutable results + append-only state events.

    This function never writes. It intentionally joins GovernanceResults back to their source cycle
    using the authoritative decided event that recorded the result_id.
    """
    store = result_store or ResultStore()
    states = state_log or ResultStateLog()
    gates = QualityGateLog()
    mapping = _result_to_cycle_map()
    candidates = []
    for result in store.read():
        meta = mapping.get(result.result_id, {})
        if meta.get("control_id") != control_id:
            continue
        if framework and meta.get("framework") and meta.get("framework") != framework:
            continue
        state = states.current_state(result.result_id)
        candidates.append((result, meta, state))
    candidates.sort(key=lambda item: (item[0].result_version, item[0].created_at))
    current = next((x for x in reversed(candidates) if x[2] == ValidityState.CURRENT), None)
    latest = current or (candidates[-1] if candidates else None)
    history = []
    for result, meta, state in candidates:
        history.append({
            "result_id": result.result_id,
            "result_version": result.result_version,
            "state": state.value if state else "UNKNOWN",
            "decision": result.decision.value,
            "created_at": result.created_at,
            "requirement_version_id": result.requirement_version_id,
            "evidence_set_id": result.evidence_set_id,
            "parent_result_id": result.parent_result_id,
            "supersedes_result_id": result.supersedes_result_id,
            "cycle_id": meta.get("cycle_id", ""),
            "quality_gate": (gates.latest_for_result(result.result_id).status.value
                             if gates.latest_for_result(result.result_id) else "NOT_RUN"),
        })
    if not latest:
        return {
            "control_id": control_id, "framework": framework or "", "current_result": None,
            "current_state": "NO_RESULT", "human_attention_required": False,
            "change_state": "NONE", "history": [],
        }
    result, meta, state = latest
    gate = gates.latest_for_result(result.result_id)
    attention = state in {ValidityState.REVIEW_REQUIRED, ValidityState.REASSESSING} or (gate is not None and gate.status.value == "BLOCKED")
    return {
        "control_id": control_id,
        "framework": meta.get("framework") or framework or "",
        "current_result": result.result_id,
        "current_state": state.value if state else "UNKNOWN",
        "decision": result.decision.value,
        "requirement_version_id": result.requirement_version_id,
        "evidence_set_id": result.evidence_set_id,
        "result_version": result.result_version,
        "human_attention_required": bool(attention),
        "change_state": state.value if state in {ValidityState.REVIEW_REQUIRED, ValidityState.REASSESSING} else "NONE",
        "lineage_depth": len(history),
        "quality_gate": gate.status.value if gate else "NOT_RUN",
        "quality_gate_blockers": list(gate.blockers) if gate else [],
        "history": history,
    }


def all_living_views(*, result_store: ResultStore | None = None, state_log: ResultStateLog | None = None) -> list[dict[str, Any]]:
    mapping = _result_to_cycle_map()
    keys = sorted({(m.get("control_id", ""), m.get("framework", "")) for m in mapping.values() if m.get("control_id")})
    return [living_view(cid, fw, result_store=result_store, state_log=state_log) for cid, fw in keys]
