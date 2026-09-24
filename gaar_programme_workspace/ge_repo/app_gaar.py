#!/usr/bin/env python3
"""GaaR — one-click governance.

The whole app is one loop: pick an assessment, press Run, read the result,
follow any claim back to the exact bytes it came from.

Everything the machine can do without a human, it does. The only things that
stop and ask are the things a human must actually own: authorising scope,
approving a source, disposing of a material risk, and signing a result. Those
arrive as a single card that says exactly what is needed.

Run with:
    streamlit run app_gaar.py
Environment:
    WB_INVESTIGATION_CONFIG   path to the operating configuration JSON
"""

from __future__ import annotations

import json
import hmac
import os
import sqlite3
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from governance import trace as tracelib
from governance import decisions

st.set_page_config(page_title="GaaR — governance results", page_icon="🛡️", layout="wide")

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1180px;}
.chip {display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.78rem;
       font-weight:600; letter-spacing:.02em;}
.chip-adverse {background:#fdecea; color:#a61b1b;}
.chip-pass {background:#e7f5ec; color:#14663a;}
.chip-inconclusive {background:#fff5e0; color:#8a5a00;}
.chip-blocked {background:#eef0f4; color:#3d4756;}
.chip-attested {background:#e8eefb; color:#1f3f8a;}
.verdict {font-size:1.9rem; font-weight:700; margin:0 0 .15rem 0;}
.sub {color:#5b6472; font-size:0.94rem;}
.card {border:1px solid #e3e6ec; border-radius:10px; padding:14px 16px; margin-bottom:10px;}
.card-material {border-left:4px solid #c0392b;}
.card-minor {border-left:4px solid #b9bec7;}
.mono {font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:0.78rem; color:#5b6472;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

VERDICT_CLASS = {"ADVERSE": "chip-adverse", "PASS": "chip-pass", "INCONCLUSIVE": "chip-inconclusive"}
REVIEWER_POLICY = {"show_sensitive_evidence": False, "show_raw_model_io": False,
                   "allow_trace_download": False, "reveal_on_request": True}

SOURCE_STATUS_TEXT = {
    "GOVERNANCE_DECISION_ON_FILE": "governance approved",
    "EVALUATION_FIXTURE_NOT_GOVERNANCE_APPROVED": "FIXTURE — not governance approved",
    "APPROVAL_NOT_RECORDED": "approval not recorded",
    "UNREGISTERED": "not in source registry",
    "NOT_CHECKED": "not checked",
}


def visible(flag: str) -> bool:
    """Policy default, or an explicit reveal in this reviewer session."""
    key = f"revealed:{st.session_state.get('current_investigation')}:{flag}"
    return bool(REVIEWER_POLICY.get(flag)) or bool(st.session_state.get(key))


def record_reveal(case_dir: str, investigation_id: str, flags: list[str]):
    """Append-only local access record. Unsigned: it evidences use, not identity."""
    import getpass
    from datetime import datetime, timezone
    entry = {"at": datetime.now(timezone.utc).isoformat(), "investigation_id": investigation_id,
             "revealed": flags, "os_user": getpass.getuser(),
             "session": "token-authenticated" if REVIEWER_POLICY.get("access_token_env") else "local"}
    path = Path(case_dir) / "reviewer_access.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


ASSESSOR_LABEL = {"MODEL_UNAVAILABLE": "not available (model stage failed)"}


def coverage_text(o: dict, rec: dict) -> str:
    cov = o.get("coverage")
    if not cov:
        return "—"
    most = max((c.get("applied_to") or 0) for c in cov.values())
    violated = sum(c.get("violations") or 0 for c in cov.values())
    corroborated = (rec.get("coverage") or {}).get("corroborated")
    return (f"up to {most} record(s) checked, {violated} violation(s)"
            + ("" if corroborated else " · not corroborated"))


def render_reconciliation(rec: dict, models_disabled: bool = False):
    """D8: what the deterministic tests say about each obligation, against what the assessor said."""
    if not rec:
        return

    def assessor(status):
        if status == "MODEL_UNAVAILABLE" and models_disabled:
            return "not asked (models off)"
        return ASSESSOR_LABEL.get(status, status)
    count = rec.get("false_assurance_count", 0)
    if count:
        st.error(f"The assessor marked {count} obligation{'s' if count != 1 else ''} SUPPORTED that the deterministic "
                 "tests contradict or cannot support. The recorded status is the reconciled one; the assessor's "
                 "claim is kept for audit.")
    st.subheader("Reconciled against the deterministic tests")
    st.dataframe([{"Obligation": o["element_id"], "Recorded status": o["governed_status"],
                   "Assessor said": assessor(o["assessor_status"]), "Why": {
                       "DETERMINISTIC_DISCREPANCY": "a test found a record that contradicts it",
                       "DETERMINISTIC_ASSURANCE_GAP": "a record needed to decide is missing",
                       "ASSESSOR_UNCHALLENGED": "no test finding; assessor's status stands",
                       "UNMAPPED": "no test mapped to this obligation",
                       "NO_FINDING_NO_ASSESSOR": "no test finding this period; not assessed by a model",
                       "PROCEDURE_DID_NOT_RUN": "the check behind this obligation did not run",
                       "EMPTY_POPULATION": "checked 0 of 0 — usually a broken collector, never a clean result",
                       "COVERAGE_CORROBORATED": "checked, none violated — clean for this period only",
                       "NO_APPLICABLE_EVENTS": "nothing to breach this period (e.g. no freeze, no failed change)",
                       "COVERAGE_UNCORROBORATED": "checked, none violated — a claim: population not corroborated",
                       }.get(o["basis"], o["basis"]),
                   "Coverage": coverage_text(o, rec),
                   "Findings": len(o["issue_ids"])} for o in rec.get("obligations", [])],
                 width="stretch", hide_index=True)
    if rec.get("clock_simulated"):
        st.warning(f"**Simulated clock (constructed demonstration):** assessed as of {rec['clock_simulated']}, not in "
                   "real time. Timing in this record is a demonstration, not an observation.")
    cov = rec.get("coverage") or {}
    if cov.get("status") == "COMPUTED_ON_SUPPLIED_EXPORTS":
        st.caption(("Coverage corroborated: " if cov.get("corroborated") else "Coverage NOT corroborated: ")
                   + cov.get("reason", "") + ". Coverage says what the checks applied to; it is not a conclusion "
                   "on control design or effectiveness.")
    elif cov:
        st.caption("No coverage statement: " + cov.get("reason", cov.get("status", "unknown")))
    signer = rec.get("mapping_signed_by")
    if signer:
        st.caption(f"Obligation-to-test mapping signed by **{signer}** (document "
                   f"{(rec.get('mapping_document_sha256') or '')[:12]}…). It decides which findings count against which obligation.")
    else:
        st.warning("The obligation-to-test mapping behind these statuses is not signed by governance.")
    if rec.get("mapping_reviewed_by"):
        line = (f"Mapping independently reviewed by **{rec['mapping_reviewed_by']}**: "
                f"{rec.get('mapping_review_outcome')} (review {(rec.get('mapping_review_sha256') or '')[:12]}…).")
        (st.warning if rec.get("mapping_review_outcome") != "AGREED" else st.caption)(
            line + (" Changes were requested; do not rely on this series until they are resolved."
                    if rec.get("mapping_review_outcome") != "AGREED" else ""))
    elif signer:
        st.caption("Mapping not yet independently reviewed (quality policy §6.4): signed, but no second person has "
                   "recorded a review.")
    with st.expander(f"Deterministic findings ({len(rec.get('issues', []))}), each with a local remediation action"):
        st.dataframe([{"Obligation": i["element_id"], "Record": i.get("event_id") or i["evidence_id"],
                       "Finding": i["code"], "Type": "discrepancy" if i["class"] == "discrepancy" else "assurance gap",
                       "Test": i["procedure"]} for i in rec.get("issues", [])], width="stretch", hide_index=True)
        if rec.get("unmapped_codes"):
            st.warning("Findings with no obligation mapped: " + ", ".join(rec["unmapped_codes"]))
        bound = (f"signed examine record {rec['examine_record_hash'][:16]}…" if rec.get("examine_record_hash")
                 else f"signed evidence manifest {(rec.get('evidence_manifest_event_hash') or '')[:16]}…")
        st.caption(f"Bound to {bound} · mapping "
                   f"{rec.get('mapping_sha256', '')[:12]}… · journal event {(rec.get('event_hash') or '')[:16]}…")


def render_reveal(trace: dict):
    hidden = [flag for flag in ("show_sensitive_evidence", "show_raw_model_io") if not visible(flag)]
    if not hidden or not REVIEWER_POLICY.get("reveal_on_request", True):
        return
    left, right = st.columns([3, 1])
    with left:
        st.caption("Evidence text and model reasoning are hidden until you open them. Opening them is "
                   "recorded in this case's access log with your OS user and the time.")
    with right:
        if st.button("Open evidence and reasoning", width="stretch"):
            record_reveal(trace["case_dir"], trace["investigation_id"], hidden)
            for flag in hidden:
                st.session_state[f"revealed:{trace['investigation_id']}:{flag}"] = True
            st.rerun()

# Plain-English translations of gate blockers. A reviewer should never have to
# read a machine token to find out what is holding their result.
BLOCKER_TEXT = {
    "production_judgment_not_qualified":
        "This is an evaluation run. The model judgment behind it has not been independently qualified, so it cannot become a production governance result.",
    "integrated_gate_required":
        "The integrated gate has not run yet.",
    "dependency_treatments_missing":
        "The dependency review has not been recorded for this run.",
    "challenge_did_not_bind_dependency_review":
        "The challenger did not review the dependency treatments that were actually used.",
    "dependency_knowledge_version_changed":
        "The dependency knowledge base changed after this run started. The run must be repeated against the current version.",
    "element_examination_not_evaluated":
        "At least one obligation was never examined.",
    "broader_risk_review_incomplete":
        "The explanation stage did not complete.",
    "independent_challenge_incomplete":
        "The independent challenge did not complete.",
    "passing_conclusion_requires_human_decision_identity":
        "A passing conclusion cannot be signed by an automated identity. A named human must sign it.",
    "investigation_stages_incomplete":
        "The investigation has not reached all eight stages.",
}


def explain_blocker(token: str) -> str:
    if token in BLOCKER_TEXT:
        return BLOCKER_TEXT[token]
    if token.startswith("retrieval:"):
        _, lane, status = (token.split(":") + ["", ""])[:3]
        return f"The {lane} retrieval lane came back {status.lower()}. The assessor did not have that input."
    if token.startswith("test:"):
        parts = token.split(":")
        return f"Required test {parts[1]} did not execute ({parts[-1].lower()})."
    if token.startswith("material_risk_undispositioned:"):
        return f"Risk {token.split(':', 1)[1]} has no recorded disposition."
    if token.startswith("escalation_incomplete:"):
        return f"Risk {token.split(':', 1)[1]} has no completed escalation."
    if token.startswith("dependency_material_risk_undispositioned:"):
        return f"Dependency {token.split(':', 1)[1]} was marked material but its risk has no disposition."
    if token.startswith("pass_conflicts_with_executed_procedure:"):
        return f"A passing conclusion contradicts the output of executed test {token.split(':', 1)[1]}."
    return token.replace("_", " ").capitalize() + "."


# --------------------------------------------------------------------------
# configuration and portfolio
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def read_config(path_text: str, modified: float = 0.0):
    """`modified` is the file's mtime, so a re-provisioned workspace is never served from cache."""
    path = Path(path_text).expanduser().resolve()
    config = json.loads(path.read_text())
    return config, path.parent


def config_path() -> Path:
    return Path(os.environ.get("WB_INVESTIGATION_CONFIG", ROOT / "config/programme_operations.json"))


def authorized_investigations(config, root) -> list[str]:
    store = Path(root) / config.get("store", "")
    if not store.is_file():
        return []
    with sqlite3.connect(store) as db:
        return [r[0] for r in db.execute(
            "SELECT DISTINCT investigation_id FROM stages ORDER BY investigation_id")]


def portfolio(config, root) -> list[dict]:
    """One row per authorized assessment, joined with whatever the last run left."""
    programme_dir = Path(root) / config.get("programme_dir", "../var/programme")
    by_id = {c["investigation_id"]: c for c in tracelib.discover_cases(programme_dir) if c.get("investigation_id")}
    rows = []
    for iid in authorized_investigations(config, root):
        case = by_id.get(iid, {})
        rows.append({
            "investigation_id": iid,
            "case_dir": case.get("case_dir") or tracelib.case_directory(programme_dir, iid),
            "checkpoint": case.get("checkpoint", "NOT_RUN"),
            "verdict": case.get("verdict"),
            "system_id": case.get("system_id") or context_of(config, root, iid).get("system_id"),
            "control_id": case.get("control_id") or context_of(config, root, iid).get("control_id"),
            "updated_at": case.get("updated_at"),
            "has_snapshot": case.get("has_snapshot", False),
            "request": case.get("request"),
            "attestation": _attestation_of(config, case.get("case_dir") or tracelib.case_directory(programme_dir, iid)),
        })
    return rows


def _attestation_of(config, case_dir):
    """The signed attestation on a case, read through the verified journal; None if there is none."""
    path = Path(case_dir) / "operations.sqlite"
    if not path.is_file():
        return None
    try:
        from governance.production.journal import Journal
        event = Journal(path, config["trusted_keys"]).latest("pilot_attestation")
    except Exception:
        return None
    return event["payload"]["attestation"] if event else None


@st.cache_data(show_spinner=False)
def context_of(_config, _root, iid: str) -> dict:
    """Read scope straight from the signed first stage, without keys."""
    store = Path(_root) / _config.get("store", "")
    if not store.is_file():
        return {}
    try:
        with sqlite3.connect(store) as db:
            row = db.execute(
                "SELECT envelope FROM stages WHERE investigation_id=? AND sequence=0", (iid,)).fetchone()
        payload = json.loads(row[0])["payload"] if row else {}
        return {"system_id": payload.get("scope", {}).get("system_id"),
                "control_id": payload.get("control_id"),
                "period": payload.get("scope", {}).get("period"),
                "owner": payload.get("owner")}
    except (OSError, ValueError, KeyError):
        return {}


def run_investigation(config, root, iid: str) -> dict:
    from governance.production.orchestrator import run
    return run(config, root, iid)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def status_chip(row: dict) -> str:
    signed = row.get("attestation")
    if signed:
        from governance.decisions import DECISION_LABEL
        shown = DECISION_LABEL.get((signed["decision"], bool(signed.get("assurance_only_fail"))), signed["decision"])
        clock = " · simulated clock" if signed.get("clock_simulated") else ""
        return f'<span class="chip chip-attested">attested — {shown}{clock}</span>'
    verdict = row.get("verdict")
    if verdict in VERDICT_CLASS:
        return f'<span class="chip {VERDICT_CLASS[verdict]}">{verdict}</span>'
    label = {"NOT_RUN": "not run yet", "ACTION_REQUIRED": "waiting on you",
             "DETERMINISTIC_COMPLETE": "deterministic record — attest"}.get(
        row.get("checkpoint"), (row.get("checkpoint") or "unknown").replace("_", " ").lower())
    return f'<span class="chip chip-blocked">{label}</span>'


def render_request(request: dict):
    """The single card that says what a human must supply."""
    kind = request.get("kind", "Request")
    friendly = {"EvidenceRequest": "Evidence needed",
                "AuthorizationRequest": "Authorisation needed",
                "ServiceRequest": "A service is unavailable",
                "IntegrityRequest": "Integrity check needed"}.get(kind, kind)
    st.warning(f"**{friendly}** — {request.get('reason', '')}")
    st.markdown("**To continue, supply:**")
    for item in request.get("required_items", []):
        st.markdown(f"- {item}")
    if request.get("retry_safe"):
        st.caption("Once that is in place, press Run again. Completed stages are not repeated and the model is not re-invoked for them.")
    else:
        st.caption("This one needs a named person to authorise it. It cannot be retried by pressing Run again.")


def render_evidence(record: dict, key: str):
    st.markdown(
        f'<span class="mono">source {record["source_id"]} · bytes {record["start"]}–{record["end"]} · '
        f'sha256 {record["content_sha256"][:16]}… · {record["authority"]} · '
        f'{", ".join(record.get("purposes", []))} · integrity {record["integrity_status"]}</span>',
        unsafe_allow_html=True)
    if visible("show_sensitive_evidence"):
        st.code(tracelib.evidence_quote(record), language="text")
    else:
        st.caption("Evidence text is hidden. Open evidence and reasoning above to read the admitted bytes.")


def render_test(test: dict):
    icon = {"EXECUTED": "✅", "UNAVAILABLE": "⚠️", "NOT_EVALUATED": "—"}.get(test["status"], "—")
    st.markdown(f"{icon} **{test['tool']} v{test['version']}** — {test['status'].lower()}")
    if test.get("why"):
        st.caption(f"Run because: {test['why']}")
    if test.get("findings"):
        st.markdown(f"**{len(test['findings'])} discrepancy finding(s):**")
        st.dataframe(test["findings"], width="stretch", hide_index=True)
    if test.get("assurance_gaps"):
        st.markdown(f"**{len(test['assurance_gaps'])} assurance gap(s)** — absence of a record, not proof of breach:")
        st.dataframe(test["assurance_gaps"], width="stretch", hide_index=True)
    if not test.get("findings") and not test.get("assurance_gaps") and test["status"] == "EXECUTED":
        st.success("Executed with no discrepancies and no gaps, within the supplied record scope.")
    if test.get("limitation"):
        st.caption(f"Limitation: {test['limitation']}")
    st.markdown(
        f'<span class="mono">input evidence {test.get("input_evidence")} · '
        f'implementation sha256 {(test.get("implementation_sha256") or "")[:16]}…</span>',
        unsafe_allow_html=True)


def render_risk(risk, index: int):
    tone = "card-material" if risk.material else "card-minor"
    tag = "MATERIAL" if risk.material else "noted"
    st.markdown(
        f'<div class="card {tone}"><b>{risk.ref} · {risk.origin}</b> '
        f'<span class="chip chip-blocked">{tag}</span><br>{risk.claim}</div>',
        unsafe_allow_html=True)

    tabs = st.tabs(["Evidence behind it", "Tests run", "Alternatives considered",
                    "Dependencies", "What was decided"])

    with tabs[0]:
        if not risk.basis:
            st.info("No basis references were recorded for this claim.")
        for item in risk.basis:
            if item.kind == "evidence":
                st.markdown(f"**{item.label}**")
                render_evidence(item.detail, f"{index}-{item.ref}")
            elif item.kind == "gap":
                st.markdown(f"**{item.label}**")
                st.info(item.detail.get("finding", {}).get("rationale", "No rationale recorded."))
            elif item.kind == "unresolved":
                st.error(item.label)
            else:
                st.markdown(f"**{item.label}**")
                st.json(item.detail, expanded=False)

    with tabs[1]:
        if not risk.tests:
            st.info("No test was planned against this claim. That is itself worth questioning.")
        for test in risk.tests:
            render_test(test)
            st.divider()

    with tabs[2]:
        if risk.alternatives:
            st.markdown("The assessor was required to record innocent explanations before concluding:")
            for alternative in risk.alternatives:
                st.markdown(f"- {alternative}")
        else:
            st.info("No alternative explanations were recorded.")
        if risk.compensating:
            st.markdown("**Compensating controls review**")
            st.write(risk.compensating)

    with tabs[3]:
        if not risk.dependencies:
            st.info("No dependency relationship was tied to this risk.")
        for treatment in risk.dependencies:
            st.markdown(f"**{treatment['edge_id']} — {treatment['status'].replace('_', ' ').lower()}**"
                        + ("  ·  material" if treatment.get("material") else ""))
            st.caption(treatment.get("rationale", ""))
            st.markdown(
                f'<span class="mono">evidence {", ".join(treatment.get("evidence_refs", [])) or "—"} · '
                f'tests {", ".join(treatment.get("test_refs", [])) or "—"}</span>',
                unsafe_allow_html=True)

    with tabs[4]:
        if risk.disposition:
            st.markdown(f"**Action:** `{risk.disposition['action']}`")
            st.write(risk.disposition.get("rationale", ""))
            st.caption("Basis: " + ", ".join(risk.disposition.get("basis_refs", [])))
        else:
            st.error("No disposition recorded. A material risk cannot be finalised without one.")
        if risk.escalation:
            st.markdown(f"**Escalation:** {risk.escalation['route']} — {risk.escalation['status'].lower()}")
            st.caption(risk.escalation.get("rationale", ""))


def render_result(trace: dict, signing=None):
    verdict = trace.get("verdict") or "NOT CONCLUDED"
    chip = VERDICT_CLASS.get(verdict, "chip-blocked")

    left, right = st.columns([3, 1])
    with left:
        st.markdown(f'<div class="verdict">{verdict}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="sub">{tracelib.headline(trace)}</div>', unsafe_allow_html=True)
        if trace.get("verdict_meaning"):
            st.caption(trace["verdict_meaning"])
    with right:
        st.markdown(f'<span class="chip {chip}">{verdict}</span>', unsafe_allow_html=True)
        if trace.get("synthetic"):
            st.markdown('<span class="chip chip-inconclusive">synthetic evidence</span>', unsafe_allow_html=True)
        if not trace.get("finalizable"):
            st.markdown('<span class="chip chip-blocked">not finalisable</span>', unsafe_allow_html=True)

    if trace.get("rationale"):
        st.info(trace["rationale"])

    attestation = trace.get("pilot_attestation")
    if attestation:
        stale = "" if attestation.get("binds_current_head") else " It does NOT bind the current record."
        st.success(f"Attested by {attestation.get('approver')}: {attestation.get('decision')} — "
                   f"pilot decision support, not a governance result.{stale}")

    render_reveal(trace)

    # --- what the human has to do ------------------------------------------
    st.subheader("What needs a person")
    todo = False
    if trace.get("request"):
        render_request(trace["request"])
        todo = True
    for token in trace.get("blockers", []):
        st.markdown(f"- {explain_blocker(token)}")
        todo = True
    undisposed = [r for r in trace["risks"] if r.material and not r.disposition]
    for risk in undisposed:
        st.markdown(f"- Risk **{risk.ref}** is material and has no disposition.")
        todo = True
    if trace.get("actions"):
        st.markdown("**Remediation actions opened locally** (nothing was sent anywhere):")
        for action in trace["actions"]:
            owner = action.get("owner") or "no owner assigned yet"
            st.markdown(f"- `{action['action_id'][:18]}…` — {action['claim']} → **{owner}** ({action['status'].replace('_', ' ').lower()})")
        todo = True
    if not todo:
        st.success("Nothing is waiting on a person. The result is ready to sign.")
    if signing:
        signing()

    # --- why ---------------------------------------------------------------
    st.subheader("Why — every issue, and what it rests on")
    if not trace["risks"]:
        st.info("Neither the assessor nor the challenger raised an issue.")
    for index, risk in enumerate(trace["risks"]):
        render_risk(risk, index)

    # --- challenge ---------------------------------------------------------
    challenge = trace["challenge"]
    st.subheader("What the independent challenger tried")
    st.caption(
        f"Status {challenge['status']} · reviewed {challenge['reviewed_count']} objects · "
        f"bound to investigation head {(challenge.get('input_head') or '')[:16]}…")
    if challenge["disproof_attempts"]:
        st.markdown("**Disproof attempts**")
        for attempt in challenge["disproof_attempts"]:
            st.markdown(f"- {attempt}")
    if challenge["missing_explanations"]:
        st.markdown("**Explanations the challenger says are missing**")
        for item in challenge["missing_explanations"]:
            st.markdown(f"- {item}")
    if not challenge["findings"]:
        st.caption("The challenger recorded no findings of its own. It was still required to acknowledge every piece of evidence, every hypothesis and every executed test.")

    render_reconciliation(trace.get("reconciliation"))

    # --- obligations -------------------------------------------------------
    st.subheader("Obligation by obligation")
    st.dataframe(
        [{"Obligation": e["element_id"], "Status": e["status"],
          "Assessor said": e.get("assessor_status", e["status"]), "Purpose": e["purpose"],
          "Authority": e["authority"], "Source": e["source_id"],
          "Source approval": SOURCE_STATUS_TEXT.get(e.get("source_status"), e.get("source_status")),
          "Requirement": (e["text"][:110] + "…") if len(e["text"]) > 110 else e["text"]}
         for e in trace["elements"]],
        width="stretch", hide_index=True)
    for element in trace["elements"]:
        with st.expander(f"{element['element_id']} — {element['status']}"):
            st.write(element["text"])
            if element.get("source_status") == "EVALUATION_FIXTURE_NOT_GOVERNANCE_APPROVED":
                st.warning("This obligation comes from an evaluation fixture source. No governance decision "
                           "approved it; it exists to exercise the workflow.")
            elif element.get("approved_by"):
                st.caption(f"Source approved by {element['approved_by']}.")
            st.caption(f"{element['authority']} · {element['source_id']} {element['source_version']} · "
                       f"sha256 {element['source_sha256'][:16]}… · applies: {element['applies']}"
                       f" ({element['applicability_reason']})")
            st.markdown("**Assessor rationale**")
            st.write(element["rationale"] or "—")
            if element["evidence"]:
                st.markdown("**Evidence cited**")
                for record in element["evidence"]:
                    render_evidence(record, element["element_id"] + record["evidence_id"])
            else:
                st.info("No evidence was cited for this obligation.")

    render_trace_panel(trace)


def render_trace_panel(trace: dict):
    st.subheader("Full trace")

    integrity = trace["integrity"]
    if integrity["overall_status"] == "VALID":
        st.success(f"Stage, operational and receipt records verified. "
                   f"{integrity['stages']} stages; head `{integrity['head'][:24]}…`")
    elif integrity["overall_status"] in {"NOT_CHECKED", "PARTIAL"}:
        st.warning("Integrity is not fully verified: "
                   f"stages {integrity['signature_status'].lower()}, "
                   f"operations {integrity['operations']['status'].lower()}, "
                   f"receipts {integrity['receipts']['status'].lower()}.")
    else:
        problems = (integrity["problems"] + integrity["operations"]["problems"]
                    + integrity["receipts"]["problems"])
        st.error("Integrity problems: " + "; ".join(problems))

    with st.expander("Who signed what, and when"):
        st.dataframe(
            [{"Stage": t["title"], "Signed by": t["role"], "Identity": t["actor"],
              "At": (t["at"] or "")[:19].replace("T", " "), "Record hash": (t["record_hash"] or "")[:20] + "…"}
             for t in trace["timeline"]],
            width="stretch", hide_index=True)
        st.caption("Each stage is hash-chained to the one before it and signed by a separate role. "
                   "The challenger is required to be a different principal and a different key from the assessor.")

    with st.expander("Retrieval lanes the assessor actually had"):
        st.dataframe(
            [{"Lane": lane["name"], "Status": lane["status"], "Required": lane.get("required", True),
              "References": len(lane.get("refs", [])), "Error": lane.get("error", "")}
             for lane in trace["retrieval"]],
            width="stretch", hide_index=True)
        st.caption("Unavailable is not the same as completed-with-no-hits. Both are recorded distinctly.")

    dependency = trace["dependency_review"]
    with st.expander(f"Dependency review — {sum(dependency['counts'].values())} relationships treated"):
        st.caption(f"Knowledge version sha256 {(dependency.get('knowledge_sha256') or '')[:16]}… · "
                   f"reviewed by {dependency.get('actor')} · "
                   f"event {(dependency.get('event_hash') or '')[:16]}…")
        st.write({k: v for k, v in dependency["counts"].items() if v})
        st.dataframe(
            [{"Relationship": t["edge_id"], "Treatment": t["status"], "Material": t.get("material"),
              "Evidence": ", ".join(t.get("evidence_refs", [])),
              "Tests": ", ".join(t.get("test_refs", [])), "Rationale": t.get("rationale", "")}
             for t in dependency["treatments"]],
            width="stretch", hide_index=True)

    with st.expander(f"Model reasoning receipts ({len(trace['reasoning'])})"):
        if not trace["reasoning"]:
            st.info("No inference receipts in this case directory. Either the stages were replayed from "
                    "already-signed records, or this run used a scripted test harness rather than a live model.")
        for receipt in trace["reasoning"]:
            live = "live" if receipt.get("live") else "not live"
            st.markdown(f"**{receipt['stage']}** — {receipt.get('model')} via {receipt.get('provider')} "
                        f"({live}, {receipt.get('status')})")
            st.caption(f"{(receipt.get('started_at') or '')[:19]} · prompt sha256 "
                       f"{(receipt.get('prompt_sha256') or '')[:16]}… · response sha256 "
                       f"{(receipt.get('response_sha256') or '')[:16]}…")
            if receipt.get("error"):
                st.error(receipt["error"])
            if visible("show_raw_model_io"):
                question, answer = st.tabs(["Exactly what it was asked", "Exactly what it answered"])
                with question:
                    st.code(receipt.get("prompt", "")[:20000], language="json")
                with answer:
                    st.code(receipt.get("response", "")[:20000], language="json")
            else:
                st.caption("Prompt and response are hidden. Open evidence and reasoning above to read them; "
                           "the signed hashes are shown either way.")
            st.divider()

    with st.expander("Raw signed record"):
        snapshot = Path(trace["case_dir"]) / "investigation.json"
        if REVIEWER_POLICY["allow_trace_download"]:
            st.download_button("Download the complete signed investigation",
                               snapshot.read_bytes() if snapshot.is_file() else b"{}",
                               file_name=f"{trace['investigation_id']}-investigation.json",
                               mime="application/json")
        else:
            st.caption("Trace download is disabled by reviewer policy.")
        st.caption("This file contains all eight signed stages with their payloads, the dependency "
                   "review event and the run report. It replays offline without any key material.")


# --------------------------------------------------------------------------
# setup panel
# --------------------------------------------------------------------------

def render_setup(config, root):
    from governance.operations.runtime import doctor
    st.subheader("Readiness")
    report = doctor(config, root)
    ok = report["status"] == "CONFIGURED"
    (st.success if ok else st.warning)(
        "Everything this app needs is configured." if ok else
        f"{len(report['blockers'])} thing(s) must be configured before a run can start.")
    for name, check in report["checks"].items():
        symbol = {"AVAILABLE": "✅", "NOT_EVALUATED": "⏸️", "DISABLED": "⏸️"}.get(check["status"], "❌")
        st.markdown(f"{symbol} **{name}** — {check['status'].lower()}"
                    + (f" · {check['reason']}" if check.get("reason") else ""))
    st.caption("`held_out_judgment` stays unevaluated by design until an independent corpus is supplied. "
               "It is the difference between an evaluation run and a production governance result.")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    st.title("Governance as a Result")

    try:
        _cfg = config_path()
        config, root = read_config(str(_cfg), _cfg.stat().st_mtime if _cfg.exists() else 0.0)
    except Exception as exc:
        st.error(f"Cannot read the operating configuration at `{config_path()}` — {type(exc).__name__}: {exc}")
        st.caption("Set WB_INVESTIGATION_CONFIG to your approved configuration file and reload.")
        return

    mode = config.get("operation_mode", "evaluation")
    REVIEWER_POLICY.update(config.get("reviewer_ui", {}))
    token_env = REVIEWER_POLICY.get("access_token_env")
    expected_token = os.environ.get(token_env, "") if token_env else ""
    if mode == "production" and not token_env:
        st.error("Production reviewer access requires reviewer_ui.access_token_env. Enterprise identity enforcement remains an external acceptance gate.")
        return
    if token_env:
        supplied = st.text_input("Reviewer access token", type="password")
        if not expected_token or not supplied or not hmac.compare_digest(supplied, expected_token):
            st.warning("Enter the configured reviewer token to open this local assessment interface.")
            return
    profile = config.get("deployment_profile") or ("production" if mode == "production" else "demonstration")
    if config.get("separation_of_duties") == "SINGLE_REVIEWER_PILOT":
        st.warning("One person owns scope, approved the sources and will attest. Acceptable for a pilot, "
                   "not for a result anyone else relies on.")
    st.caption(f"Profile: **{profile}**. "
               f"Mode: **{mode}**. Deployment authorisation is never granted by this app. "
               f"Configuration: `{config_path()}`")

    rows = portfolio(config, root)
    if not rows:
        st.info("No authorised assessment exists yet. An owner and governance signature must create one "
                "before anything can run.")
        render_setup(config, root)
        return

    with st.sidebar:
        st.header("Assessments")
        def _label(r):
            period = (context_of(config, root, r["investigation_id"]).get("period") or "")[:10]
            recurring = bool(config.get("periodic_evidence"))
            return f"{r['system_id'] or '?'} · {r['control_id'] or '?'}" + (f" · {period}" if recurring and period else "")
        labels = {r["investigation_id"]: _label(r) for r in rows}
        selected = st.radio("Select", [r["investigation_id"] for r in rows],
                            format_func=lambda i: labels.get(i, i), label_visibility="collapsed")
        with st.expander("Readiness"):
            render_setup(config, root)

    current = next(r for r in rows if r["investigation_id"] == selected)
    st.session_state["current_investigation"] = selected

    header, action = st.columns([4, 1])
    with header:
        st.markdown(f"### {current['system_id'] or '?'} — {current['control_id'] or '?'}")
        st.markdown(status_chip(current)
                    + f' <span class="mono">{current["investigation_id"]}'
                      f'{" · last run " + current["updated_at"][:19].replace("T", " ") if current.get("updated_at") else ""}</span>',
                    unsafe_allow_html=True)
    with action:
        if st.button("▶  Run", type="primary", width="stretch"):
            with st.status("Running the assessment…", expanded=True) as status:
                status.write("Collecting scoped evidence, examining, explaining, planning, "
                             "executing tests, reviewing dependencies, challenging, disposing.")
                try:
                    outcome = run_investigation(config, root, selected)
                    status.update(label=f"Finished: {outcome.get('checkpoint')}", state="complete")
                except Exception as exc:
                    status.update(label="Stopped", state="error")
                    # Kept in the session so the refresh below cannot erase it.
                    st.session_state["run_error"] = f"{type(exc).__name__}: {exc}"
            st.cache_data.clear()
            st.rerun()
        st.caption("Completed stages resume; the model is not re-asked.")

    run_error = st.session_state.pop("run_error", None)
    if run_error:
        st.error(f"The last Run stopped with an error: {run_error}")

    st.divider()

    if not current["has_snapshot"]:
        events = []
        try:
            ops = tracelib.verify_operations(current["case_dir"], config.get("trusted_keys"))
            if ops.get("status") == "VALID":
                events = ops.get("records", [])
        except Exception as exc:
            st.caption(f"Journal unavailable: {type(exc).__name__}")
        for event in [e for e in events if e.get("kind") == "integrity_event"]:
            item = event["payload"]
            st.error(f"**Integrity event ({item['rule']}):** {item['finding']}. Detected {item['detected_at']}; "
                     f"the delivery was moved, untouched, to `{item['quarantined_to']}`. Find out who produced it and why.")
        if config.get("standing_authorisation"):
            try:
                from governance.production import recurring as _recurring
                series = _recurring.load(config, Path(root))["payload"]
                if series.get("governing_policy_status") == "APPROVED":
                    st.caption(f"Series {series['authorisation_id']} runs under governing policy "
                               f"{series.get('governing_policy_version')} ({(series.get('governing_policy_sha256') or '')[:12]}…), approved.")
                else:
                    st.caption(f"Series {series['authorisation_id']} was authorised without an approved governing "
                               f"policy ({series.get('governing_policy_status') or 'authorised before policy approval existed'}).")
            except Exception as exc:
                st.caption(f"Series status unavailable: {type(exc).__name__}")
        unavailable = [e for e in events if e.get("kind") == "model_stage_unavailable"]
        reconciled = [e for e in events if e.get("kind") == "obligation_reconciliation"]
        from governance.production.completion import enabled as completion_enabled
        deterministic = bool(unavailable) and completion_enabled(config)
        if deterministic and not any(e.get("kind") == "pilot_attestation" for e in events):
            st.success("**New result, awaiting your attestation.**")
        deltas = [e for e in events if e.get("kind") == "period_delta"]
        if deltas:
            d = deltas[-1]["payload"]
            st.markdown(f"#### Since the previous period ({d['previous_label']})")
            st.markdown(f"Verdict **{d['verdict_before']} → {d['verdict_after']}**"
                        f" ({'changed' if d['verdict_changed'] else 'unchanged'}) · findings "
                        f"**{d['issues_before']} → {d['issues_after']}**")
            if d["obligation_changes"]:
                quiet = "no finding this period (not positively shown)"
                label = lambda v: quiet if v == "NOT_EVALUATED" else (
                    "no exceptions this period (checked, corroborated)" if v == "NO_EXCEPTIONS_FOR_PERIOD" else v)
                st.dataframe([{"Obligation": c["element_id"], "Previous period": label(c["before"]),
                               "This period": label(c["after"])} for c in d["obligation_changes"]],
                             width="stretch", hide_index=True)
                if any("NOT_EVALUATED" in (c["before"], c["after"]) for c in d["obligation_changes"]):
                    st.caption("A quiet period is not a clean one: no test finding fired, and with no model "
                               "assessment nothing positively shows the obligation was met.")
            before, after = d.get("coverage_before"), d.get("coverage_after")
            if before and after and before["corroborated"] != after["corroborated"]:
                line = (f"Coverage: **{'corroborated' if before['corroborated'] else 'not corroborated'} → "
                        f"{'corroborated' if after['corroborated'] else 'not corroborated'}**"
                        + (f" ({after['reason']})" if after.get("reason") else ""))
                (st.warning if before["corroborated"] and not after["corroborated"] else st.markdown)(line)
            if d.get("basis_changes"):
                st.caption("Same status, different basis: " + "; ".join(
                    f"{b['element_id']} {b['before']} → {b['after']}" for b in d["basis_changes"]))
            cols = st.columns(3)
            for col, title, key in zip(cols, ("Resolved", "New", "Still present"),
                                       ("codes_resolved", "codes_new", "codes_persisting")):
                with col:
                    st.markdown(f"**{title}** ({len(d[key])})")
                    for code in d[key]:
                        st.caption(code)
        if deterministic and unavailable[-1]["payload"].get("disabled_by_configuration"):
            st.info("**Deterministic record.** Model stages are disabled for this pilot, so no model was asked "
                    "anything. Every status below comes from the deterministic tests and the reconciliation.")
        elif deterministic:
            item = unavailable[-1]["payload"]
            st.warning(f"**Model stage unavailable — deterministic record only.** The {item['stage']} stage failed "
                       f"({item['error'][:220]}). This record comes from the deterministic tests and the "
                       "reconciliation alone. No model stage was written in the model's name.")
        else:
            period_note = None
            if config.get("periodic_evidence") and not [e for e in events if e.get("kind") != "integrity_event"]:
                try:
                    from governance.production import recurring
                    payload = recurring.verify(config, Path(root))
                    period = next((p for p in payload["periods"] if p["investigation_id"] == selected), None)
                    period_note = recurring.period_state(config, Path(root), period) if period else None
                except Exception as exc:
                    st.caption(f"Period status unavailable: {type(exc).__name__}")
            if period_note and period_note["state"] == "OVERDUE":
                st.error(f"**Evidence overdue by {period_note['overdue_days']} day(s).** This period ended "
                         f"{period_note['as_of'][:10]} and its exports have not arrived"
                         + (f" (missing: {', '.join(period_note['missing_files'])})" if period_note["missing_files"] else "")
                         + ". Nothing can be assessed until they do.")
            elif period_note and period_note["state"] in {"PREMATURE_EXPORT", "EARLY_PARTIAL"}:
                st.warning("**Exports arrived before this period ended.** "
                           + ("They declare complete collection, which cannot yet be true, so the next check will "
                              "quarantine them as an integrity event (D14, runbook E1)." if period_note["state"] == "PREMATURE_EXPORT"
                              else "They are partial; nothing is assessed until the period ends."))
            elif period_note and period_note["state"] == "NOT_YET_DUE":
                st.info(f"This period ends {period_note['as_of'][:10]}. Nothing is due yet.")
            elif period_note and period_note["state"] in {"AWAITING_EVIDENCE", "EVIDENCE_INCOMPLETE"}:
                st.info(f"This period ended {period_note['as_of'][:10]}. Waiting for its exports"
                        + (f" (missing: {', '.join(period_note['missing_files'])})" if period_note["missing_files"] else "")
                        + "; it becomes overdue after the grace period.")
            else:
                st.info("This assessment has not produced a concluded record yet.")
            if current.get("request"):
                render_request(current["request"])
        if reconciled:
            render_reconciliation({**reconciled[-1]["payload"], "event_hash": reconciled[-1].get("event_hash")},
                                  models_disabled=bool(unavailable) and bool(unavailable[-1]["payload"].get("disabled_by_configuration")))
        if deterministic:
            try:
                from governance.investigation import InvestigationEngine, InvestigationStore
                from governance.production.journal import Journal
                engine = InvestigationEngine(InvestigationStore(Path(root) / config["store"], config["trusted_keys"]),
                                             config["sources"])
                journal = Journal(Path(current["case_dir"]) / "operations.sqlite", config["trusted_keys"])
                decisions.render_panel(st, config_path(), config, Path(root), selected, engine, journal)
            except Exception as exc:
                st.error(f"Attestation is unavailable — {type(exc).__name__}: {exc}")
        elif not current.get("request") and not reconciled and not config.get("periodic_evidence"):
            st.caption("Press Run to start it.")
        return

    try:
        trace = tracelib.build_trace(current["case_dir"], config.get("trusted_keys"), config.get("sources"))
    except Exception as exc:
        st.error(f"Cannot assemble the trace — {type(exc).__name__}: {exc}")
        return

    def signing():
        try:
            from governance.investigation import InvestigationEngine, InvestigationStore
            from governance.production.journal import Journal
            engine = InvestigationEngine(InvestigationStore(Path(root) / config["store"], config["trusted_keys"]),
                                         config["sources"])
            journal = Journal(Path(current["case_dir"]) / "operations.sqlite", config["trusted_keys"])
            decisions.render_panel(st, config_path(), config, Path(root), selected, engine, journal)
        except Exception as exc:
            st.error(f"Signing is unavailable — {type(exc).__name__}: {exc}")

    render_result(trace, signing=signing)


if __name__ == "__main__":
    main()
