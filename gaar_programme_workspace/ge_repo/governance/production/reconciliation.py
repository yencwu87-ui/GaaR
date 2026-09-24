"""D8 — reconcile the assessor's obligation statuses against deterministic tests.

Why this exists
---------------
Phase 0 run B: qwen2.5:7b marked all four change-management obligations
SUPPORTED, cited real evidence ids, passed the examine validator, and was signed
into the record. The same evidence contains planted violations that the
deterministic procedures find every time. A citation check only proves evidence
was named, not that it supports the conclusion.

What it does
------------
Runs immediately after the examine stage is signed, before any further model
stage, so a model that stalls later cannot leave a false status standing.

1. Runs the configured deterministic procedures directly on the admitted
   evidence. It does not depend on the model choosing to plan them.
2. Maps each finding code to the obligations it tests, using a versioned
   mapping from configuration. Codes are the ones the procedures actually emit.
3. Derives a governed status per obligation:
     any mapped discrepancy          -> CONTRADICTED
     else any mapped assurance gap   -> NOT_EVIDENCED
     else                            -> the assessor's status, unchanged
   Deterministic silence never upgrades a status. It cannot prove support.
4. Keeps the assessor's original status beside the governed one and flags
   false assurance where the assessor said SUPPORTED and the tests disagree.
5. Opens one issue and one local remediation action per deterministic finding,
   whether or not any model raised it.

Everything is written as one executor-signed journal event bound to the signed
examine record, so it is replayable and cannot drift from what the model saw.
The signed examine stage itself is never altered.
"""
from __future__ import annotations

import json

from governance.investigation.store import digest
from .procedures import PROCEDURES

EVENT = "obligation_reconciliation"

# Every code the reconciled procedures can emit, with what it means. This is the
# single source for D8's validation and the mapping worksheet, so neither can
# drift into codes that no procedure produces.
CODE_CATALOGUE = {
    "NO_MATCHING_APPROVED_TICKET": ("change_authorization:2", "assurance gap",
        "The change names a ticket that is not in the export."),
    "APPROVAL_NOT_ESTABLISHED": ("change_authorization:2", "assurance gap",
        "The ticket exists but has no approver, no approval time, or is not in approved status."),
    "APPROVAL_AFTER_EXECUTION": ("change_authorization:2", "discrepancy",
        "The ticket was approved after the change had already run."),
    "SELF_APPROVAL": ("change_segregation:1", "discrepancy",
        "The ticket's approver is the same person who implemented the change."),
    "OUTSIDE_APPROVED_WINDOW": ("change_authorization:2", "discrepancy",
        "The change ran before the approved window opened or after it closed. Time zones are compared exactly."),
    "DEVIATES_FROM_APPROVED_SCOPE": ("change_authorization:2", "discrepancy",
        "The change touched a target, or performed an action, that the ticket does not allow."),
    "IMPLEMENTER_NOT_APPROVED": ("change_authorization:2", "discrepancy",
        "The person who made the change is not an approved implementer on the ticket."),
    "CREDENTIAL_NOT_APPROVED_FOR_CHANGE": ("change_authorization:2", "discrepancy",
        "The change used a credential the ticket does not allow."),
    "IMPLEMENTATION_CONTENT_MISMATCH": ("change_authorization:2", "discrepancy, or assurance gap if no deployed hash was recorded",
        "The artefact deployed differs from the one approved."),
    "PRIVILEGE_NOT_ESTABLISHED": ("change_authorization:2", "assurance gap",
        "No approved privilege grant covers this person, credential, target and action at the time of the change."),
    "FREEZE_WITHOUT_PRIOR_EXCEPTION": ("change_authorization:2", "assurance gap",
        "The change ran inside a declared freeze with no exception approved beforehand."),
    "RECOVERY_NOT_ESTABLISHED": ("change_authorization:2", "assurance gap",
        "A failed change has no recorded, approved and successful recovery."),
    "COLLECTION_POPULATION_DISAGREEMENT": ("change_population:1", "assurance gap",
        "The primary change record and the independent record list different changes."),
}
KNOWN_CODES = frozenset(CODE_CATALOGUE)


def validate_map(mapping: dict) -> None:
    unknown = sorted({c for codes in mapping.values() for c in codes} - KNOWN_CODES)
    if unknown:
        raise ValueError("reconciliation mapping names codes no procedure emits: " + ", ".join(unknown)
                         + ". Valid codes: " + ", ".join(sorted(KNOWN_CODES)))

# (procedure, version) chosen by the shape of the admitted export.
CHANGE_EXPORT = (("change_authorization", "2"), ("change_segregation", "1"))
POPULATION_EXPORT = (("change_population", "1"),)


def verify_signed_mapping(config: dict, control_id: str, mapping: dict) -> dict:
    """Re-verify the signed mapping document on every run, not a hash copied into the configuration.

    A hash stored beside the mapping can be edited together with it. The signature cannot:
    the document must verify against a trusted human governance key, and its mapping must be
    exactly the one about to be used.
    """
    reference = config.get("reconciliation_mapping_document")
    if not reference or reference.get("control_id") != control_id:
        return {"mapping_signed_by": None}
    from pathlib import Path
    from governance.result_contract import verify_signature
    from governance.investigation.store import canonical
    document = json.loads(Path(reference["path"]).read_text())
    policy = config["trusted_keys"].get(document.get("key_id"), {})
    if policy.get("actor_type") != "human" or "governance" not in policy.get("roles", []):
        raise ValueError("the mapping document is not signed by a trusted human governance identity")
    if not verify_signature(policy["public_key"], document["signature"], canonical(document["payload"]).encode()):
        raise ValueError("the mapping document signature is invalid")
    if document["payload"]["mapping"] != mapping or document["payload"]["control_id"] != control_id:
        raise ValueError("reconciliation mapping differs from the signed mapping document")
    result = {"mapping_signed_by": document["payload"]["signed_by"], "mapping_document_sha256": digest(document)}
    if reference.get("review"):
        review = json.loads(Path(reference["review"]["path"]).read_text())
        verified = verify_mapping_review(review, document)
        result.update(mapping_reviewed_by=verified["reviewer"], mapping_review_outcome=verified["outcome"],
                      mapping_review_sha256=digest(review))
    return result


REVIEW_OUTCOMES = ("AGREED", "CHANGES_REQUESTED")


def verify_mapping_review(review: dict, mapping_document: dict) -> dict:
    """A signed, independent review of one exact mapping document (quality policy §6.4)."""
    from governance.result_contract import verify_signature
    from governance.investigation.store import canonical
    payload = review["payload"]
    if not verify_signature(payload["reviewer_public_key"], review["signature"], canonical(payload).encode()):
        raise ValueError("the mapping review signature is invalid")
    if payload["mapping_document_sha256"] != digest(mapping_document):
        raise ValueError("the mapping review is about a different mapping document")
    if payload["outcome"] not in REVIEW_OUTCOMES:
        raise ValueError("the mapping review outcome must be AGREED or CHANGES_REQUESTED")
    if (payload["reviewer_key_id"] == mapping_document.get("key_id")
            or payload["reviewer"].strip().lower() == mapping_document["payload"]["signed_by"].strip().lower()):
        raise ValueError("the mapping review is not independent: the reviewer is the mapping's signer")
    return payload


def configured_map(config: dict, control_id: str) -> dict | None:
    return (config.get("reconciliation_map") or {}).get(control_id)


def due(config: dict, values: dict, journal) -> bool:
    if "examine" not in values:
        return False
    if not configured_map(config, values["understand"].control_id):
        return False
    return journal.latest(EVENT) is None


def _procedures_for(package: dict):
    if isinstance(package.get("changes"), list):
        return CHANGE_EXPORT
    if "primary" in package and "independent" in package:
        return POPULATION_EXPORT
    return ()


def _run_procedures(values: dict, evidence) -> tuple[list, list]:
    scope = values["understand"].scope
    runs, findings = [], []
    for record in evidence:
        try:
            package = json.loads(record.text)
        except ValueError:
            continue
        if not isinstance(package, dict):
            continue
        for name, version in _procedures_for(package):
            entry = {"procedure": name, "version": version, "evidence_id": record.evidence_id,
                     "content_sha256": record.content_sha256}
            if package.get("scope") != scope.system_id or package.get("as_of") != scope.period:
                runs.append({**entry, "status": "NOT_COMPARABLE", "reason": "export scope or as_of differs from the investigation"})
                continue
            try:
                result = PROCEDURES[(name, version)](package)
            except Exception as exc:
                runs.append({**entry, "status": "FAILED", "reason": f"{type(exc).__name__}: {exc}"})
                continue
            runs.append({**entry, "status": result.get("status"), "result_sha256": digest(result),
                         "conclusion": result.get("conclusion")})
            for klass, items in (("discrepancy", result.get("findings", [])), ("gap", result.get("assurance_gaps", []))):
                for item in items:
                    findings.append({"code": item.get("code"), "class": klass, "procedure": f"{name}:{version}",
                                     "evidence_id": record.evidence_id,
                                     "event_id": item.get("event_id") or ",".join(item.get("missing_primary", []) or []) or None,
                                     "detail": {k: v for k, v in item.items() if k not in ("code",)}})
    return runs, findings


class _Unassessed:
    """Stands in for an obligation the assessor never examined (model unavailable)."""
    status = "MODEL_UNAVAILABLE"
    evidence_refs = ()

    def __init__(self, element_id):
        self.element_id = element_id


def coverage_statement(values: dict, admitted) -> dict:
    """What the checks applied to this period, and whether an independent record corroborates it."""
    from .procedures import change_coverage
    scope = values["understand"].scope
    change_pkg = population_pkg = None
    for record in admitted:
        try:
            package = json.loads(record.text)
        except ValueError:
            continue
        if not isinstance(package, dict) or package.get("scope") != scope.system_id or package.get("as_of") != scope.period:
            continue
        if isinstance(package.get("changes"), list):
            change_pkg = package
        elif "primary" in package and "independent" in package:
            population_pkg = package
    if change_pkg is None:
        return {"status": "NOT_COMPARABLE", "reason": "no change export for this period", "corroborated": False}
    try:
        coverage = change_coverage(change_pkg)
    except Exception as exc:
        return {"status": "FAILED", "reason": f"{type(exc).__name__}: {exc}", "corroborated": False}
    if coverage["status"] != "COMPUTED_ON_SUPPLIED_EXPORTS":
        return {**coverage, "corroborated": False}
    corroboration = {"corroborated": False, "reason": "no population export for this period"}
    if population_pkg is not None:
        primary, independent = population_pkg.get("primary") or {}, population_pkg.get("independent") or {}
        p_ids, i_ids = sorted(primary.get("event_ids") or []), sorted(independent.get("event_ids") or [])
        if not (primary.get("complete") is True and independent.get("complete") is True):
            corroboration = {"corroborated": False, "reason": "a population record is not declared complete"}
        elif p_ids != i_ids:
            corroboration = {"corroborated": False, "reason": "the primary and independent records differ"}
        elif p_ids != coverage["change_ids"]:
            corroboration = {"corroborated": False, "reason": "the assessed change export differs from the population"}
        else:
            corroboration = {"corroborated": True, "reason": f"independent record lists the same {len(p_ids)} changes"}
        coverage["applied_to"]["COLLECTION_POPULATION_DISAGREEMENT"] = len(set(p_ids) | set(i_ids))
    return {**coverage, **corroboration}


def reconcile(config: dict, iid: str, engine, journal, signer, evidence=None) -> dict:
    """Reconcile after examine, or, if examine was rejected, directly on the admitted evidence."""
    rows, values = engine.snapshot(iid)
    control = values["understand"].control_id
    mapping = configured_map(config, control)
    if not mapping:
        raise ValueError("no reconciliation mapping configured for " + control)
    validate_map(mapping)
    signed_mapping = verify_signed_mapping(config, control, mapping)
    if "examine" in values:
        examine_row = next(r for r in rows if r["stage"] == "examine")
        admitted, examined = values["examine"].evidence, values["examine"].findings
        binding = {"examine_record_hash": examine_row["record_hash"]}
    else:
        if not evidence:
            raise ValueError("examine is missing and no admitted evidence was supplied")
        manifest = journal.latest("evidence_manifest")
        if not manifest or {e[0] for e in manifest["payload"]["evidence"]} != {e.evidence_id for e in evidence}:
            raise ValueError("evidence must match the signed evidence manifest")
        admitted = evidence
        examined = [_Unassessed(e.element_id) for e in values["expectations"].elements]
        binding = {"examine_record_hash": None, "evidence_manifest_event_hash": manifest["event_hash"]}
    runs, findings = _run_procedures(values, admitted)
    coverage = coverage_statement(values, admitted)
    ran_ok = {r["procedure"] for r in runs if r.get("status") not in ("NOT_COMPARABLE", "FAILED", None)}

    code_to_elements: dict[str, list[str]] = {}
    for element, codes in mapping.items():
        for code in codes:
            code_to_elements.setdefault(code, []).append(element)

    issues = []
    for finding in findings:
        for element in code_to_elements.get(finding["code"], []):
            issue_id = "ISSUE-" + digest({"investigation_id": iid, "element": element, "code": finding["code"],
                                          "event": finding["event_id"], "evidence": finding["evidence_id"]})[:16]
            issues.append({"issue_id": issue_id, "element_id": element, **finding})
    unmapped = sorted({f["code"] for f in findings if f["code"] not in code_to_elements})

    obligations = []
    for exam in examined:
        hits = [i for i in issues if i["element_id"] == exam.element_id]
        if exam.element_id not in mapping:
            governed, basis = exam.status, "UNMAPPED"
        elif any(i["class"] == "discrepancy" for i in hits):
            governed, basis = "CONTRADICTED", "DETERMINISTIC_DISCREPANCY"
        elif hits:
            governed, basis = "NOT_EVIDENCED", "DETERMINISTIC_ASSURANCE_GAP"
        elif any(CODE_CATALOGUE[c][0].split(":")[0] not in ran_ok for c in mapping[exam.element_id]):
            governed, basis = "NOT_EVIDENCED", "PROCEDURE_DID_NOT_RUN"      # a mapped check that cannot run is never silence
        elif coverage.get("status") == "COMPUTED_ON_SUPPLIED_EXPORTS" and coverage.get("changes") == 0:
            governed, basis = "NOT_EVIDENCED", "EMPTY_POPULATION"            # checked 0 of 0: usually a broken collector
        elif coverage.get("corroborated") and exam.status in ("MODEL_UNAVAILABLE", "SUPPORTED"):
            applied = sum(coverage["applied_to"].get(c, 0) for c in mapping[exam.element_id])
            governed = "NO_EXCEPTIONS_FOR_PERIOD"
            basis = "COVERAGE_CORROBORATED" if applied else "NO_APPLICABLE_EVENTS"
        elif coverage.get("status") == "COMPUTED_ON_SUPPLIED_EXPORTS" and exam.status == "MODEL_UNAVAILABLE":
            governed, basis = "NOT_EVALUATED", "COVERAGE_UNCORROBORATED"
        elif exam.status == "MODEL_UNAVAILABLE":
            governed, basis = "NOT_EVALUATED", "NO_FINDING_NO_ASSESSOR"
        else:
            governed, basis = exam.status, "ASSESSOR_UNCHALLENGED"
        obligations.append({"element_id": exam.element_id, "assessor_status": exam.status,
                            "assessor_evidence_refs": list(exam.evidence_refs), "governed_status": governed,
                            "basis": basis, "issue_ids": [i["issue_id"] for i in hits],
                            "coverage": ({c: {"applied_to": coverage["applied_to"].get(c),
                                              "violations": sum(1 for i in hits if i["code"] == c)}
                                          for c in mapping.get(exam.element_id, [])}
                                         if coverage.get("status") == "COMPUTED_ON_SUPPLIED_EXPORTS" else None),
                            "false_assurance": exam.status == "SUPPORTED" and governed in ("CONTRADICTED", "NOT_EVIDENCED")})

    payload = {"investigation_id": iid, "control_id": control, **binding, **signed_mapping,
               "mapping_sha256": digest(mapping), "mapping": mapping, "procedures": runs,
               "obligations": obligations, "issues": issues, "unmapped_codes": unmapped,
               "coverage": {k: v for k, v in coverage.items() if k != "change_ids"},
               "clock_simulated": config.get("simulated_clock"),
               "false_assurance_count": sum(o["false_assurance"] for o in obligations)}
    event = journal.append(EVENT, EVENT, json.loads(json.dumps(payload)), signer, "executor")
    _open_actions(config, iid, values, journal, signer, issues)
    return event["payload"]


def _open_actions(config, iid, values, journal, signer, issues):
    """One local remediation action per deterministic issue. Nothing is sent anywhere."""
    ctx = values["understand"]
    owner = config.get("action_owners", {}).get(ctx.control_id)
    trusted = any(p.get("actor") == owner and "action_owner" in p.get("roles", [])
                  for p in config["trusted_keys"].values())
    auto = config["trusted_keys"][signer.key_id].get("allow_action_assignment") is True
    existing = {e["event_key"] for e in journal.read()}
    for issue in issues:
        action_id = "ACTION-" + digest({"investigation_id": iid, "issue_id": issue["issue_id"]})
        if action_id in existing:
            continue
        claim = (f"{issue['code']} on {issue['event_id'] or issue['evidence_id']} "
                 f"({'discrepancy' if issue['class'] == 'discrepancy' else 'assurance gap'}) "
                 f"affecting {issue['element_id']}")
        action = {"action_id": action_id, "investigation_id": iid, "risk_ref": issue["issue_id"], "claim": claim,
                  "source": "DETERMINISTIC_RECONCILIATION", "system_id": ctx.scope.system_id,
                  "control_id": ctx.control_id, "framework": ctx.framework,
                  "owner": owner if trusted and auto else None,
                  "status": "OPEN" if trusted and auto else "OWNER_ASSIGNMENT_REQUIRED", "delivery": "LOCAL_ONLY",
                  "required_closure_tools": config.get("closure_tools_by_control", {}).get(ctx.control_id, [])}
        journal.append(action_id, "remediation_opened", action, signer, "executor")


def gate_blockers(config: dict, values: dict, journal) -> list[str]:
    """Blockers the integrated gate adds when reconciliation is configured."""
    if "examine" not in values or not configured_map(config, values["understand"].control_id):
        return []
    event = journal.latest(EVENT)
    if not event:
        return ["obligation_reconciliation_missing"]
    blockers = []
    if "conclude" in values and values["conclude"].verdict == "PASS":
        blockers += ["pass_conflicts_with_reconciliation:" + o["element_id"]
                     for o in event["payload"]["obligations"] if o["governed_status"] != "SUPPORTED"]
    return blockers


def attempted_false_assurance(response_text: str, obligations: list[dict]) -> dict:
    """D13: what the model claimed, measured from its receipt, not from the record.

    The recorded count only sees answers a validator accepted. A rejected answer
    never reaches the record, so it scores zero there even when the model claimed
    SUPPORTED on every obligation. Model comparison and the escape-rate metric
    need the attempted count: SUPPORTED claims on obligations the deterministic
    reconciliation does not support.
    """
    try:
        findings = json.loads(response_text).get("findings", [])
    except (ValueError, AttributeError):
        return {"parsed": False, "attempted": None, "claimed_supported": None, "obligations": len(obligations)}
    governed = {o["element_id"]: o["governed_status"] for o in obligations}
    claimed = [f.get("element_id") for f in findings if isinstance(f, dict) and f.get("status") == "SUPPORTED"]
    false = sorted(e for e in claimed if e in governed and governed[e] != "SUPPORTED")
    return {"parsed": True, "attempted": len(false), "false_claims": false,
            "claimed_supported": len(claimed), "obligations": len(governed)}
