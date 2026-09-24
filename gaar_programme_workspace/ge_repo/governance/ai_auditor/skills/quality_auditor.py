from __future__ import annotations

import events
from review_queue import challenge_counts
from ..schemas import QualityAuditInput, QualityAuditOutput


def run(value: QualityAuditInput | dict) -> QualityAuditOutput:
    inp = value if isinstance(value, QualityAuditInput) else QualityAuditInput.model_validate(value)
    state = events.state(inp.cycle_id)
    if not state:
        return QualityAuditOutput(ready=False, dimensions={"evidence": False, "reasoning": False, "governance": False, "provenance": False}, blockers=["cycle_not_found"])
    ch = challenge_counts(state)
    evidence_ok = bool((state.get("evidence") or {}).get("text") or (state.get("evidence") or {}).get("chunks"))
    from governance.routine_waiver import applied_waiver, eligibility
    valid_waiver = bool(state.get("blind_read_waiver") and applied_waiver(state)
                        and not eligibility(state, require_challenge=True))
    reasoning_ok = bool(state.get("proposal")) and (bool(state.get("diff")) or valid_waiver)
    governance_ok = not ch["blocked"] and ch["unresolved_strong"] == 0
    decision = state.get("decision")
    provenance_ok = bool(state.get("cycle_id")) and bool(state.get("control_id"))
    if inp.require_human_decision:
        provenance_ok = provenance_ok and bool(decision)
    blockers = []
    if not evidence_ok: blockers.append("evidence_missing")
    if not reasoning_ok: blockers.append("reasoning_incomplete")
    if ch["blocked"]: blockers.append("challenge_validation_blocked")
    if ch["unresolved_strong"]: blockers.append("strong_challenge_unresolved")
    if inp.require_human_decision and not decision: blockers.append("human_decision_missing")
    dims = {"evidence": evidence_ok, "reasoning": reasoning_ok, "governance": governance_ok, "provenance": provenance_ok}
    from governance.investigation.bridge import required, cycle_gate
    if required(state):
        investigation = cycle_gate(state)
        dims["investigation"] = investigation["assessment_finalizable"]
        blockers.extend(investigation.get("blockers", []))
    return QualityAuditOutput(ready=all(dims.values()), dimensions=dims, blockers=blockers)
