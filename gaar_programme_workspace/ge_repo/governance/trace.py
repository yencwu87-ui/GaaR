"""Reviewer-facing trace assembly.

Turns the signed artefacts a completed run leaves behind into one structure a
human reviewer can read top-down and drill into: verdict -> risk -> basis ->
exact source bytes -> executed test -> challenge -> model receipt.

Design rules
------------
1.  Read-only. This module never appends, signs, seals or decides anything.
2.  Offline. It needs only the case directory (`investigation.json` plus
    `inference_receipts/`). No private keys, no model service, no network.
3.  Nothing is invented. Every field here is copied from a signed record. If a
    reference cannot be resolved it is reported as unresolved rather than
    quietly dropped, because a dangling basis reference is itself a finding.
4.  Verification is separate from presentation. `verify_chain` recomputes the
    hash chain and signatures when the trust policy is supplied; the trace
    renders with or without it and always says which happened.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ZERO = "0" * 64

STAGE_TITLES = {
    "understand": "Scope and ownership",
    "expectations": "Obligations in force",
    "examine": "Evidence examination",
    "explain": "Explanation and dependencies",
    "plan": "Test plan",
    "verify": "Test execution",
    "challenge": "Independent challenge",
    "conclude": "Disposition",
}

STAGE_ROLE_LABEL = {
    "understand": "System owner",
    "expectations": "Governance",
    "examine": "Assessor",
    "explain": "Assessor",
    "plan": "Test planner",
    "verify": "Executor (deterministic)",
    "challenge": "Challenger (independent)",
    "conclude": "Decision",
}

VERDICT_MEANING = {
    "ADVERSE": "The record contains evidence or executed test output that contradicts the obligation.",
    "INCONCLUSIVE": "Nothing was contradicted, but the evidence available was not sufficient to support the obligation either.",
    "PASS": "Every applicable obligation was supported by in-scope evidence of the right kind, and nothing executed contradicted it.",
}

CHECKPOINT_MEANING = {
    "COMPLETE": "All stages ran and the integrated quality gate is clear.",
    "EVALUATION_COMPLETE": "All stages ran. This is an evaluation run, so the result is not a production governance result.",
    "QUALITY_GATE_BLOCKED": "All stages ran, but the quality gate is holding the result.",
    "ACTION_REQUIRED": "The run stopped and is asking for something specific before it can continue.",
}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def case_directory(programme_dir: Path | str, investigation_id: str) -> Path:
    """Mirror of the orchestrator's directory naming, without importing it."""
    import hashlib

    return Path(programme_dir) / hashlib.sha256(investigation_id.encode()).hexdigest()


def discover_cases(programme_dir: Path | str) -> list[dict[str, Any]]:
    """List every case directory that holds a readable snapshot."""
    root = Path(programme_dir)
    found = []
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        snapshot = child / "investigation.json"
        status = child / "latest_status.json"
        if not snapshot.is_file() and not status.is_file():
            continue
        entry = {"case_dir": child, "investigation_id": None, "checkpoint": "UNKNOWN",
                 "verdict": None, "system_id": None, "control_id": None, "updated_at": None,
                 "has_snapshot": snapshot.is_file()}
        try:
            if status.is_file():
                data = json.loads(status.read_text())
                entry["investigation_id"] = data.get("investigation_id") or (data.get("request") or {}).get("investigation_id")
                entry["checkpoint"] = data.get("checkpoint", "UNKNOWN")
                entry["verdict"] = (data.get("gate") or {}).get("verdict")
                entry["system_id"] = (data.get("scope") or {}).get("system_id")
                entry["blockers"] = (data.get("gate") or {}).get("blockers", [])
                entry["request"] = data.get("request") or data.get("next_request")
            if snapshot.is_file():
                rows = json.loads(snapshot.read_text()).get("rows", [])
                if rows:
                    context = rows[0]["payload"]
                    entry["investigation_id"] = entry["investigation_id"] or context.get("investigation_id")
                    entry["control_id"] = context.get("control_id")
                    entry["system_id"] = entry["system_id"] or context.get("scope", {}).get("system_id")
                    entry["updated_at"] = rows[-1].get("at")
                    entry["stages_complete"] = len(rows)
        except (OSError, ValueError) as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        found.append(entry)
    return found


def load_snapshot(case_dir: Path | str) -> dict[str, Any]:
    path = Path(case_dir) / "investigation.json"
    if not path.is_file():
        raise FileNotFoundError(
            "No investigation snapshot in this case directory. The run has not reached "
            "a concluded state yet; read latest_status.json for the current request.")
    return json.loads(path.read_text())


def load_receipts(case_dir: Path | str) -> list[dict[str, Any]]:
    """Signed model request/response receipts, oldest first.

    The prompt and the raw response are both in the receipt, so this is the
    complete record of what the assessor and the challenger were actually asked
    and actually said.
    """
    folder = Path(case_dir) / "inference_receipts"
    receipts = []
    if not folder.is_dir():
        return receipts
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        data["_path"] = str(path)
        receipts.append(data)
    receipts.sort(key=lambda r: r.get("started_at", ""))
    return receipts


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def verify_chain(rows: list[dict], trusted_keys: dict | None = None) -> dict[str, Any]:
    """Recompute the stage hash chain, and signatures when keys are supplied.

    Returns a plain report. A reviewer should be able to see *unverified* as a
    distinct state from *verified* and from *failed* -- never a silent pass.
    """
    from governance.investigation.contracts import MODELS, ROLES, STAGES
    problems: list[str] = []
    head = ZERO
    actors: dict[str, str] = {}
    public_keys: dict[str, str] = {}
    investigation_id = rows[0].get("investigation_id") if rows else None
    for index, row in enumerate(rows):
        if row.get("sequence") != index:
            problems.append(f"stage {index}: out-of-order sequence")
        if index >= len(STAGES) or row.get("stage") != STAGES[index]:
            problems.append(f"stage {index}: fixed stage order violated")
        if row.get("investigation_id") != investigation_id:
            problems.append(f"stage {row.get('stage')}: investigation identity changed")
        if row.get("previous") != head:
            problems.append(f"stage {row.get('stage')}: chain break")
        unsigned = {k: v for k, v in row.items() if k not in ("signature", "record_hash")}
        if _digest({**unsigned, "signature": row.get("signature")}) != row.get("record_hash"):
            problems.append(f"stage {row.get('stage')}: record hash mismatch")
        try:
            MODELS[row["stage"]].model_validate(row.get("payload"))
        except Exception as exc:
            problems.append(f"stage {row.get('stage')}: invalid payload ({type(exc).__name__})")
        if row.get("stage") == "understand":
            if row.get("payload", {}).get("owner") != row.get("actor"):
                problems.append("stage understand: owner does not match signer")
        if row.get("stage") == "challenge":
            if row.get("payload", {}).get("input_head") != head:
                problems.append("stage challenge: input head does not bind reviewed record")
        head = row.get("record_hash")

    signature_status = "NOT_CHECKED"
    signatures = "not checked (external trust policy not supplied)"
    if trusted_keys:
        try:
            from governance.result_contract import verify_signature
            bad = []
            for row in rows:
                policy = trusted_keys.get(row.get("key_id"), {})
                unsigned = {k: v for k, v in row.items() if k not in ("signature", "record_hash")}
                stage = row.get("stage")
                if (row.get("policy_sha256") != _digest(trusted_keys)
                        or policy.get("actor") != row.get("actor")
                        or ROLES.get(stage) not in policy.get("roles", [])
                        or not verify_signature(policy.get("public_key", ""), row.get("signature", ""),
                                                _canonical(unsigned).encode())):
                    bad.append(row.get("stage"))
                actors[stage] = row.get("actor")
                public_keys[stage] = policy.get("public_key")
            if actors.get("challenge") in {actors.get("examine"), actors.get("explain")}:
                bad.append("challenge-principal-independence")
            if public_keys.get("challenge") in {public_keys.get("examine"), public_keys.get("explain")}:
                bad.append("challenge-key-independence")
            signature_status = "VALID" if not bad else "INVALID"
            signatures = "all valid" if not bad else "INVALID: " + ", ".join(bad)
            problems.extend(f"stage {s}: invalid signature" for s in bad)
        except Exception as exc:  # signature backend unavailable
            signature_status = "UNAVAILABLE"
            signatures = f"unable to check ({type(exc).__name__})"
            problems.append(f"signature verification unavailable: {type(exc).__name__}")

    return {"stages": len(rows), "head": head, "chain_intact": not problems,
            "signature_status": signature_status, "signatures": signatures, "problems": problems}


def verify_operations(case_dir: Path, trusted_keys: dict | None) -> dict[str, Any]:
    """Verify the operational chain without opening the SQLite database for writes."""
    database = case_dir / "operations.sqlite"
    anchor_path = case_dir / "operations.anchor.json"
    if not database.is_file():
        return {"status": "UNAVAILABLE", "events": 0, "problems": ["operational journal absent"]}
    try:
        uri = f"file:{database.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            events = [json.loads(row[0]) for row in connection.execute(
                "SELECT envelope FROM entries ORDER BY sequence")]
    except Exception as exc:
        return {"status": "INVALID", "events": 0,
                "problems": [f"operational journal unreadable: {type(exc).__name__}: {exc}"]}
    if not trusted_keys:
        return {"status": "NOT_CHECKED", "events": len(events),
                "problems": ["external trust policy not supplied"]}
    from governance.production.journal import authorized_kind
    from governance.result_contract import verify_signature
    problems, previous = [], ZERO
    for index, event in enumerate(events):
        policy = trusted_keys.get(event.get("key_id"), {})
        unsigned = {k: v for k, v in event.items() if k not in {"signature", "event_hash"}}
        if event.get("sequence") != index or event.get("previous") != previous:
            problems.append(f"operational event {index}: chain/order mismatch")
        if event.get("policy_sha256") != _digest(trusted_keys):
            problems.append(f"operational event {index}: trust policy mismatch")
        if (event.get("actor") != policy.get("actor")
                or event.get("role") not in policy.get("roles", [])
                or not authorized_kind(event.get("kind"), event.get("payload", {}), event.get("role"))):
            problems.append(f"operational event {index}: signer/role not authorised")
        if not verify_signature(policy.get("public_key", ""), event.get("signature", ""),
                                _canonical(unsigned).encode()):
            problems.append(f"operational event {index}: invalid signature")
        if _digest({**unsigned, "signature": event.get("signature")}) != event.get("event_hash"):
            problems.append(f"operational event {index}: hash mismatch")
        previous = event.get("event_hash")
    if not anchor_path.is_file():
        problems.append("operational head anchor absent")
    else:
        try:
            anchor = json.loads(anchor_path.read_text())
            if (anchor.get("sequence", -1) >= len(events)
                    or events[anchor["sequence"]].get("event_hash") != anchor.get("event_hash")):
                problems.append("operational head anchor does not match retained history")
        except Exception as exc:
            problems.append(f"operational head anchor invalid: {type(exc).__name__}")
    return {"status": "VALID" if not problems else "INVALID", "events": len(events),
            "head": previous, "problems": problems, "records": events}


def verify_receipts(receipts: list[dict], trusted_keys: dict | None,
                    investigation_id: str | None) -> dict[str, Any]:
    if not receipts:
        return {"status": "UNAVAILABLE", "receipts": 0, "problems": ["inference receipts absent"]}
    if not trusted_keys:
        return {"status": "NOT_CHECKED", "receipts": len(receipts),
                "problems": ["external trust policy not supplied"]}
    from governance.result_contract import verify_signature
    roles = {"examine": "assessor", "explain": "assessor", "plan": "test_planner",
             "dependency_review": "assessor", "challenge": "challenger"}
    problems = []
    for index, stored in enumerate(receipts):
        receipt = {k: v for k, v in stored.items() if k != "_path"}
        signature = receipt.pop("signature", "")
        policy = trusted_keys.get(receipt.get("key_id"), {})
        stage = str(receipt.get("stage", "")).removeprefix("evaluation_")
        if receipt.get("investigation_id") != investigation_id:
            problems.append(f"receipt {index}: investigation identity mismatch")
        if roles.get(stage) not in policy.get("roles", []):
            problems.append(f"receipt {index}: identity not authorised for {stage}")
        if hashlib.sha256(str(receipt.get("prompt", "")).encode()).hexdigest() != receipt.get("prompt_sha256"):
            problems.append(f"receipt {index}: prompt hash mismatch")
        response = receipt.get("response")
        if response is not None and hashlib.sha256(str(response).encode()).hexdigest() != receipt.get("response_sha256"):
            problems.append(f"receipt {index}: response hash mismatch")
        if not verify_signature(policy.get("public_key", ""), signature,
                                _canonical(receipt).encode()):
            problems.append(f"receipt {index}: invalid signature")
    return {"status": "VALID" if not problems else "INVALID", "receipts": len(receipts),
            "problems": problems}


# --------------------------------------------------------------------------
# trace assembly
# --------------------------------------------------------------------------

@dataclass
class BasisItem:
    """One resolved reference behind a claim."""
    ref: str
    kind: str                      # evidence | gap | hypothesis | test | element | dependency | unresolved
    label: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Risk:
    ref: str
    origin: str                    # "Assessor" or "Challenger"
    claim: str
    material: bool
    basis: list[BasisItem] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    compensating: str = ""
    tests: list[dict] = field(default_factory=list)
    disposition: dict | None = None
    escalation: dict | None = None
    dependencies: list[dict] = field(default_factory=list)


def _stage_payloads(rows: list[dict]) -> dict[str, dict]:
    return {row["stage"]: row["payload"] for row in rows}


def source_status(entry: dict | None) -> str:
    """How the obligation's source came to be trusted, in reviewer terms."""
    if entry is None:
        return "UNREGISTERED"
    if entry.get("evaluation_fixture") is True:
        return "EVALUATION_FIXTURE_NOT_GOVERNANCE_APPROVED"
    if entry.get("authority_decision_ref") and entry.get("approved_by"):
        return "GOVERNANCE_DECISION_ON_FILE"
    return "APPROVAL_NOT_RECORDED"


def build_trace(case_dir: Path | str, trusted_keys: dict | None = None,
                sources: dict | None = None) -> dict[str, Any]:
    """Assemble the whole reviewer view from one case directory.

    `sources` is the configured source registry. When supplied, each obligation
    carries how its source was approved, so a fixture source never looks the
    same as a governance-approved one.
    """
    case_dir = Path(case_dir)
    snapshot = load_snapshot(case_dir)
    rows = snapshot.get("rows", [])
    report = snapshot.get("report", {})
    dependency_event = snapshot.get("dependency_review") or {}
    payloads = _stage_payloads(rows)

    context = payloads.get("understand", {})
    expectations = {e["element_id"]: e for e in payloads.get("expectations", {}).get("elements", [])}
    examine = payloads.get("examine", {})
    evidence = {e["evidence_id"]: e for e in examine.get("evidence", [])}
    findings = {f["element_id"]: f for f in examine.get("findings", [])}
    explain = payloads.get("explain", {})
    hypotheses = {h["hypothesis_id"]: h for h in explain.get("hypotheses", [])}
    dependencies = {d["dependency_id"]: d for d in explain.get("dependencies", [])}
    plan = {t["test_id"]: t for t in payloads.get("plan", {}).get("tests", [])}
    verify = {t["test_id"]: t for t in payloads.get("verify", {}).get("tests", [])}
    challenge = payloads.get("challenge", {})
    challenge_findings = {f["finding_id"]: f for f in challenge.get("findings", [])}
    conclude = payloads.get("conclude", {})
    dispositions = {d["risk_ref"]: d for d in conclude.get("dispositions", [])}
    escalations = {d["risk_ref"]: d for d in conclude.get("escalation_decisions", [])}

    treatments = (dependency_event.get("payload", {}).get("review", {}) or {}).get("treatments", [])
    treatments_by_risk: dict[str, list[dict]] = {}
    for treatment in treatments:
        for ref in treatment.get("risk_refs", []):
            treatments_by_risk.setdefault(ref, []).append(treatment)

    def resolve(ref: str) -> BasisItem:
        if ref in evidence:
            item = evidence[ref]
            return BasisItem(ref, "evidence",
                             f"Evidence {ref} from {item['source_id']}, bytes {item['start']}-{item['end']}",
                             item)
        if ref.startswith("gap:"):
            element = ref.split(":", 1)[1]
            finding = findings.get(element, {})
            return BasisItem(ref, "gap",
                             f"Recorded gap on obligation {element} ({finding.get('status', 'unknown')})",
                             {"element": expectations.get(element, {}), "finding": finding})
        if ref in hypotheses:
            return BasisItem(ref, "hypothesis", f"Assessor explanation {ref}", hypotheses[ref])
        if ref in verify:
            return BasisItem(ref, "test", f"Executed test {ref}", {"plan": plan.get(ref, {}), "result": verify[ref]})
        if ref in expectations:
            return BasisItem(ref, "element", f"Obligation {ref}", expectations[ref])
        if ref in dependencies:
            return BasisItem(ref, "dependency", f"Dependency {ref}", dependencies[ref])
        if ref in challenge_findings:
            return BasisItem(ref, "challenge_finding", f"Challenge finding {ref}", challenge_findings[ref])
        return BasisItem(ref, "unresolved", f"Reference {ref} could not be resolved in this record", {})

    def tests_for(risk_ref: str) -> list[dict]:
        out = []
        for test_id, proposal in plan.items():
            if proposal.get("hypothesis_id") != risk_ref:
                continue
            execution = verify.get(test_id, {})
            result = {}
            if execution.get("result_json"):
                try:
                    result = json.loads(execution["result_json"])
                except ValueError:
                    result = {"unparsed": execution["result_json"][:400]}
            out.append({
                "test_id": test_id,
                "tool": proposal.get("tool"),
                "version": proposal.get("version"),
                "why": proposal.get("decision_impact"),
                "input_evidence": proposal.get("input_ref"),
                "required": proposal.get("required", True),
                "status": execution.get("status", "NOT_EVALUATED"),
                "limitation": execution.get("limitation", ""),
                "implementation_sha256": execution.get("implementation_sha256", ""),
                "result": result,
                "findings": result.get("findings", []),
                "assurance_gaps": result.get("assurance_gaps", []),
            })
        return out

    risks: list[Risk] = []
    for ref, item in hypotheses.items():
        risks.append(Risk(ref=ref, origin="Assessor", claim=item.get("claim", ""),
                          material=bool(item.get("material")),
                          basis=[resolve(r) for r in item.get("basis_refs", [])],
                          alternatives=list(item.get("alternatives", [])),
                          compensating=item.get("compensating_controls_review", ""),
                          tests=tests_for(ref),
                          disposition=dispositions.get(ref),
                          escalation=escalations.get(ref),
                          dependencies=treatments_by_risk.get(ref, [])))
    for ref, item in challenge_findings.items():
        risks.append(Risk(ref=ref, origin="Challenger", claim=item.get("claim", ""),
                          material=bool(item.get("material")),
                          basis=[resolve(r) for r in item.get("basis_refs", [])],
                          disposition=dispositions.get(ref),
                          escalation=escalations.get(ref),
                          dependencies=treatments_by_risk.get(ref, [])))
    risks.sort(key=lambda r: (not r.material, r.origin, r.ref))

    elements = []
    for element_id, expectation in expectations.items():
        finding = findings.get(element_id, {})
        elements.append({
            "element_id": element_id,
            "text": expectation.get("text", ""),
            "purpose": expectation.get("purpose"),
            "authority": expectation.get("authority"),
            "source_id": expectation.get("source_id"),
            "source_version": expectation.get("source_version"),
            "source_sha256": expectation.get("source_sha256"),
            "source_status": ("NOT_CHECKED" if sources is None
                              else source_status(sources.get(expectation.get("source_id")))),
            "approved_by": ((sources or {}).get(expectation.get("source_id")) or {}).get("approved_by"),
            "applies": expectation.get("applies"),
            "applicability_reason": expectation.get("applicability_reason", ""),
            "status": finding.get("status", "NOT_EVALUATED"),
            "rationale": finding.get("rationale", ""),
            "evidence": [evidence[r] for r in finding.get("evidence_refs", []) if r in evidence],
        })

    timeline = [{
        "stage": row["stage"],
        "title": STAGE_TITLES.get(row["stage"], row["stage"]),
        "role": STAGE_ROLE_LABEL.get(row["stage"], ""),
        "actor": row.get("actor"),
        "at": row.get("at"),
        "record_hash": row.get("record_hash"),
        "key_id": row.get("key_id"),
    } for row in rows]

    receipts = load_receipts(case_dir)
    reasoning = [{
        "stage": r.get("stage"),
        "model": r.get("model"),
        "provider": r.get("provider"),
        "status": r.get("status"),
        "live": r.get("live"),
        "started_at": r.get("started_at"),
        "finished_at": r.get("finished_at"),
        "prompt_sha256": r.get("prompt_sha256"),
        "response_sha256": r.get("response_sha256"),
        "prompt": r.get("prompt", ""),
        "response": r.get("response", ""),
        "error": r.get("error", ""),
        "path": r.get("_path", ""),
    } for r in receipts]

    gate = report.get("gate", {})
    verdict = gate.get("verdict") or conclude.get("verdict")
    checkpoint = report.get("checkpoint", "UNKNOWN")

    unresolved = sorted({b.ref for r in risks for b in r.basis if b.kind == "unresolved"})
    retrieval = explain.get("retrieval", [])
    incomplete_lanes = [lane for lane in retrieval if lane.get("status") != "COMPLETED"]

    stage_integrity = verify_chain(rows, trusted_keys)
    operational_integrity = verify_operations(case_dir, trusted_keys)
    receipt_integrity = verify_receipts(receipts, trusted_keys,
                                        context.get("investigation_id") or report.get("investigation_id"))
    attestation = None
    reconciliation = None
    if operational_integrity.get("status") == "VALID":
        events = operational_integrity.pop("records", [])
        # Only an attestation read from the verified journal is shown.
        reconciled = [e for e in events if e.get("kind") == "obligation_reconciliation"]
        if reconciled:
            reconciliation = {**reconciled[-1].get("payload", {}), "event_hash": reconciled[-1].get("event_hash")}
        signed = [e for e in events if e.get("kind") == "pilot_attestation"]
        if signed:
            item = signed[-1]
            body = item.get("payload", {}).get("attestation", {})
            attestation = {**body, "event_hash": item.get("event_hash"), "signed_by": item.get("actor"),
                           "binds_current_head": body.get("investigation_head") == (rows[-1]["record_hash"] if rows else None)}
        event_hashes = {event.get("event_hash") for event in events}
        if dependency_event and dependency_event.get("event_hash") not in event_hashes:
            operational_integrity["status"] = "INVALID"
            operational_integrity["problems"].append(
                "snapshot dependency review is not present in the verified operational journal")
        run_reports = [event.get("payload") for event in events if event.get("kind") == "run_report"]
        if report and not any(all(report.get(key) == value for key, value in signed.items())
                              for signed in run_reports):
            operational_integrity["status"] = "INVALID"
            operational_integrity["problems"].append(
                "snapshot report is not present in the verified operational journal")
    states = [stage_integrity.get("signature_status"), operational_integrity.get("status"),
              receipt_integrity.get("status")]
    overall = ("INVALID" if "INVALID" in states or not stage_integrity.get("chain_intact")
               else "VALID" if all(state == "VALID" for state in states)
               else "NOT_CHECKED" if "NOT_CHECKED" in states
               else "PARTIAL")

    result = {
        "investigation_id": context.get("investigation_id") or report.get("investigation_id"),
        "control_id": context.get("control_id"),
        "framework": context.get("framework"),
        "requirement_version": context.get("requirement_version"),
        "owner": context.get("owner"),
        "criticality": context.get("criticality"),
        "boundary": context.get("boundary", ""),
        "synthetic": bool(context.get("synthetic")),
        "scope": context.get("scope", {}),
        "verdict": verdict,
        "verdict_meaning": VERDICT_MEANING.get(verdict, ""),
        "rationale": conclude.get("rationale", ""),
        "uncertainty": list(conclude.get("uncertainty", [])),
        "checkpoint": checkpoint,
        "checkpoint_meaning": CHECKPOINT_MEANING.get(checkpoint, ""),
        "finalizable": bool(gate.get("assessment_finalizable")),
        "deployment_authorized": False,
        "blockers": list(gate.get("blockers", [])),
        "qualification": report.get("qualification", {}),
        "governance_result": report.get("governance_result"),
        "request": report.get("next_request") or report.get("request"),
        "actions": report.get("actions", []),
        "elements": elements,
        "risks": risks,
        "evidence": evidence,
        "tests": [{"test_id": tid, **verify[tid], "plan": plan.get(tid, {})} for tid in verify],
        "challenge": {
            "status": challenge.get("status"),
            "input_head": challenge.get("input_head"),
            "reviewed_count": len(challenge.get("reviewed_refs", [])),
            "reviewed_refs": list(challenge.get("reviewed_refs", [])),
            "disproof_attempts": list(challenge.get("disproof_attempts", [])),
            "missing_explanations": list(challenge.get("missing_explanations", [])),
            "findings": list(challenge.get("findings", [])),
        },
        "dependency_review": {
            "event_hash": dependency_event.get("event_hash"),
            "actor": dependency_event.get("actor"),
            "knowledge_sha256": (dependency_event.get("payload", {}).get("review", {}) or {}).get("knowledge_sha256"),
            "treatments": treatments,
            "counts": {status: sum(1 for t in treatments if t.get("status") == status)
                       for status in ("INVESTIGATED", "NOT_APPLICABLE", "UNRESOLVED", "UNAVAILABLE")},
        },
        "retrieval": retrieval,
        "incomplete_lanes": incomplete_lanes,
        "timeline": timeline,
        "reasoning": reasoning,
        "integrity": {**stage_integrity, "overall_status": overall,
                      "operations": operational_integrity, "receipts": receipt_integrity},
        "unresolved_references": unresolved,
        "pilot_attestation": attestation,
        "case_dir": str(case_dir),
    }
    result["reconciliation"] = reconciliation
    if reconciliation:
        # Only a reconciliation read from the verified journal changes what is shown.
        governed = {o["element_id"]: o for o in reconciliation.get("obligations", [])}
        for element in result["elements"]:
            o = governed.get(element["element_id"])
            if o:
                element["assessor_status"] = o["assessor_status"]
                element["status"] = o["governed_status"]
                element["false_assurance"] = o["false_assurance"]
                element["reconciliation_issues"] = [i for i in reconciliation.get("issues", [])
                                                    if i["element_id"] == element["element_id"]]
    return result


def headline(trace: dict[str, Any]) -> str:
    """One sentence a reviewer can read without any other context."""
    verdict = trace.get("verdict") or "NOT CONCLUDED"
    control = trace.get("control_id", "?")
    system = trace.get("scope", {}).get("system_id", "?")
    period = trace.get("scope", {}).get("period", "?")
    material = sum(1 for r in trace.get("risks", []) if r.material)
    if material:
        tail = f" {material} material issue{'s' if material != 1 else ''} {'require' if material != 1 else 'requires'} disposition."
    else:
        tail = " No material issue was raised."
    return f"{verdict} on {control} for {system}, period {period}.{tail}"


def evidence_quote(record: dict, limit: int = 1200) -> str:
    """Exact admitted bytes, truncated only for display, never reworded."""
    text = record.get("text", "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [{len(text) - limit} more characters in the admitted slice]"
