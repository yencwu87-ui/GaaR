from __future__ import annotations

from ..schemas import ChallengeAuditInput, ChallengeAuditOutput


def run(value: ChallengeAuditInput | dict) -> ChallengeAuditOutput:
    inp = value if isinstance(value, ChallengeAuditInput) else ChallengeAuditInput.model_validate(value)
    env = inp.challenge_envelope or {}
    rows = [r for r in (env.get("challenges") or []) if isinstance(r, dict)]
    blocked = str(env.get("validation_status") or "").lower() == "blocked"
    strong = 0
    reasons: list[str] = []
    for row in rows:
        strength = str(row.get("challenge_strength") or row.get("strength") or "weak").lower()
        status = str(row.get("status") or "open").lower()
        resolution = str(row.get("resolution") or "").lower()
        resolved = status == "resolved" or resolution in {"accepted", "accept", "rejected", "reject", "escalate"}
        if strength == "strong" and not resolved:
            strong += 1
    if blocked:
        action = "REQUIRE_HUMAN"
        reasons.append("latest challenger output failed governed admission")
    elif strong:
        action = "REQUIRE_HUMAN"
        reasons.append(f"{strong} unresolved strong challenge(s)")
    elif rows:
        action = "ESCALATE_TO_COPILOT"
        reasons.append("admitted challenge(s) should be explained to the reviewer")
    else:
        action = "NONE"
        reasons.append("challenger ran without an admitted challenge")
    return ChallengeAuditOutput(
        admitted_count=len(rows), strong_unresolved_count=strong, blocked=blocked,
        recommended_action=action, reasons=reasons,
    )
