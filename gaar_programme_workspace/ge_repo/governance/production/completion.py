"""Deterministic-first completion (Phase 0 → pilot MVP).

Phase 0 showed the model stages are the unreliable part (J3, J7) and the
deterministic procedures plus D8 reconciliation are the reliable part. Before
this, one rejected model answer left the whole run at ACTION_REQUIRED even
though the truth was already recorded.

When a model stage fails and `deterministic_completion` is enabled, the run
finishes on what is trustworthy:

* No model stage is fabricated. A missing explain, plan, dependency review or
  challenge stays missing; nothing is signed with the assessor's or
  challenger's key on their behalf.
* The failure is recorded: which stage, the exact error, and which model stages
  did complete, as an executor-signed journal event bound to the current head.
* D8 must exist. If examine itself was rejected, reconciliation runs directly on
  the admitted evidence against the signed manifest, with the assessor recorded
  as MODEL_UNAVAILABLE.
* The verdict is derived from the reconciled statuses alone and can only be
  ADVERSE or INCONCLUSIVE. A record without a completed model assessment can
  establish that something is wrong; it cannot establish that everything is
  right, so it never yields PASS.
* The result is decision support for a human attestation, never a governance
  result, and never authorises deployment.

Pressing Run again returns the same completed record. It does not re-ask the
model. Retrying a model stage needs a fresh investigation revision.
"""
from __future__ import annotations

from . import reconciliation

MODEL_STAGES = {"examine", "explain", "plan", "dependency_review", "challenge"}
UNAVAILABLE = "model_stage_unavailable"
REPORT_KEY = "deterministic_run_report"


def models_disabled(config: dict) -> bool:
    """Pilot setting: no model is called at all; the record is deterministic from the start."""
    return config.get("model_stages") == "disabled"


def enabled(config: dict) -> bool:
    return config.get("deterministic_completion") is True or models_disabled(config)


def deterministic_verdict(obligations: list[dict]) -> str:
    statuses = {o["governed_status"] for o in obligations}
    if "CONTRADICTED" in statuses:
        return "ADVERSE"
    if statuses == {"NO_EXCEPTIONS_FOR_PERIOD"}:
        return "NO_EXCEPTIONS_FOUND"          # still never PASS: see docs/design/coverage_reporting.md
    return "INCONCLUSIVE"


def complete(config, iid, engine, journal, signers, stage, error, evidence=None, disabled=False) -> dict:
    rows, values = engine.snapshot(iid)
    if not journal.latest(reconciliation.EVENT):
        reconciliation.reconcile(config, iid, engine, journal, signers["executor"], evidence=evidence)
    rows, values = engine.snapshot(iid)
    journal.append(UNAVAILABLE, UNAVAILABLE, {
        "investigation_id": iid, "stage": stage, "error": error[:2000], "disabled_by_configuration": disabled,
        "completed_model_stages": [s for s in ("examine", "explain", "plan", "challenge") if s in values],
        "dependency_review_recorded": journal.latest("dependency_review") is not None,
        "investigation_head": rows[-1]["record_hash"],
    }, signers["executor"], "executor")
    return report(iid, engine, journal, signers)


def report(iid, engine, journal, signers) -> dict:
    existing = next((e for e in journal.read() if e["event_key"] == REPORT_KEY), None)
    if existing:
        return existing["payload"]
    rows, values = engine.snapshot(iid)
    rec_event = journal.latest(reconciliation.EVENT)
    unavailable = journal.latest(UNAVAILABLE)
    obligations = rec_event["payload"]["obligations"]
    verdict = deterministic_verdict(obligations)
    payload = {
        "checkpoint": "DETERMINISTIC_COMPLETE",
        "record_basis": "DETERMINISTIC_RECORD",
        "investigation_id": iid,
        "scope": values["understand"].scope.model_dump(),
        "deterministic_verdict": verdict,
        "gate": {"verdict": verdict, "assessment_finalizable": False, "deployment_authorized": False,
                 "blockers": [("model_stages_disabled" if unavailable["payload"].get("disabled_by_configuration")
                               else "model_stages_unavailable:" + unavailable["payload"]["stage"]),
                              "production_judgment_not_qualified"]},
        "obligations": [{k: o[k] for k in ("element_id", "governed_status", "assessor_status", "basis")}
                        for o in obligations],
        "issues": len(rec_event["payload"]["issues"]),
        "model_stage_unavailable": unavailable["payload"],
        "reconciliation_event_hash": rec_event["event_hash"],
        "unavailable_event_hash": unavailable["event_hash"],
        "investigation_head": rows[-1]["record_hash"],
        "synthetic": values["understand"].synthetic,
        "deployment_authorized": False,
        "outcome_available": "PILOT_ATTESTATION on the deterministic record",
    }
    journal.append(REPORT_KEY, "run_report", payload, signers["executor"], "executor")
    return payload
