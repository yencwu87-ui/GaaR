"""Human result decisions, signed where the reviewer is sitting.

This is the last step of the loop. Everything before it is machine work the
reviewer reads; this is the part only a named person can do.

What it does
------------
Builds the approval payload `lifecycle.seal` already expects, checks every
precondition *before* asking for a signature, signs it with a key the operator
controls, registers it in the configuration and seals. Nothing here mints an
identity, relaxes a gate or decides anything on the reviewer's behalf.

What it refuses
---------------
* A decision that does not bind the current investigation head. If the record
  moved after the reviewer started reading, the signature would attest to
  something they did not see.
* A PASS on an ADVERSE or INCONCLUSIVE investigation, and an INCONCLUSIVE FAIL
  that does not carry the explicit assurance-only mapping. `seal` enforces this
  too; checking early means the reviewer sees why before signing, not after.
* An approver who is the same principal or key as the assessor or challenger.
* A synthetic investigation, and any run whose integrated gate is not clear.
* Overwriting an existing decision document.

The signing key is read through `operations.secrets.private_seed`, so it comes
from a file the reviewer owns at chmod 600, or an environment variable, or
whatever the caller has put behind that boundary. Point it at an HSM or KMS
before a decision anyone relies on.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from governance.investigation.store import canonical
from governance.operations.secrets import private_seed
from governance.result_contract import CanonicalSigner

UNQUALIFIED = "production_judgment_not_qualified"
PILOT_RELIANCE = "PILOT_DECISION_SUPPORT"

VERDICT_DECISIONS = {
    "ADVERSE": [("FAIL", False)],
    "INCONCLUSIVE": [("FAIL", True)],
    "PASS": [("PASS", False), ("CONDITIONAL_PASS", False), ("FAIL", False)],
}

DECISION_MEANING = {
    ("FAIL", False): "The control did not operate effectively in the assessed scope.",
    ("FAIL", True): "Assurance could not be obtained. This records an assurance failure, "
                    "not a finding that the control breached.",
    ("PASS", False): "The control operated effectively in the assessed scope.",
    ("CONDITIONAL_PASS", False): "Effective, subject to the recorded conditions.",
    ("NO_EXCEPTIONS_NOTED", True): "No exceptions noted for this period — assurance only. The tests found nothing in the "
                                   "checked, corroborated population. This is not a conclusion that the control is "
                                   "designed or operating effectively.",
}
# How a decision reads to a person. The verdict says what the machine found; the decision says what the human notes.
DECISION_LABEL = {("NO_EXCEPTIONS_NOTED", True): "No exceptions noted for this period (assurance only)"}


def approver_signer(config: dict, root: Path):
    """The reviewer's own key. Never generated here."""
    item = config["signers"]["result_approver"]
    signer = CanonicalSigner.from_base64(item["key_id"], private_seed(item, root))
    policy = config["trusted_keys"].get(signer.key_id, {})
    if policy.get("public_key") != signer.public_key_b64:
        raise ValueError("result approver key is not pinned by the trust policy")
    if "result_approver" not in policy.get("roles", []):
        raise ValueError("this identity does not hold the result_approver role")
    if policy.get("actor_type") != "human":
        raise ValueError("a result decision requires a human identity")
    return signer, policy


def preflight(config: dict, root: Path, investigation_id: str, engine, journal) -> dict:
    """Everything that must be true before a signature is worth asking for.

    Returns a report rather than raising, so a reviewer interface can show all
    the reasons at once instead of one per attempt.
    """
    return _preflight(config, root, investigation_id, engine, journal, pilot=False)


def _preflight(config: dict, root: Path, investigation_id: str, engine, journal, *, pilot: bool) -> dict:
    from governance.production.orchestrator import programme_gate
    from governance.production.qualification import check as check_qualification
    from governance.production.lifecycle import check_changes

    problems: list[str] = []
    rows, values = engine.snapshot(investigation_id)
    head = rows[-1]["record_hash"] if rows else None
    verdict = values["conclude"].verdict if "conclude" in values else None

    if len(rows) != 8:
        problems.append("The investigation has not reached all eight stages.")
    if "understand" in values and values["understand"].synthetic:
        problems.append("This is a synthetic investigation. It cannot produce a governance result.")

    quality = check_qualification(config, root)
    gate = programme_gate(engine, investigation_id, journal, quality,
                          config.get("operation_mode", "evaluation"), config)
    # A pilot attestation is the one place the unqualified-judgment blocker is
    # tolerated, because the attestation never becomes a governance result.
    # Every other gate blocker still stops it.
    tolerated = {UNQUALIFIED} if pilot else set()
    problems.extend(f"Gate: {token}" for token in gate.get("blockers", []) if token not in tolerated)

    if journal.latest("result_sealed"):
        problems.append("A result has already been sealed for this investigation.")
    if journal.latest("reassessment_requested"):
        problems.append("A reassessment has been requested. This result cannot be re-promoted.")

    try:
        signer, policy = approver_signer(config, root)
        approver = {"actor": policy["actor"], "key_id": signer.key_id}
        for role in ("assessor", "challenger"):
            other = config["trusted_keys"][config["signers"][role]["key_id"]]
            if policy["actor"] == other["actor"] or policy["public_key"] == other["public_key"]:
                problems.append(f"The approver is the same identity as the {role}. "
                                "A result decision must be independent of the agents it approves.")
    except Exception as exc:
        approver = None
        problems.append(f"Signing identity unavailable: {exc}")

    if config.get("result_decisions", {}).get(investigation_id):
        problems.append("A decision document is already registered for this investigation.")

    try:
        executor = _executor(config, root)
        changed = check_changes(config, root, investigation_id, engine, journal, executor)
        if changed["status"] == "INPUT_CHANGE_DETECTED":
            problems.extend(describe_changes(changed))
    except Exception as exc:
        problems.append(f"Change check unavailable: {exc}")

    return {
        "ready": not problems,
        "problems": problems,
        "investigation_head": head,
        "verdict": verdict,
        "approver": approver,
        "choices": [{"decision": d, "assurance_only_fail": a,
                     "meaning": DECISION_MEANING[(d, a)]}
                    for d, a in VERDICT_DECISIONS.get(verdict, [])],
    }


def _executor(config, root):
    from governance.production.lifecycle import actor_signer
    return actor_signer(config, root, "executor")


def build_payload(investigation_id: str, investigation_head: str, decision: str,
                  rationale: str, *, assurance_only_fail: bool = False,
                  decision_id: str | None = None, at: str | None = None) -> dict:
    """The exact shape `lifecycle.seal` validates."""
    rationale = rationale.strip()
    if len(rationale) < 20:
        raise ValueError("record a rationale a later reader can act on, not a placeholder")
    payload = {
        "investigation_id": investigation_id,
        "investigation_head": investigation_head,
        "decision": decision,
        "decision_id": decision_id or ("DEC-" + uuid.uuid4().hex[:16]),
        "at": at or datetime.now(timezone.utc).isoformat(),
        "rationale": rationale,
    }
    if assurance_only_fail:
        payload["assurance_only_fail"] = True
    return payload


def _check_decision(engine, investigation_id: str, payload: dict) -> str:
    """Head binding and verdict-to-decision mapping. Returns the verdict."""
    rows, values = engine.snapshot(investigation_id)
    if payload["investigation_head"] != rows[-1]["record_hash"]:
        raise ValueError("the investigation moved while you were deciding; re-read it before signing")
    verdict = values["conclude"].verdict
    allowed = VERDICT_DECISIONS.get(verdict, [])
    pair = (payload["decision"], bool(payload.get("assurance_only_fail")))
    if pair not in allowed:
        raise ValueError(f"a {verdict} investigation cannot carry decision {pair[0]}"
                         + (" without the assurance-only mapping" if verdict == "INCONCLUSIVE" else ""))
    return verdict


def _write_document(root: Path, relative: Path, document: dict) -> Path:
    target = Path(root) / relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(canonical(document))
        handle.flush()
        os.fsync(handle.fileno())
    return target


def sign_and_register(config_path: Path, config: dict, root: Path, investigation_id: str,
                      payload: dict, engine, journal) -> dict:
    """Sign the decision, write it, register it, then seal.

    The configuration write and the seal are separate steps on purpose. If the
    seal fails, the signed decision still exists on disk and can be inspected;
    nothing is silently discarded.
    """
    _check_decision(engine, investigation_id, payload)

    signer, _ = approver_signer(config, root)
    document = {"payload": payload, "key_id": signer.key_id,
                "signature": signer.sign(canonical(payload).encode())}

    relative = Path("decisions") / f"{investigation_id}-{payload['decision_id']}.json"
    target = _write_document(root, relative, document)

    config.setdefault("result_decisions", {})[investigation_id] = str(relative)
    config_path = Path(config_path)
    temporary = config_path.with_suffix(".decision.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(config_path)

    from governance.production.lifecycle import seal
    sealed = seal(config, root, investigation_id, engine, journal)
    return {"decision_document": str(target), "result": sealed}


# --------------------------------------------------------------------------
# pilot attestation
# --------------------------------------------------------------------------
#
# In evaluation mode the integrated gate always carries
# `production_judgment_not_qualified`, so `seal` can never run and a pilot
# would have no way to close its loop. An attestation closes it without
# weakening anything:
#
# * It is signed by the same human result_approver identity, bound to the same
#   investigation head, under the same verdict-to-decision mapping, after the
#   same preflight, with the single unqualified-judgment blocker tolerated and
#   every other blocker still enforced.
# * It records reliance as PILOT_DECISION_SUPPORT and governance_result False
#   inside the signed payload, so neither can be stripped without breaking the
#   signature.
# * It is written to the operational journal, never to result_decisions, and
#   `lifecycle.seal` refuses any approval that carries a pilot reliance marker.
#   An attestation cannot be promoted to a governance result.


def pilot_preflight(config: dict, root: Path, investigation_id: str, engine, journal) -> dict:
    report = _preflight(config, root, investigation_id, engine, journal, pilot=True)
    extra = []
    if config.get("operation_mode", "evaluation") != "evaluation":
        extra.append("Production configurations sign and seal a governance result. "
                     "Pilot attestation is for evaluation mode only.")
    if config.get("deployment_profile") != "pilot":
        extra.append("This configuration was not provisioned as a pilot. Use tools/gaar_pilot.py, "
                     "which accepts human keys rather than generating them.")
    if journal.latest("pilot_attestation"):
        extra.append("This investigation already carries a pilot attestation.")
    report["problems"] = extra + report["problems"]
    report["ready"] = not report["problems"]
    report["reliance"] = PILOT_RELIANCE
    return report


def attest(config: dict, root: Path, investigation_id: str, payload: dict, engine, journal) -> dict:
    """Sign a pilot decision and record it in the operational journal."""
    report = pilot_preflight(config, root, investigation_id, engine, journal)
    if not report["ready"]:
        raise ValueError("pilot attestation blocked: " + "; ".join(report["problems"]))
    verdict = _check_decision(engine, investigation_id, payload)
    signer, policy = approver_signer(config, root)
    attested = {**payload, "verdict": verdict, "approver": policy["actor"],
                "rationale_warnings": rationale_warnings(payload["decision"], payload.get("rationale", "")),
                "reliance": PILOT_RELIANCE, "governance_result": False, "deployment_authorized": False}
    document = {"payload": attested, "key_id": signer.key_id,
                "signature": signer.sign(canonical(attested).encode())}
    relative = Path("decisions") / f"{investigation_id}-{payload['decision_id']}.pilot.json"
    target = _write_document(root, relative, document)
    import hashlib
    event = journal.append("pilot_attestation", "pilot_attestation",
                           {"attestation": attested, "document_path": str(relative),
                            "document_sha256": hashlib.sha256(canonical(document).encode()).hexdigest()},
                           signer, "result_approver")
    return {"decision_document": str(target), "event_hash": event["event_hash"], "attestation": attested}


def existing_attestation(journal) -> dict | None:
    event = journal.latest("pilot_attestation")
    if not event:
        return None
    return {**event["payload"]["attestation"], "event_hash": event["event_hash"], "at_recorded": event["at"]}


# --------------------------------------------------------------------------
# reviewer interface
# --------------------------------------------------------------------------

CONFIRM_FULL = ("I have read the findings, the evidence behind them and the challenge, "
                "and I take accountability for this decision.")
CONFIRM_DETERMINISTIC = ("I have read the reconciled statuses, the deterministic findings and the evidence behind "
                         "them, and I take accountability for this decision.")
CONFIRM_DETERMINISTIC_COVERAGE = ("I have read the reconciled statuses, the deterministic findings, the coverage "
                                  "statements and the evidence behind them, and I take accountability for this decision.")


CONFIRM_NO_EXCEPTIONS = ("I have read the reconciled statuses, the coverage statements and the evidence behind them; "
                         "no findings were raised this period; I take accountability for this decision.")


def deterministic_confirm_text(journal) -> str:
    """The signed sentence names exactly what the record contains."""
    report = _deterministic_report(journal)
    if report and report.get("deterministic_verdict") == "NO_EXCEPTIONS_FOUND":
        return CONFIRM_NO_EXCEPTIONS
    rec = (journal.latest("obligation_reconciliation") or {}).get("payload", {})
    if (rec.get("coverage") or {}).get("status") == "COMPUTED_ON_SUPPLIED_EXPORTS":
        return CONFIRM_DETERMINISTIC_COVERAGE
    return CONFIRM_DETERMINISTIC


CHANGE_WORDS = {
    "code_sha256": ("the GaaR software was updated after this run",
                    "Rerun this period under the current version (runbook U1: attest outstanding results before upgrading)."),
    "knowledge_sha256": ("the dependency knowledge base changed", "Rerun under the current knowledge base."),
    "models_sha256": ("the model configuration changed", "Rerun under the current model configuration."),
    "trust_sha256": ("the trusted signing identities changed", "Confirm the key change was authorised, then rerun."),
    "operating_scope_sha256": ("the approved sources or collectors changed", "Confirm the change was authorised, then rerun."),
    "quality_policy_sha256": ("the quality policy changed", "Rerun under the current policy."),
}


def describe_changes(result: dict) -> list[str]:
    """Say which bound part changed, and what to do. A software upgrade is not tampered evidence."""
    lines = []
    for key, value in (result.get("changes") or {}).items():
        if key == "operating_configuration":
            for part in value if isinstance(value, list) else [value]:
                what, action = CHANGE_WORDS.get(part, (f"bound configuration part {part} changed", "Rerun this period."))
                lines.append(f"Blocked because {what}. {action}")
        elif value == "UNAVAILABLE":
            lines.append(f"Blocked because evidence export {key} is missing since this run. "
                         "Treat this as a potential integrity event (runbook E1): find out who removed it and why.")
        else:
            lines.append(f"Blocked because evidence export {key} was changed after this run. "
                         "Treat this as a potential integrity event (runbook E1): find out who changed it and why.")
    return lines or ["Bound evidence or configuration changed since this run."]


APPROVAL_CLAIMS = (r"\b(control|it)\s+(is|was|remains)\s+(effective|compliant|operating effectively)\b",
                   r"\b(no|zero)\s+(issues|exceptions|findings|problems)\b", r"\bpass(ed|es)?\b",
                   r"\boperat(ed|es|ing)\s+effectively\b")
PROCEED_CLAIMS = (r"\b(ok|okay|fine|good|clear|time)\s+to\s+(proceed|go)\b", r"\bgo\s+ahead\b",
                  r"\bapproved?\b(?!\s+(pending|subject|with|on condition))")
QUALIFIERS = r"\b(pending|remediat|condition|subject to|until|exception|risk accept|accepted for continued)"


def rationale_warnings(decision: str, text: str) -> list[str]:
    """Flag, never block, rationale wording that contradicts a FAIL decision."""
    import re
    if decision != "FAIL" or not text:
        return []
    lowered = text.lower()
    negated = re.sub(r"\b(not|in|non)[\s-]*(effective|compliant)", "", lowered)
    warnings = []
    if any(re.search(p, negated) for p in APPROVAL_CLAIMS):
        warnings.append("This rationale reads as saying the control passed or was effective, but the decision is FAIL.")
    if any(re.search(p, lowered) for p in PROCEED_CLAIMS) and not re.search(QUALIFIERS, lowered):
        warnings.append("This rationale reads as unqualified approval to proceed on a failed control. If you are "
                        "accepting the risk, say on what condition or pending what remediation.")
    return warnings


def local_time(stamp: str) -> str:
    """Show a signed timestamp in local time with its offset, so no reader has to guess the clock."""
    from datetime import datetime
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp
    if moment.tzinfo is None:
        return stamp + " (time zone not recorded)"
    local = moment.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S ") + (local.tzname() or "") + local.strftime(" (UTC%z)")


def _decision_form(st, report: dict, key: str, confirm_text: str = CONFIRM_FULL, read: str | None = None):
    """`read` names the record on screen. The confirmation is keyed to it, so if the record is replaced while the
    reviewer reads (a U1 rerun by the scheduler), the confirmation resets and must be given again."""
    labels = {DECISION_LABEL.get((c["decision"], c["assurance_only_fail"]),
                                 f"{c['decision']}{' (assurance only)' if c['assurance_only_fail'] else ''}"): c
              for c in report["choices"]}
    if not labels:
        st.error(f"No decision is permitted for a {report['verdict']} investigation.")
        return None
    chosen = labels[st.radio("Decision", list(labels), horizontal=True, key=f"{key}-decision")]
    st.info(chosen["meaning"])
    rationale = st.text_area("Your rationale", key=f"{key}-rationale", height=120,
                             placeholder="Which obligations and findings drove this decision, and what must "
                                         "happen next. Write it for a reader in a year.")
    for warning in rationale_warnings(chosen["decision"], rationale):
        st.warning(warning + " You can still sign; the rationale is yours.")
    confirm = st.checkbox(confirm_text, key=f"{key}-confirm" + (f"-{read[:16]}" if read else ""))
    return chosen, rationale, confirm


def render_panel(st, config_path: Path, config: dict, root: Path,
                 investigation_id: str, engine, journal):
    """Streamlit panel for the one human step. Seal in production, attest in a pilot."""
    mode = config.get("operation_mode", "evaluation")
    from governance.production.completion import enabled as completion_enabled
    if completion_enabled(config) and journal.latest("model_stage_unavailable"):
        _render_attest_deterministic(st, config, root, investigation_id, engine, journal)
        return
    if mode == "production":
        _render_seal(st, config_path, config, root, investigation_id, engine, journal)
    elif config.get("deployment_profile") == "pilot":
        _render_attest(st, config, root, investigation_id, engine, journal)
    else:
        st.markdown("### Sign the result")
        st.info("This is an evaluation demonstration. Its identities are generated service keys and its "
                "evidence is marked synthetic, so nothing here can be signed by a person. "
                "Provision a pilot with tools/gaar_pilot.py to review real evidence and attest.")


def _render_seal(st, config_path, config, root, investigation_id, engine, journal):
    st.markdown("### Sign the result")
    try:
        report = preflight(config, root, investigation_id, engine, journal)
    except Exception as exc:
        st.error(f"Cannot check whether this is ready to sign — {type(exc).__name__}: {exc}")
        return
    if not report["ready"]:
        st.warning("This result cannot be signed yet.")
        for problem in report["problems"]:
            st.markdown(f"- {problem}")
        return
    approver = report["approver"]
    st.caption(f"Signing as **{approver['actor']}** using key `{approver['key_id']}`. "
               f"Binding investigation head `{report['investigation_head'][:20]}…`")
    form = _decision_form(st, report, "seal")
    if not form:
        return
    chosen, rationale, confirm = form
    if st.button("Sign and seal", type="primary", disabled=not confirm):
        try:
            payload = build_payload(investigation_id, report["investigation_head"],
                                    chosen["decision"], rationale,
                                    assurance_only_fail=chosen["assurance_only_fail"])
            outcome = sign_and_register(config_path, config, root, investigation_id,
                                        payload, engine, journal)
        except Exception as exc:
            st.error(f"Not signed — {type(exc).__name__}: {exc}")
            return
        result = outcome["result"]
        st.success(f"Sealed. Result `{result['result_id']}` is {result['state']}, "
                   f"decision {result['decision']}.")
        st.caption(f"Decision document: {outcome['decision_document']}. "
                   "Deployment authorisation is not granted by sealing a result.")


def _render_attest(st, config, root, investigation_id, engine, journal):
    st.markdown("### Attest this pilot result")
    done = existing_attestation(journal)
    if done:
        st.success(f"Attested by **{done['approver']}**: {done['decision']} on a {done['verdict']} "
                   f"investigation, {local_time(done['at'])}.")
        st.caption(f"Reliance: pilot decision support. Not a governance result. "
                   f"Journal event `{done['event_hash'][:20]}…`")
        st.write(done["rationale"])
        return
    try:
        report = pilot_preflight(config, root, investigation_id, engine, journal)
    except Exception as exc:
        st.error(f"Cannot check whether this is ready to attest — {type(exc).__name__}: {exc}")
        return
    st.caption("A pilot attestation is your signed decision on this run. The model judgment behind it has "
               "not been independently qualified, so it is recorded as decision support and cannot become "
               "a sealed governance result.")
    if not report["ready"]:
        st.warning("This result cannot be attested yet.")
        for problem in report["problems"]:
            st.markdown(f"- {problem}")
        return
    approver = report["approver"]
    st.caption(f"Signing as **{approver['actor']}** using key `{approver['key_id']}`. "
               f"Binding investigation head `{report['investigation_head'][:20]}…`")
    form = _decision_form(st, report, "attest")
    if not form:
        return
    chosen, rationale, confirm = form
    if st.button("Sign attestation", type="primary", disabled=not confirm):
        try:
            payload = build_payload(investigation_id, report["investigation_head"],
                                    chosen["decision"], rationale,
                                    assurance_only_fail=chosen["assurance_only_fail"])
            outcome = attest(config, root, investigation_id, payload, engine, journal)
        except Exception as exc:
            st.error(f"Not signed — {type(exc).__name__}: {exc}")
            return
        st.success(f"Attested: {outcome['attestation']['decision']}. Recorded as pilot decision support.")
        st.caption(f"Document: {outcome['decision_document']}")


# --------------------------------------------------------------------------
# attestation on a deterministic record (model stage unavailable)
# --------------------------------------------------------------------------
#
# When a model stage failed and the run completed deterministically, there is no
# eight-stage record to attest. The human attests the deterministic record
# instead: D8's reconciled statuses and the executed procedures. The decision
# can only be FAIL (ADVERSE) or assurance-only FAIL (INCONCLUSIVE), because a
# record without a completed model assessment cannot establish PASS. The same
# reliance markers keep it out of result sealing.

DETERMINISTIC_DECISIONS = {"ADVERSE": [("FAIL", False)], "INCONCLUSIVE": [("FAIL", True)],
                           "NO_EXCEPTIONS_FOUND": [("NO_EXCEPTIONS_NOTED", True)]}   # never PASS; see coverage design note


def _deterministic_report(journal):
    event = next((e for e in journal.read() if e["event_key"] == "deterministic_run_report"), None)
    return event["payload"] if event else None


def deterministic_preflight(config: dict, root: Path, investigation_id: str, engine, journal) -> dict:
    problems: list[str] = []
    record = _deterministic_report(journal)
    rows, values = engine.snapshot(investigation_id)
    head = rows[-1]["record_hash"] if rows else None
    if not record:
        problems.append("No deterministic record exists for this investigation.")
    if config.get("operation_mode", "evaluation") != "evaluation":
        problems.append("Deterministic records are attested in evaluation mode only.")
    if config.get("deployment_profile") != "pilot":
        problems.append("This configuration was not provisioned as a pilot.")
    if values.get("understand") is not None and values["understand"].synthetic:
        problems.append("This is a synthetic investigation. It cannot be attested.")
    if record and record.get("investigation_head") != head:
        problems.append("The signed record changed after the deterministic record was made.")
    if journal.latest("pilot_attestation"):
        problems.append("This investigation already carries a pilot attestation.")
    approver = None
    try:
        signer, policy = approver_signer(config, root)
        approver = {"actor": policy["actor"], "key_id": signer.key_id}
        for role in ("assessor", "challenger"):
            other = config["trusted_keys"][config["signers"][role]["key_id"]]
            if policy["actor"] == other["actor"] or policy["public_key"] == other["public_key"]:
                problems.append(f"The approver is the same identity as the {role}.")
    except Exception as exc:
        problems.append(f"Signing identity unavailable: {exc}")
    try:
        from governance.production.lifecycle import check_changes
        changed = check_changes(config, root, investigation_id, engine, journal, _executor(config, root))
        if changed["status"] == "INPUT_CHANGE_DETECTED":
            problems.extend(describe_changes(changed))
    except Exception as exc:
        problems.append(f"Change check unavailable: {exc}")
    verdict = (record or {}).get("deterministic_verdict")
    if verdict == "NO_EXCEPTIONS_FOUND":
        rec = (journal.latest("obligation_reconciliation") or {}).get("payload", {})
        if not (rec.get("coverage") or {}).get("corroborated") or any(
                o["governed_status"] != "NO_EXCEPTIONS_FOR_PERIOD" for o in rec.get("obligations", [])):
            problems.append("This record is not eligible for 'no exceptions noted': every obligation must be clean "
                            "with corroborated coverage.")
    return {"ready": not problems, "problems": problems, "investigation_head": head, "verdict": verdict,
            "approver": approver, "record": record,
            "choices": [{"decision": d, "assurance_only_fail": a, "meaning": DECISION_MEANING[(d, a)]}
                        for d, a in DETERMINISTIC_DECISIONS.get(verdict, [])]}


def attest_deterministic(config: dict, root: Path, investigation_id: str, payload: dict, engine, journal) -> dict:
    report = deterministic_preflight(config, root, investigation_id, engine, journal)
    if not report["ready"]:
        raise ValueError("deterministic attestation blocked: " + "; ".join(report["problems"]))
    if payload["investigation_head"] != report["investigation_head"]:
        raise ValueError("the investigation moved while you were deciding; re-read it before signing")
    pair = (payload["decision"], bool(payload.get("assurance_only_fail")))
    if pair not in DETERMINISTIC_DECISIONS.get(report["verdict"], []):
        raise ValueError(f"a deterministic {report['verdict']} record cannot carry decision {pair[0]}"
                         + ("" if report["verdict"] != "INCONCLUSIVE" else " without the assurance-only mapping"))
    signer, policy = approver_signer(config, root)
    record = report["record"]
    attested = {**payload, "verdict": report["verdict"], "approver": policy["actor"],
                "record_basis": "DETERMINISTIC_RECORD",
                "reconciliation_event_hash": record["reconciliation_event_hash"],
                "model_stage_unavailable": record["model_stage_unavailable"]["stage"],
                "models_disabled_by_configuration": bool(record["model_stage_unavailable"].get("disabled_by_configuration")),
                # A simulated clock must be visible in the signature itself, not only in the record it signs.
                "clock_simulated": (journal.latest("obligation_reconciliation") or {}).get("payload", {}).get("clock_simulated"),
                "reviewer_confirmed": deterministic_confirm_text(journal),
                # Warnings shown at signing are evidence about the attestation itself, so they are signed with it.
                "rationale_warnings": rationale_warnings(payload["decision"], payload.get("rationale", "")),
                "reliance": PILOT_RELIANCE, "governance_result": False, "deployment_authorized": False}
    document = {"payload": attested, "key_id": signer.key_id,
                "signature": signer.sign(canonical(attested).encode())}
    relative = Path("decisions") / f"{investigation_id}-{payload['decision_id']}.deterministic.json"
    target = _write_document(root, relative, document)
    import hashlib
    event = journal.append("pilot_attestation", "pilot_attestation",
                           {"attestation": attested, "document_path": str(relative),
                            "document_sha256": hashlib.sha256(canonical(document).encode()).hexdigest()},
                           signer, "result_approver")
    return {"decision_document": str(target), "event_hash": event["event_hash"], "attestation": attested}


def _render_attest_deterministic(st, config, root, investigation_id, engine, journal):
    st.markdown("### Attest the deterministic record")
    done = existing_attestation(journal)
    if done:
        shown = DECISION_LABEL.get((done["decision"], bool(done.get("assurance_only_fail"))), done["decision"])
        clock = (f" Assessed under a simulated clock ({done['clock_simulated']}), recorded in this attestation."
                 if done.get("clock_simulated") else "")
        st.success(f"Attested by **{done['approver']}**: {shown} on a deterministic "
                   f"{done['verdict']} record, {local_time(done['at'])}.{clock}")
        st.caption("Reliance: pilot decision support. Not a governance result.")
        st.write(done["rationale"])
        return
    report = deterministic_preflight(config, root, investigation_id, engine, journal)
    disabled = bool((journal.latest("model_stage_unavailable") or {}).get("payload", {}).get("disabled_by_configuration"))
    st.caption("You are attesting what the deterministic tests and the reconciliation show. "
               + ("Model stages are switched off for this pilot, so no model was asked anything. "
                  if disabled else "A model stage failed, so its answer is not part of this record. ")
               + "This record can support FAIL or assurance-only FAIL, never PASS.")
    if not report["ready"]:
        st.warning("This record cannot be attested yet.")
        for problem in report["problems"]:
            st.markdown(f"- {problem}")
        return
    approver = report["approver"]
    st.caption(f"Signing as **{approver['actor']}** using key `{approver['key_id']}`.")
    simulated = (journal.latest("obligation_reconciliation") or {}).get("payload", {}).get("clock_simulated")
    if simulated:
        st.warning(f"**Simulated clock (constructed demonstration).** This record was assessed as of {simulated}, not "
                   "in real time. Your attestation will record that.")
    if report["verdict"] == "NO_EXCEPTIONS_FOUND":
        st.info("The tests found no exceptions in the checked, corroborated population for this period. You can note "
                "that; it is not a conclusion that the control is designed and operating effectively, and it is never PASS.")
    form = _decision_form(st, report, "deterministic", deterministic_confirm_text(journal),
                          read=report["record"].get("reconciliation_event_hash"))
    if not form:
        return
    chosen, rationale, confirm = form
    if st.button("Sign attestation", type="primary", disabled=not confirm, key="deterministic-sign"):
        try:
            payload = build_payload(investigation_id, report["investigation_head"], chosen["decision"], rationale,
                                    assurance_only_fail=chosen["assurance_only_fail"])
            outcome = attest_deterministic(config, root, investigation_id, payload, engine, journal)
        except Exception as exc:
            st.error(f"Not signed — {type(exc).__name__}: {exc}")
            return
        st.success(f"Attested: {outcome['attestation']['decision']} on the deterministic record.")
