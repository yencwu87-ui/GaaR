"""Ledger-derived GaaR/RaaS maturity status.

This module never upgrades a milestone from configuration or intent alone.  A milestone
is GREEN only when its durable acceptance artifact is present.  The UI and CLI use the
same projection so operators cannot receive a different maturity story from each surface.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = row.get("payload")
        rows.append({**row, **payload} if isinstance(payload, dict) else row)
    return rows


def _path(env: str, default: str) -> Path:
    return Path(os.environ.get(env) or ROOT / "governance" / default).expanduser().resolve()


@dataclass(frozen=True)
class Milestone:
    number: int
    name: str
    status: str
    evidence: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _latest_for(rows: list[dict[str, Any]], control_id: str) -> dict[str, Any] | None:
    return next((row for row in reversed(rows) if row.get("control_id") == control_id), None)


def evaluate(control_id: str = "M3.6", framework: str = "MAS") -> dict[str, Any]:
    acquisitions = _records(_path("WB_GAAR_SCOUT_ACQUISITION_STORE", "evidence_acquisitions.jsonl"))
    dossiers = _records(_path("WB_GAAR_DOSSIER_STORE", "evidence_dossiers.jsonl"))
    admissions = _records(_path("WB_GAAR_ADMISSION_STORE", "evidence_admissions.jsonl"))
    events = _records(_path("WB_EVENT_LOG", "events.jsonl"))
    gates = _records(_path("WB_GAAR_QUALITY_GATE_STORE", "quality_gate_events.jsonl"))
    results = _records(_path("WB_GAAR_RESULT_STORE", "result_store.jsonl"))
    states = _records(_path("WB_GAAR_RESULT_STATE_STORE", "result_state_events.jsonl"))
    inference = _records(_path("WB_INFERENCE_TASK_METRICS", "inference_tasks.jsonl"))
    replay = _records(_path("WB_GAAR_REPLAY_PROOF_STORE", "replay_proofs.jsonl"))

    acquisition = _latest_for(acquisitions, control_id)
    good_acquisition = bool(
        acquisition
        and acquisition.get("framework") == framework
        and acquisition.get("recommended_action") == "REVIEW_CANDIDATES"
        and (acquisition.get("preflight") or {}).get("evaluation_status") == "EVALUATED"
        and not acquisition.get("gaps")
    )

    dossier = _latest_for(dossiers, control_id)
    good_dossier = bool(
        dossier and dossier.get("framework") == framework
        and dossier.get("binding_status") == "PROPOSED_ONLY"
        and dossier.get("required_elements")
        and not dossier.get("gaps")
        and all(row.get("candidate_anchors") for row in dossier.get("required_elements") or [])
    )

    completed_admission = next((row for row in reversed(admissions)
        if row.get("dossier_id") == (dossier or {}).get("dossier_id")
        and row.get("cycle_evidence_bound") is True), None)
    admitted = bool(completed_admission)
    cycle_id = str((completed_admission or {}).get("cycle_id") or "")
    cycle_events = [row for row in events if row.get("cycle_id") == cycle_id] if cycle_id else []
    proposal = next((row for row in reversed(cycle_events) if row.get("kind") == "proposed"), None)
    challenge = next((row for row in reversed(cycle_events)
                      if row.get("kind") in {"independent_challenged", "challenged"}), None)
    decision = next((row for row in reversed(cycle_events) if row.get("kind") == "decided"), None)

    colibri = next((row for row in reversed(inference)
                    if row.get("control_id") == control_id and row.get("provider") == "colibri"), None)
    colibri_policy = next((row for row in reversed(inference)
                           if row.get("control_id") == control_id
                           and row.get("escalation_policy") == "governed-v1"), None)
    gate = next((row for row in reversed(gates)
                 if (not cycle_id or row.get("cycle_id") == cycle_id)
                 and row.get("status") == "FINALIZABLE"), None)
    # ResultStore wraps the immutable result under ``result``. Bind it back to this
    # control run through the governed evidence-set identity rather than mutable labels.
    admitted_evidence_set = str((completed_admission or {}).get("evidence_set_id") or "")
    result = next((row for row in reversed(results)
                   if admitted_evidence_set
                   and (row.get("result") or row).get("evidence_set_id") == admitted_evidence_set), None)
    result_payload = (result or {}).get("result") or (result or {})
    current = next((row for row in reversed(states)
                    if row.get("result_id") == result_payload.get("result_id")
                    and (row.get("to_state") == "CURRENT" or row.get("state") == "CURRENT")), None)
    replay_ok = next((row for row in reversed(replay)
                      if row.get("control_id") == control_id and row.get("status") == "PASS"), None)

    validation_path = ROOT / "WB137_VALIDATION.json"
    validation = {}
    if validation_path.exists():
        try:
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            validation = {}
    regression_ok = validation.get("overall_status") == "PASS"

    def item(number: int, name: str, ok: bool, evidence: str, action: str) -> Milestone:
        return Milestone(number, name, "GREEN" if ok else "NOT_PROVEN", evidence if ok else "No qualifying artifact", action)

    milestones = [
        item(1, "Control-aware evidence acquisition", good_acquisition,
             str((acquisition or {}).get("acquisition_id") or ""),
             "Run Scout with exact governed M3.6 elements and resolve every gap."),
        item(2, "Admission-ready evidence dossier", good_dossier,
             str((dossier or {}).get("dossier_id") or ""),
             "Assemble a dossier with explicit elements and candidate anchors."),
        item(3, "Governed evidence admission", admitted,
             str((completed_admission or {}).get("evidence_set_id") or ""),
             "Run admission preflight, review it, then explicitly admit into a fresh cycle."),
        item(4, "Assessment execution", bool(proposal),
             str((proposal or {}).get("event_id") or (proposal or {}).get("model") or ""),
             "Run the assessor on the admitted cycle."),
        item(5, "Independent challenge", bool(challenge),
             str((challenge or {}).get("event_id") or ""),
             "Run the independent challenge and resolve strong or blocked findings."),
        item(6, "Governed Colibri routing proof", bool(colibri or colibri_policy),
             str((colibri or colibri_policy or {}).get("task_id") or "policy recorded"),
             "Record Colibri escalation or an explicit governed not-required decision."),
        item(7, "Final Quality Gate", bool(gate),
             str((gate or {}).get("gate_id") or ""),
             "Obtain FINALIZABLE after evidence, reasoning, governance and provenance checks."),
        item(8, "Human governance decision", bool(decision),
             str((decision or {}).get("human_decision_id") or (decision or {}).get("event_id") or ""),
             "A named human approves, investigates or rejects at the final checkpoint."),
        item(9, "Signed CURRENT GovernanceResult", bool(result and current),
             str(result_payload.get("result_id") or ""),
             "Seal the result and verify the FINALIZED to CURRENT state transition."),
        item(10, "Deterministic replay proof", bool(replay_ok),
             str((replay_ok or {}).get("proof_id") or ""),
             "Replay the same immutable inputs and compare result identity and hashes."),
        item(11, "Regression and release gate", regression_ok,
             str(validation_path.name if regression_ok else ""),
             "Run the full supported suite and record a machine-readable PASS report."),
    ]
    green = sum(row.status == "GREEN" for row in milestones)
    return {
        "control_id": control_id,
        "framework": framework,
        "green": green,
        "total": len(milestones),
        "percent": round(100 * green / len(milestones)),
        "status": "FULLY_PROVEN" if green == len(milestones) else "IN_PROGRESS",
        "milestones": [row.to_dict() for row in milestones],
    }
