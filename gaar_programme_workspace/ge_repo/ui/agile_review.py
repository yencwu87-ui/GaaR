from __future__ import annotations

from collections import defaultdict
from typing import Iterable


KANBAN_ORDER = ["BACKLOG", "AUTOMATION", "HUMAN READ", "VERIFY", "EXCEPTION", "DECISION", "DONE"]


def kanban_stage(row: dict) -> str:
    if row.get("next_action", {}).get("kind") == "complete":
        return "DONE"
    if not row.get("has_evidence"):
        return "BACKLOG"
    if not row.get("has_read"):
        return "HUMAN READ"
    if not row.get("has_proposal") or not row.get("has_compare"):
        return "AUTOMATION"
    ch = row.get("challenge") or {}
    if ch.get("blocked") or ch.get("unresolved_strong"):
        return "EXCEPTION"
    if ch.get("unresolved"):
        return "VERIFY"
    return "DECISION"


def framework_groups(rows: Iterable[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("library") or row.get("framework") or "Other")].append(row)
    return dict(grouped)


def kanban_board(rows: Iterable[dict]) -> dict[str, list[dict]]:
    board = {k: [] for k in KANBAN_ORDER}
    for row in rows:
        board[kanban_stage(row)].append(row)
    return board


def standup_summary(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    board = kanban_board(rows)
    by_framework = framework_groups(rows)
    strong = sum(int((r.get("challenge") or {}).get("unresolved_strong") or 0) for r in rows)
    blocked = sum(1 for r in rows if (r.get("challenge") or {}).get("blocked"))
    return {
        "in_scope": len(rows),
        "done": len(board["DONE"]),
        "human_read": len(board["HUMAN READ"]),
        "exceptions": len(board["EXCEPTION"]),
        "decisions": len(board["DECISION"]),
        "strong_challenges": strong,
        "blocked_challenge_runs": blocked,
        "frameworks": {k: len(v) for k, v in sorted(by_framework.items())},
        "top_attention": [r for r in rows if kanban_stage(r) in {"EXCEPTION", "DECISION", "HUMAN READ"}][:12],
    }
