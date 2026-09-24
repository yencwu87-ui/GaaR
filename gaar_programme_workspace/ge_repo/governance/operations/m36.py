"""Read-only M3.6 procedures over supplied operating records, not model prose.

Thresholds and source authority are inputs from approved expectations. These
procedures do not invent regulatory thresholds or independently rerun a model.
"""
from datetime import datetime
import hashlib
import json
import math


def _time(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware time required")
    return dt


def _number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError("finite numeric input required")
    return x


def _base(p, name):
    for key in ("scope", "model_version", "as_of", "source_refs", "criteria_ref"):
        if not p.get(key):
            raise ValueError(f"{name}: missing {key}")
    if not isinstance(p["source_refs"], list) or any(not isinstance(r, str) or not r.strip() for r in p["source_refs"]):
        raise ValueError("source_refs must contain nonempty reference IDs")
    _time(p["as_of"])
    return {"procedure": name, "status": "COMPUTED_ON_SUPPLIED_EXPORTS",
        "scope": p["scope"], "model_version": p["model_version"], "as_of": p["as_of"],
        "source_refs": p["source_refs"], "criteria_ref": p["criteria_ref"],
        "findings": [], "assurance_gaps": [], "metrics": {},
        "input_sha256": hashlib.sha256(json.dumps(p, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "limitation": "Computed from supplied records. Does not establish authenticity, population completeness, legal applicability or independent validation quality.",
        "changes_control_verdict": False}


def _finish(out):
    out["conclusion"] = "ADVERSE" if out["findings"] else "INCONCLUSIVE" if out["assurance_gaps"] else "SUPPORTED_WITHIN_PROCEDURE_SCOPE"
    return out


def model_evaluation(p):
    """Recompute classification accuracy/error and compare approved thresholds."""
    out = _base(p, "m36_model_evaluation.1")
    rows = p.get("prediction_records")
    if not isinstance(rows, list) or not rows:
        out["assurance_gaps"].append("No actual prediction records supplied")
        return _finish(out)
    ids = [r["sample_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate prediction sample IDs")
    if any(r.get("model_version") != p["model_version"] for r in rows):
        raise ValueError("cross-version prediction record")
    if any(r.get("actual_label") is None or r.get("predicted_label") is None for r in rows):
        raise ValueError("missing labels cannot count as matching predictions")
    correct = sum(r["actual_label"] == r["predicted_label"] for r in rows)
    metrics = {"accuracy": correct / len(rows), "error_rate": 1 - correct / len(rows), "sample_count": len(rows)}
    out["metrics"] = metrics
    thresholds = p.get("approved_thresholds") or {}
    if not thresholds:
        out["assurance_gaps"].append("Approved performance thresholds absent")
    for metric, rule in thresholds.items():
        if metric not in {"accuracy", "error_rate"} or rule.get("operator") not in {">=", "<="}:
            raise ValueError("unsupported metric or threshold operator")
        limit = _number(rule["value"])
        if not 0 <= limit <= 1:
            raise ValueError("classification threshold outside 0..1")
        passed = metrics[metric] >= limit if rule["operator"] == ">=" else metrics[metric] <= limit
        if not passed:
            out["findings"].append(f"{metric}={metrics[metric]} violates supplied criterion {rule['operator']}{limit}")
    agreements = p.get("threshold_agreements") or []
    for role in ("business_owner", "developer", "reviewer"):
        if not any(a.get("role") == role and a.get("actor_id") and a.get("record_ref") for a in agreements):
            out["assurance_gaps"].append(f"Threshold agreement evidence missing for {role}")
    if "training_sample_ids" not in p:
        out["assurance_gaps"].append("Training/test separation not checkable")
    elif set(ids) & set(p["training_sample_ids"]):
        out["findings"].append("Evaluation samples overlap supplied training sample IDs")
    out["limitation"] += " Accuracy is recomputed from existing predictions; the assessed model was not invoked. Sample-ID separation alone does not rule out leakage."
    return _finish(out)


def representativeness(p):
    out = _base(p, "m36_representativeness.1")
    dimensions = p.get("dimensions")
    if not dimensions:
        out["assurance_gaps"].append("Population and test-group counts not supplied")
        return _finish(out)
    for dimension in dimensions:
        name = dimension["name"]
        population, test = dimension["population_counts"], dimension["test_counts"]
        for count in list(population.values()) + list(test.values()):
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("counts must be nonnegative integers")
        total_population, total_test = sum(population.values()), sum(test.values())
        if not total_population or not total_test:
            out["assurance_gaps"].append(f"{name}: zero population or test denominator")
            continue
        if "max_share_difference" not in dimension or "min_test_count" not in dimension:
            out["assurance_gaps"].append(f"{name}: approved coverage criteria absent")
            continue
        tolerance = _number(dimension["max_share_difference"])
        minimum = dimension["min_test_count"]
        if not 0 <= tolerance <= 1 or isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ValueError("invalid supplied coverage criterion")
        deltas = {}
        for group in sorted(set(population) | set(test)):
            delta = abs(population.get(group, 0)/total_population - test.get(group, 0)/total_test)
            deltas[group] = delta
            if delta > tolerance:
                out["findings"].append(f"{name}/{group}: distribution difference exceeds supplied tolerance")
            if population.get(group, 0) and test.get(group, 0) < minimum:
                out["findings"].append(f"{name}/{group}: insufficient tested members for supplied minimum")
        out["metrics"][name] = {"population_n": total_population, "test_n": total_test, "absolute_share_differences": deltas}
    out["limitation"] += " Supplied group counts cannot establish coverage of omitted groups or unseen future conditions."
    return _finish(out)


def independent_validation(p):
    out = _base(p, "m36_independent_validation.1")
    report = p.get("validation_record")
    if not report:
        out["assurance_gaps"].append("Validation/review operating record absent")
        return _finish(out)
    if report.get("model_version") != p["model_version"]:
        raise ValueError("validation is for a different model version")
    reviewers = report.get("reviewer_ids") or []
    if not reviewers:
        out["assurance_gaps"].append("Named reviewers absent")
    conflicts = set(reviewers) & (set(p.get("developer_ids", [])) | set(p.get("deployer_ids", [])))
    if conflicts:
        out["findings"].append("Reviewers overlap recorded development/deployment roles: " + ",".join(sorted(conflicts)))
    if "developer_ids" not in p or "deployer_ids" not in p:
        out["assurance_gaps"].append("Role population missing; independence cannot be established")
    competence = p.get("competency_evidence", {})
    for reviewer in reviewers:
        if not competence.get(reviewer):
            out["assurance_gaps"].append(f"Competence evidence missing for {reviewer}")
    if not report.get("completed_at") or not p.get("deployment_at"):
        out["assurance_gaps"].append("Review/deployment timing not checkable")
    elif _time(report["completed_at"]) > _time(p["deployment_at"]):
        out["findings"].append("Review completed after recorded deployment")
    if p.get("risk_tier") == "high":
        if not report.get("kind"):
            out["assurance_gaps"].append("Validation record type not supplied for high-risk scope")
        elif report["kind"] != "formal_independent_validation":
            out["findings"].append("Recorded validation type differs from the high-risk formal-validation criterion")
    if p.get("risk_tier") not in {"low", "medium", "high"}:
        out["assurance_gaps"].append("Approved materiality classification absent")
    required = p.get("required_review_areas")
    if not required:
        out["assurance_gaps"].append("Governed review scope absent")
    else:
        for area in required:
            if not (report.get("area_evidence_refs") or {}).get(area):
                out["assurance_gaps"].append(f"Review coverage evidence missing: {area}")
    if not report.get("challenge_records"):
        out["assurance_gaps"].append("Effective-challenge records absent")
    out["limitation"] += " Named roles and report references do not by themselves demonstrate competence, objectivity or effective challenge."
    return _finish(out)


def residual_risk(p):
    out = _base(p, "m36_residual_risk.1")
    risks = p.get("risks")
    if not isinstance(risks, list) or not risks:
        out["assurance_gaps"].append("Residual risk population absent; no clean acceptance inferred")
        return _finish(out)
    ids = [r["risk_id"] for r in risks]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate risk ID")
    for r in risks:
        rid = r["risk_id"]
        if not r.get("owner_id") or not r.get("assessment_ref"):
            out["assurance_gaps"].append(f"{rid}: accountable owner/assessment record absent")
        if "residual_score" not in r or "appetite_limit" not in r or not r.get("scale_id"):
            out["assurance_gaps"].append(f"{rid}: comparable residual-risk/appetite criteria absent")
            continue
        if _number(r["residual_score"]) > _number(r["appetite_limit"]):
            out["findings"].append(f"{rid}: residual risk exceeds the supplied appetite limit")
        acceptance = r.get("acceptance") or {}
        if not acceptance.get("record_ref") or acceptance.get("actor_id") not in p.get("authorized_acceptors", []):
            out["assurance_gaps"].append(f"{rid}: authorized acceptance evidence absent")
        if acceptance.get("at") and p.get("deployment_at"):
            if _time(acceptance["at"]) > _time(p["deployment_at"]):
                out["findings"].append(f"{rid}: acceptance followed deployment")
        else:
            out["assurance_gaps"].append(f"{rid}: acceptance/deployment timing unavailable")
    for finding in p.get("validation_findings", []):
        if finding.get("material") and (finding.get("disposition") not in {"remediated", "accepted_with_conditions", "deployment_blocked"} or not finding.get("disposition_ref")):
            out["assurance_gaps"].append(f"{finding['finding_id']}: material validation finding has no evidenced disposition")
    return _finish(out)


PROCEDURES = {("m36_model_evaluation", "1"): model_evaluation,
              ("m36_representativeness", "1"): representativeness,
              ("m36_independent_validation", "1"): independent_validation,
              ("m36_residual_risk", "1"): residual_risk}
