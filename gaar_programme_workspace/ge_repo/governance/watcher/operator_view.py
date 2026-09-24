"""Plain-language Watcher status projection for non-specialist operators."""
from __future__ import annotations
from typing import Any, Iterable

_MEANING = {
    "UP_TO_DATE": ("Working", "No new items were observed in the bounded source on the last successful check."),
    "BASELINE_ESTABLISHED": ("Working", "The first successful source inventory was recorded."),
    "OK": ("Working", "The source responded successfully."),
    "UPDATES_AVAILABLE": ("Review needed", "New or changed listing items need human review."),
    "CHECK_OVERDUE": ("Attention", "The source has not completed a successful check within its expected interval."),
    "UNABLE_TO_CHECK": ("Blocked", "The source could not be checked; this is not an all-clear."),
    "DEGRADED": ("Blocked", "The source returned incomplete or invalid information."),
    "ERROR": ("Blocked", "The last source check failed."),
    "NOT_CONFIGURED": ("Not configured", "The source is intentionally disabled."),
    "NEVER_CHECKED": ("Ready to test", "The source is enabled but has no successful baseline yet."),
    "NOT_RUN": ("Ready to test", "No check has been recorded."),
}


def explain_status(status: str) -> dict[str, str]:
    raw = str(status or "NOT_RUN").upper()
    label, meaning = _MEANING.get(raw, ("Attention", "Inspect the technical detail before relying on this source."))
    return {"raw_status": raw, "plain_status": label, "meaning": meaning}


def source_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        explained = explain_status(str(row.get("status") or row.get("Update status") or ""))
        out.append({
            "Source": row.get("source_id") or row.get("Source") or "Unknown source",
            "Where": row.get("jurisdiction") or row.get("Jurisdiction") or "—",
            "Plain status": explained["plain_status"],
            "What it means": explained["meaning"],
            "Last checked": row.get("checked_at") or row.get("Last check") or row.get("Last checked") or "Never",
            "New items": len(row.get("new") or []) if isinstance(row.get("new"), list) else row.get("New snapshots", 0),
            "Technical status": explained["raw_status"],
        })
    return out


def summary(rows: Iterable[dict[str, Any]], pending_publications: int = 0) -> dict[str, Any]:
    projected = source_rows(rows)
    counts = {label: sum(r["Plain status"] == label for r in projected)
              for label in ("Working", "Review needed", "Attention", "Blocked", "Not configured", "Ready to test")}
    if pending_publications:
        action = f"Review {pending_publications} discovered publication(s)."
    elif counts["Blocked"]:
        action = f"Investigate {counts['Blocked']} blocked source(s); blocked never means up to date."
    elif counts["Ready to test"]:
        action = f"Run the first check for {counts['Ready to test']} enabled source(s)."
    elif counts["Working"]:
        action = "No publication review is waiting. Keep scheduled monitoring running."
    else:
        action = "Configure and validate at least one official source."
    return {"counts": counts, "pending_publications": pending_publications,
            "next_action": action, "rows": projected}
