"""Read-only Operations / GaaR state dashboard.

This module is deliberately a projection over durable ledgers. It does not make governance
judgements, mutate results, or recompute evaluation metrics. The renderer is thin; snapshot()
contains the testable data projection.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import os
import statistics
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows[-limit:] if limit else rows


def _percentile(values: list[int | float], pct: float) -> int | None:
    xs = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not xs:
        return None
    idx = min(len(xs) - 1, max(0, round((len(xs) - 1) * pct)))
    return int(round(xs[idx]))


def _integrity_projection() -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}

    try:
        from governance.result_store import ResultStore
        results = ResultStore().read()
        checks["result_store"] = {"ok": True, "records": len(results), "error": ""}
    except Exception as exc:
        results = []
        checks["result_store"] = {"ok": False, "records": 0, "error": f"{type(exc).__name__}: {exc}"}

    try:
        from governance.result_contract import ResultStateLog
        state_events = ResultStateLog().read()
        checks["state_log"] = {"ok": True, "records": len(state_events), "error": ""}
    except Exception as exc:
        state_events = []
        checks["state_log"] = {"ok": False, "records": 0, "error": f"{type(exc).__name__}: {exc}"}

    try:
        from governance.change_runtime import ChangeImpactStore
        change_rows = ChangeImpactStore().read()
        checks["change_store"] = {"ok": True, "records": len(change_rows), "error": ""}
    except Exception as exc:
        change_rows = []
        checks["change_store"] = {"ok": False, "records": 0, "error": f"{type(exc).__name__}: {exc}"}

    try:
        from governance.reassessment import ReassessmentCaseStore
        reassessment_rows = ReassessmentCaseStore().read()
        checks["reassessment_store"] = {"ok": True, "records": len(reassessment_rows), "error": ""}
    except Exception as exc:
        reassessment_rows = []
        checks["reassessment_store"] = {"ok": False, "records": 0, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "checks": checks,
        "results": results,
        "state_events": state_events,
        "change_rows": change_rows,
        "reassessment_rows": reassessment_rows,
    }


def snapshot(*, task_limit: int = 500, call_limit: int = 1000) -> dict[str, Any]:
    """Project operator metrics from durable ledgers without mutating any source."""
    tasks = _read_jsonl(GOV / "inference_tasks.jsonl", limit=task_limit)
    calls = _read_jsonl(GOV / "llm_metrics.jsonl", limit=call_limit)
    integ = _integrity_projection()

    completed = sum(1 for r in tasks if r.get("completed") is True)
    failed = sum(1 for r in tasks if r.get("completed") is False)
    escalated = sum(1 for r in tasks if r.get("escalated") is True)
    providers = Counter(str(r.get("provider") or "unknown") for r in tasks)
    tiers = Counter(str(r.get("tier") or "unknown") for r in tasks)
    roles = Counter(str(r.get("role") or "unknown") for r in tasks)
    elapsed = [r.get("elapsed_ms") for r in tasks if isinstance(r.get("elapsed_ms"), (int, float))]
    budgets = [r.get("generation_budget") for r in tasks if isinstance(r.get("generation_budget"), int)]

    call_failed = sum(1 for r in calls if r.get("ok") is False)
    call_providers = Counter(str(r.get("provider") or "unknown") for r in calls)
    call_ms = [r.get("ms") for r in calls if isinstance(r.get("ms"), (int, float))]

    state_counts: Counter[str] = Counter()
    latest_state: dict[str, str] = {}
    for event in integ["state_events"]:
        rid = str(getattr(event, "result_id", ""))
        state = getattr(event, "to_state", None)
        state_s = getattr(state, "value", str(state or ""))
        if rid and state_s:
            latest_state[rid] = state_s
    state_counts.update(latest_state.values())

    reassessment_status = Counter(getattr(row, "status", "UNKNOWN") for row in integ["reassessment_rows"])
    change_types = Counter(str(row.get("record_type") or "unknown") for row in integ["change_rows"])

    return {
        "features": {
            "result_contract": os.environ.get("WB_GAAR_RESULT_ENABLE", "0") in {"1", "true", "yes", "on"},
            "change_intelligence": os.environ.get("WB_GAAR_CHANGE_INTELLIGENCE", "0") in {"1", "true", "yes", "on"},
            "reassessment": os.environ.get("WB_GAAR_REASSESSMENT_WORKFLOW", "0") in {"1", "true", "yes", "on"},
            "colibri": os.environ.get("WB_COLIBRI_ENABLED", "0") in {"1", "true", "yes", "on"},
        },
        "inference": {
            "tasks": len(tasks),
            "completed": completed,
            "failed": failed,
            "completion_rate": (completed / len(tasks)) if tasks else None,
            "escalated": escalated,
            "providers": dict(providers),
            "tiers": dict(tiers),
            "roles": dict(roles),
            "p50_ms": int(statistics.median(elapsed)) if elapsed else None,
            "p95_ms": _percentile(elapsed, .95),
            "budget_min": min(budgets) if budgets else None,
            "budget_median": int(statistics.median(budgets)) if budgets else None,
            "budget_max": max(budgets) if budgets else None,
            "recent": list(reversed(tasks[-30:])),
        },
        "calls": {
            "calls": len(calls),
            "failed": call_failed,
            "success_rate": ((len(calls) - call_failed) / len(calls)) if calls else None,
            "providers": dict(call_providers),
            "p50_ms": int(statistics.median(call_ms)) if call_ms else None,
            "p95_ms": _percentile(call_ms, .95),
        },
        "gaar": {
            "results": len(integ["results"]),
            "states": dict(state_counts),
            "reassessment_cases": len(integ["reassessment_rows"]),
            "reassessment_status": dict(reassessment_status),
            "change_records": len(integ["change_rows"]),
            "change_types": dict(change_types),
        },
        "integrity": integ["checks"],
    }


def render(theme: str = "light") -> None:
    import streamlit as st

    snap = snapshot()
    inf = snap["inference"]
    calls = snap["calls"]
    gaar = snap["gaar"]

    st.subheader("Operations & GaaR state")
    st.caption(
        "Read-only projection of durable ledgers: governance-result lifecycle, reassessment, "
        "inference routing and provider calls. This page does not recompute governance outcomes."
    )

    f = snap["features"]
    flags = [
        ("Result", f["result_contract"]),
        ("Change", f["change_intelligence"]),
        ("Reassessment", f["reassessment"]),
        ("Colibrì", f["colibri"]),
    ]
    st.markdown(" · ".join(f"**{name}: {'ON' if on else 'OFF'}**" for name, on in flags))

    a, b, c, d, e = st.columns(5)
    a.metric("Governance results", gaar["results"])
    b.metric("CURRENT", gaar["states"].get("CURRENT", 0))
    c.metric("Review required", gaar["states"].get("REVIEW_REQUIRED", 0))
    d.metric("Reassessing", gaar["states"].get("REASSESSING", 0))
    e.metric("Superseded", gaar["states"].get("SUPERSEDED", 0))

    st.markdown("#### Inference runtime")
    i1, i2, i3, i4, i5 = st.columns(5)
    i1.metric("Tasks", inf["tasks"])
    i2.metric("Completion", f"{inf['completion_rate']:.1%}" if inf["completion_rate"] is not None else "—")
    i3.metric("Escalated", inf["escalated"])
    i4.metric("P50 latency", f"{inf['p50_ms']} ms" if inf["p50_ms"] is not None else "—")
    i5.metric("P95 latency", f"{inf['p95_ms']} ms" if inf["p95_ms"] is not None else "—")

    left, right = st.columns(2)
    with left:
        st.markdown("**Routing mix**")
        rows = []
        for provider, count in sorted(inf["providers"].items()):
            rows.append({"Provider": provider, "Tasks": count})
        st.dataframe(rows, width="stretch", hide_index=True)
    with right:
        st.markdown("**Generation budget observed**")
        if inf["budget_min"] is None:
            st.caption("No budget telemetry recorded yet. New tasks record the router-selected budget.")
        else:
            b1, b2, b3 = st.columns(3)
            b1.metric("Min", inf["budget_min"])
            b2.metric("Median", inf["budget_median"])
            b3.metric("Max", inf["budget_max"])

    st.markdown("#### Provider calls")
    with st.expander("Live provider health", expanded=False):
        st.caption("Health checks are on-demand so opening the dashboard never blocks on a local model service.")
        if st.button("Check Ollama + Colibrì now", key="ops_provider_health"):
            health_rows = []
            try:
                import requests
                r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
                health_rows.append({"Provider": "Ollama", "Status": "OK" if r.ok else f"HTTP {r.status_code}", "Endpoint": "127.0.0.1:11434"})
            except Exception as exc:
                health_rows.append({"Provider": "Ollama", "Status": f"OFFLINE · {type(exc).__name__}", "Endpoint": "127.0.0.1:11434"})
            try:
                from llm.colibri import health as colibri_health
                h = colibri_health()
                health_rows.append({"Provider": "Colibrì", "Status": "OK" if h.get("ok") else f"OFFLINE · {h.get('error') or h.get('status_code') or 'unavailable'}", "Endpoint": h.get("url", "")})
            except Exception as exc:
                health_rows.append({"Provider": "Colibrì", "Status": f"OFFLINE · {type(exc).__name__}", "Endpoint": ""})
            st.dataframe(health_rows, width="stretch", hide_index=True)

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Calls", calls["calls"])
    p2.metric("Success", f"{calls['success_rate']:.1%}" if calls["success_rate"] is not None else "—")
    p3.metric("P50", f"{calls['p50_ms']} ms" if calls["p50_ms"] is not None else "—")
    p4.metric("P95", f"{calls['p95_ms']} ms" if calls["p95_ms"] is not None else "—")

    st.markdown("#### Ledger integrity")
    integrity_rows = []
    for name, row in snap["integrity"].items():
        integrity_rows.append({
            "Store": name.replace("_", " ").title(),
            "Integrity": "OK" if row["ok"] else "ERROR",
            "Records": row["records"],
            "Detail": row["error"] or "hash/chain validation passed",
        })
    st.dataframe(integrity_rows, width="stretch", hide_index=True)

    st.markdown("#### Reassessment & change activity")
    r1, r2 = st.columns(2)
    with r1:
        st.metric("Reassessment cases", gaar["reassessment_cases"])
        if gaar["reassessment_status"]:
            st.dataframe(
                [{"Status": k, "Cases": v} for k, v in sorted(gaar["reassessment_status"].items())],
                width="stretch", hide_index=True,
            )
    with r2:
        st.metric("Change / impact records", gaar["change_records"])
        if gaar["change_types"]:
            st.dataframe(
                [{"Type": k, "Records": v} for k, v in sorted(gaar["change_types"].items())],
                width="stretch", hide_index=True,
            )

    with st.expander("Recent inference tasks", expanded=False):
        rows = []
        for r in inf["recent"]:
            rows.append({
                "Time": str(r.get("ts", ""))[:19].replace("T", " "),
                "Role": r.get("role", ""),
                "Control": r.get("control_id", ""),
                "Tier": r.get("tier", ""),
                "Provider": r.get("provider", ""),
                "Model": r.get("model", ""),
                "Budget": r.get("generation_budget", "—"),
                "Elapsed ms": r.get("elapsed_ms", "—"),
                "Status": "complete" if r.get("completed") else "failed",
            })
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        else:
            st.info("No inference tasks recorded yet.")
