from __future__ import annotations

from governance.result_contract import ResultStateLog
from governance.result_store import ResultStore
from ..schemas import ProvenanceAuditInput, ProvenanceAuditOutput


def run(value: ProvenanceAuditInput | dict, *, result_store: ResultStore | None = None,
        state_log: ResultStateLog | None = None) -> ProvenanceAuditOutput:
    inp = value if isinstance(value, ProvenanceAuditInput) else ProvenanceAuditInput.model_validate(value)
    store = result_store or ResultStore()
    log = state_log or ResultStateLog()
    failures: list[str] = []
    checks = {"result_present": False, "seal_valid": False, "state_present": False, "provenance_complete": False}
    try:
        result = store.get(inp.result_id)
    except Exception as exc:
        failures.append(f"result_store_invalid:{type(exc).__name__}:{exc}")
        return ProvenanceAuditOutput(valid=False, checks=checks, failures=failures)
    if result is None:
        failures.append("result_not_found")
        return ProvenanceAuditOutput(valid=False, checks=checks, failures=failures)
    checks["result_present"] = True
    try:
        # Pydantic validation on read already verifies content hash, Merkle root and Ed25519 seal.
        result.validate_internal_consistency()
        checks["seal_valid"] = True
    except Exception as exc:
        failures.append(f"seal_invalid:{type(exc).__name__}:{exc}")
    prov = result.provenance
    required = [prov.requirement_version_id, prov.evidence_set_id, prov.assessment_id,
                prov.challenge_set_id, prov.human_decision_id, prov.human_decider_id]
    checks["provenance_complete"] = all(bool(str(x).strip()) for x in required)
    if not checks["provenance_complete"]:
        failures.append("provenance_incomplete")
    try:
        checks["state_present"] = log.current_state(result.result_id) is not None
    except Exception as exc:
        failures.append(f"state_log_invalid:{type(exc).__name__}:{exc}")
    return ProvenanceAuditOutput(valid=all(checks.values()), checks=checks, failures=failures)
