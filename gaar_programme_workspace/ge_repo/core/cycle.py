"""WB-042 — the assessment cycle as a library.

Until now the cycle existed only as control flow inside `app.py`, interleaved with Streamlit
widgets. `run_scan.py` stopped at proposals; blind read, compare, challenge and decide were
reachable only by a person clicking. That was the ceiling on everything else — a continuous
audit cannot be scheduled, replayed, exposed as an API or driven from CI if its middle is a UI.

Nothing here re-implements assessment. It orchestrates the existing modules — `pipeline.propose`,
`compare.compare`, `challenge.challenge_disagreement`, `reasons.reason_error` — and writes each
step to the append-only event store. The deterministic constraints all still live where they
were, which is the layer that was already right.

Two invariants this module enforces, both of which were previously enforced by the shape of the
UI rather than by code — and a UI is not a control:

  blindness    `proposal_for_reviewer()` returns nothing until a read is recorded. The proposal
               can be computed at any time, including hours earlier in a batch: blindness is
               about what the reviewer was shown, not when the call was made. A caller that
               wants the proposal regardless must ask for it explicitly through
               `state()["proposal"]`, which is an auditable choice rather than an accident.

  reasons      `decide()` runs the same `reasons.reason_error` check the UI runs. The hollow
               record — 47 accepts to 4 amends, every reason reading "accept" — happened because
               agreement was one click. A headless path with no reason check would reproduce it
               at machine speed.

No module below this one imports Streamlit. That is the test of whether the extraction worked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from dataclasses import replace

import os

import events
import llm
from governance.observation import declare_observation_envelope

declare_observation_envelope("reviewer_read")

__all__ = ["start", "bind_evidence", "bind_admitted_evidence", "rebind_evidence", "gap_scan", "check_bundle_unchanged",
           "assess", "record_proposal", "challenge_read", "record_challenge", "record_note",
           "copilot_request", "copilot_reference", "copilot_influence",
           "challenge_copilot_request",
           "contract_status", "assert_contract_executable",
           "record_compare", "record_observation",
           "record_read",
           "proposal_for_reviewer", "compare_reads", "challenge", "decide", "apply_routine_blind_read_waiver", "state",
           "open_cycles"]


class CycleError(RuntimeError):
    """A step was attempted out of order, or on a cycle that cannot support it."""


def _decision_time_freshness(state: dict) -> dict:
    """Evaluate declared evidence freshness at the actual decision boundary.

    Unknown freshness is reported but does not block a decision. A declared ``fresh_until``
    that has expired is a governance blocker because the human is deciding on evidence that is
    no longer current according to the evidence producer.
    """
    evidence = state.get("evidence") or {}
    candidates: list[dict] = []

    if isinstance(evidence, dict):
        for key in ("fresh_until",):
            if evidence.get(key):
                candidates.append({"source": "evidence", "fresh_until": evidence.get(key),
                                   "observation_id": evidence.get("observation_id")})
        packet = evidence.get("plugin_packet")
        if isinstance(packet, dict) and packet.get("fresh_until"):
            candidates.append({"source": "plugin_packet",
                               "fresh_until": packet.get("fresh_until"),
                               "observation_id": packet.get("observation_id")})

    for row in state.get("observations") or []:
        if isinstance(row, dict) and row.get("fresh_until"):
            candidates.append({"source": "observation",
                               "fresh_until": row.get("fresh_until"),
                               "observation_id": row.get("observation_id")})

    now = datetime.now(timezone.utc)
    stale: list[dict] = []
    malformed: list[dict] = []
    for item in candidates:
        raw = str(item["fresh_until"])
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if now > parsed:
                stale.append(item)
        except ValueError:
            malformed.append({**item, "reason": "INVALID_FRESH_UNTIL"})

    return {
        "status": "stale" if stale else ("invalid" if malformed else ("known" if candidates else "unknown")),
        "checked_at": now.isoformat(timespec="seconds"),
        "declared": len(candidates),
        "stale": stale,
        "malformed": malformed,
    }


_FRAMEWORK_ALIASES = {
    "MGF": "MGF Agentic",
    "MGF_Agentic": "MGF Agentic",
    "MGF Agentic": "MGF Agentic",
    "ISO42001": "ISO 42001",
    "ISO_42001": "ISO 42001",
    "ISO 42001": "ISO 42001",
    "NIST_AI_RMF": "NIST AI RMF",
    "NIST AI RMF": "NIST AI RMF",
    "MAS": "MAS",
    "SAFR": "SAFR",
}


def _canonical_framework(framework: str) -> str:
    raw = str(framework or "").strip()
    return _FRAMEWORK_ALIASES.get(raw, raw)


_CONTROLS_CACHE: dict = {}


def _library(workbook: str):
    """The parsed playbook, cached on the workbook's and the overlay's path, mtime and size (kit v21).

    Parsing the workbook takes ~0.4 s, and the decision queue asked for one control per cycle: 84 parses per page.
    Editing either file changes the key, so the next call re-reads it.
    """
    from playbook import load_controls, overlay_path
    import os
    overlay = overlay_path()
    key = (workbook, os.stat(workbook).st_mtime_ns, os.stat(workbook).st_size,
           str(overlay) if overlay else None, os.stat(overlay).st_mtime_ns if overlay and os.path.exists(overlay) else None)
    if key not in _CONTROLS_CACHE:
        _CONTROLS_CACHE.clear()
        _CONTROLS_CACHE[key] = load_controls(workbook)
    return _CONTROLS_CACHE[key]


def _control(control_id: str, framework: str = ""):
    import copy
    import glob
    from governance.paths import workbench_data
    wb = sorted(glob.glob(str(workbench_data() / "*.xlsx")))
    if not wb:
        raise CycleError("no playbook workbook found in data/")
    canonical_framework = _canonical_framework(framework)
    for lib, controls in _library(wb[0]).items():
        if canonical_framework and lib != canonical_framework:
            continue
        for c in controls:
            if c.id == control_id:
                return copy.deepcopy(c)            # callers get their own copy; the cache is never mutated
    raise CycleError(f"control {control_id} not found"
                     + (f" in {canonical_framework}" if canonical_framework else ""))


# ---------------------------------------------------------------- cycle lifecycle

def start(control_id: str, *, framework: str = "", actor: str = "system",
          governance_context: dict | None = None) -> str:
    c = _control(control_id, framework)
    cid = events.new_cycle_id(control_id)
    payload = {"title": c.title}
    if governance_context:
        payload["governance_context"] = dict(governance_context)
    events.append("cycle_started", cycle_id=cid, actor=actor, control_id=control_id,
                  framework=c.lib, payload=payload)
    return cid


def _control_for_state(state: dict):
    """Return the canonical control, optionally projected onto a governed requirement version.

    Reassessment metadata may carry a target requirement snapshot.  The snapshot changes only
    the requirement context presented to the existing assessor/reviewer/challenger path; it does
    not create a second assessment engine and does not mutate the playbook control object.
    """
    c = _control(state["control_id"], state.get("framework", ""))
    ctx = state.get("governance_context") or {}
    override = ctx.get("requirement_override") or {}
    if not isinstance(override, dict) or not override:
        return c
    req = str(override.get("requirement") or override.get("text") or c.req).strip()
    elements_raw = override.get("elements")
    elements = c.elements
    artefacts = c.artefacts
    if isinstance(elements_raw, list):
        parsed = []
        for item in elements_raw:
            if isinstance(item, dict):
                parsed.append((str(item.get("id", "")), str(item.get("text", "")).strip()))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                parsed.append((str(item[0]), str(item[1]).strip()))
        if parsed:
            elements = tuple(parsed)
            artefacts = "; ".join(text for _eid, text in elements if text) or artefacts
    return replace(c, req=req, elements=elements, artefacts=artefacts)


def bind_evidence(cycle_id: str, evidence: dict, *, actor: str = "system") -> dict:
    """Attach the evidence bundle. Recorded before assessment so that what the model was given
    is part of the record, not reconstructed from what it said afterwards."""
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    return events.append("evidence_bound", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=evidence)


def bind_admitted_evidence(cycle_id: str, evidence: dict, *, admission_event: dict,
                           admission_store, actor: str) -> dict:
    """WB-124 governed binding: verify signed, ledger-backed admission at the cycle boundary.

    Existing manual bind_evidence remains available for legacy review; this endpoint does not
    let a Scout proposal masquerade as admitted evidence.
    """
    from governance.evidence_scout.dossier import canonical, sha256
    from governance.result_contract import CanonicalSigner
    import base64
    if not actor or actor != admission_event.get('actor_id'):
        raise CycleError('admission actor mismatch')
    if admission_event.get('cycle_id') != cycle_id or evidence.get('admission_dossier_id') != admission_event.get('dossier_id'):
        raise CycleError('admission/cycle/dossier mismatch')
    if evidence.get('evidence_set_id') != admission_event.get('evidence_set_id') or sha256(canonical(evidence)) != admission_event.get('bundle_hash'):
        raise CycleError('admission payload does not match evidence bundle')
    if not any(r['record_type'] == 'EvidenceAdmissionPrepared' and r['payload'] == admission_event
               for r in admission_store.read()):
        raise CycleError('signed admission has no matching ledger entry')
    seal = admission_event.get('seal') or {}
    from governance.result_integration import signer_from_env
    configured = signer_from_env()
    if seal.get('key_id') != configured.key_id or seal.get('public_key_b64') != configured.public_key_b64:
        raise CycleError('admission signer does not match configured trusted key')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(seal['public_key_b64'],validate=True))
        public_key.verify(base64.b64decode(seal['signature'],validate=True),
                          canonical({k:v for k,v in admission_event.items() if k != 'seal'}))
    except Exception as exc:
        raise CycleError('invalid admission signature') from exc
    s = events.state(cycle_id)
    if not s or s.get('evidence') or s.get('read') or s.get('proposal') or s.get('decision'):
        raise CycleError('cycle not fresh or evidence already bound')
    return bind_evidence(cycle_id,evidence,actor=actor)


def gap_scan(cycle_id: str, chunks=None, *, actor: str = "system") -> dict:
    """WB-103 — deterministic completeness pass over the bound evidence.

    Runs before the reviewer's blind read, and safe to show them, because it produces no rating
    and no element verdict: only which declared artefacts have no candidate document. A list of
    what is missing cannot anchor a reader the way a proposed sufficiency can — there is no
    verdict to agree with.

    No model is called. See governance/completeness.py for why this is a matching rule rather
    than a judgement.
    """
    from governance.completeness import scan, hash_chunks
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    ev = s.get("evidence") or {}
    if chunks is None:
        chunks = ev.get("chunks") or []
    c = _control_for_state(s)
    result = scan(c, chunks)
    result["bundle_hash_at_scan"] = hash_chunks(chunks)
    events.append("gap_scanned", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload={"completeness": result})
    return result


def rebind_evidence(cycle_id: str, evidence: dict, *, actor: str, reason: str = "") -> dict:
    """Re-bind after the reviewer topped up the bundle in response to the gap scan.

    Two things this records that a silent re-bind would lose.

    First, the bundle assessed must be the bundle the blind read and the challenge saw. Without
    an explicit re-bind those three steps can attack different objects and nothing in the record
    would show it.

    Second, a bundle assembled against a checklist is not an independent sample of what the
    organisation had. `evidence_added_after_gap_scan` marks it, for the same reason label.py
    records `assessor_shown`: the number is still usable, but it is no longer usable as eval
    material, and the record has to say which it is rather than leaving a later reader to guess.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not actor or not str(actor).strip():
        raise CycleError("a re-bind must name who added the evidence")
    if s.get("read"):
        raise CycleError("the reviewer has already recorded a read — topping up the bundle now "
                         "would leave that read attached to evidence it never saw. Start a new "
                         "cycle rather than editing the object under an existing reading")
    payload = dict(evidence)
    payload["evidence_added_after_gap_scan"] = bool(s.get("completeness"))
    payload["rebind_reason"] = str(reason or "")
    payload["supersedes_bundle_hash"] = (s.get("evidence") or {}).get("bundle_hash")
    return events.append("evidence_bound", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=payload)


def contract_status(control_id: str, framework: str = "", *, source_path=None) -> dict:
    """Integrity status for one control. The UI's only route to it.

    `app.py` calls this and renders the verdict. It does not assemble a contract, does not know
    which checks exist, and does not decide what blocks — the same shape the predicate engine
    will use later, where the app asks `evaluate(control_id, scope)` and receives a ControlResult
    without learning what a predicate is.
    """
    from governance.contract_integrity import status_for_control
    c = _control(control_id, framework)
    return status_for_control(c, source_path=source_path)


def assert_contract_executable(control_id: str, framework: str = "") -> dict:
    """Raise `ContractInvalid` unless the contract is sound.

    GE-110. Enforced here rather than in the UI, because a gate the caller has to remember is a
    gate that holds until someone adds a second caller. `app.py` renders the block; this makes it
    true whether or not it does.
    """
    from governance.contract_integrity import ContractInvalid, status_for_control
    c = _control(control_id, framework)
    report = status_for_control(c)
    if not report["executable"]:
        raise ContractInvalid(report)
    return report


def check_bundle_unchanged(cycle_id: str, evidence: dict | None = None) -> None:
    """Raise if the bundle moved after the completeness scan without a recorded re-bind.

    Public, and separate from `assess()`, because `app.py` does not call `assess()` — it computes
    the proposal itself and writes a `proposed` event directly. A guard that lives only inside
    the library function the UI skips is a guard the UI does not have, which is the same class of
    mistake as enforcing blindness by screen order. Call this at any point that is about to
    record a proposal.
    """
    from governance.completeness import hash_chunks, chunks_from_evidence
    s = events.state(cycle_id)
    if not s:
        return
    ev = evidence if evidence is not None else (s.get("evidence") or {})
    scanned = (s.get("completeness") or {}).get("bundle_hash_at_scan")
    if not scanned:
        return
    chunks = ev.get("chunks") or chunks_from_evidence(ev)
    current = ev.get("bundle_hash") or hash_chunks(chunks)
    if current != scanned and not ev.get("evidence_added_after_gap_scan"):
        raise CycleError(
            "the evidence bundle changed after the completeness scan without a recorded "
            "re-bind — call rebind_evidence() so the record shows which bundle each step saw")


def assess(cycle_id: str, *, actor: str = "assessor") -> dict:
    """Run the assessor over the bound evidence under the `assess` role's model."""
    from pipeline import is_error, propose
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    ev = s.get("evidence")
    if not ev:
        raise CycleError("bind evidence before assessing — an assessment with no recorded "
                         "evidence cannot be reproduced or replayed")
    assert_contract_executable(s["control_id"], s.get("framework", ""))
    check_bundle_unchanged(cycle_id)
    c = _control_for_state(s)
    with llm.model_for("assess") as model:
        with llm.observe("assess", cycle_id=cycle_id, control_id=s["control_id"]) as m:
            try:
                proposal = propose(c, ev, task_id=f"ASSESS-{cycle_id}", review_id=cycle_id)
            except TypeError as exc:
                text = str(exc)
                if "unexpected keyword argument 'review_id'" in text:
                    proposal = propose(c, ev, task_id=f"ASSESS-{cycle_id}")
                elif "unexpected keyword argument 'task_id'" in text:
                    proposal = propose(c, ev)
                else:
                    raise
            m["ok"] = not is_error(proposal)
            m["error"] = proposal.get("error") if not m["ok"] else None
    events.append("proposed", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""),
                  payload={"proposal": proposal, "model": model,
                           "assessment_identity": ev.get("assessment_identity")})
    return proposal


def record_proposal(cycle_id: str, proposal: dict, *, model: str | None = None,
                    assessment_identity: dict | None = None, actor: str = "assessor") -> dict:
    """Record a proposal the caller already computed.

    GE-109. `assess()` both runs the assessor and writes the result, which the UI cannot use —
    it runs `propose()` on a background thread so the reviewer is never blocked, and only has a
    finished proposal to hand. Before this, the UI wrote the `proposed` event itself, which meant
    it skipped every guard `assess()` applies. Two of them matter:

      * a failed call is not a proposal. `propose()` returns `status: "error"` with no
        sufficiency rather than manufacturing a `none` (WB-021), and writing that to the ledger
        would record a rating the assessor never made.
      * the bundle must not have moved since the completeness scan (WB-103), or the proposal is
        about an object nothing else in the cycle saw.

    This is the write half of `assess()` with both guards, and nothing else.
    """
    from pipeline import is_error
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not isinstance(proposal, dict) or not proposal:
        raise CycleError("a proposal must be a non-empty record")
    if is_error(proposal):
        raise CycleError("the assessor call failed — a failed call is not a proposal and is not "
                         "recorded as one. Surface the error to the reviewer instead")
    # WB-129 Gate 0: async UI write-half must enforce the same evidence-before-assess
    # boundary as assess(). check_bundle_unchanged() alone does not require a bundle.
    if not s.get("evidence"):
        raise CycleError("bind evidence before recording an assessment proposal")
    assert_contract_executable(s["control_id"], s.get("framework", ""))
    check_bundle_unchanged(cycle_id)
    return events.append("proposed", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload={"proposal": proposal,
                                  "model": model or proposal.get("model"),
                                  "assessment_identity": assessment_identity})


def challenge_read(cycle_id: str, *, actor: str = "challenger") -> dict:
    """First-pass challenge: attack the reviewer's own reading.

    Distinct from `challenge()`, which is the second pass and is scoped to the disagreement
    between the two reads. This one needs only a recorded read, and refuses without one — a
    challenge against a reading nobody has written down has nothing to attack.
    """
    from challenge import challenge as challenge_reading
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    read = s.get("read")
    if not read:
        raise CycleError("no reviewer read recorded — this pass attacks your reading, so there "
                         "must be a reading to attack")
    c = _control_for_state(s)
    ev_text = (s.get("evidence") or {}).get("text", "")
    # The challenge implementation owns provider/model selection through the inference
    # orchestrator. Keeping another `model_for()` wrapper here would silently relabel a Colibri
    # call as Ollama and double-count transport telemetry.
    return challenge_reading(c, ev_text, read)


def record_challenge(cycle_id: str, record: dict, *, actor: str = "challenger") -> dict:
    """Write a challenge pass to the ledger.

    Separate from running it, because the UI decorates the challenger's return with dossier and
    display fields before it is stored. The one thing this refuses is an empty record: a pass
    that produced nothing must still say which of the three it was (ran clean, blocked, never
    ran), and a bare `{}` says none of them.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not isinstance(record, dict) or not record:
        raise CycleError("an empty challenge record cannot be written — a pass that produced "
                         "nothing still has to record whether it ran, was blocked, or found "
                         "nothing")
    return events.append("challenged", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=record)


def record_note(cycle_id: str, payload: dict, *, actor: str) -> dict:
    """A reviewer annotation on an existing cycle — currently challenge responses.

    Notes carry no rating and gate nothing, but they are attributable, so a named actor is
    required for the same reason `decide()` requires one.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not actor or not str(actor).strip():
        raise CycleError("a note must name who wrote it")
    if not isinstance(payload, dict) or not payload:
        raise CycleError("an empty note is not a record of anything")
    return events.append("note", cycle_id=cycle_id, actor=str(actor).strip(),
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload=payload)


def _first_read_event(cycle_id: str) -> dict | None:
    rows = [e for e in events.cycle(cycle_id) if e.get("kind") == "read"]
    return rows[0] if rows else None


def _latest_copilot_event(cycle_id: str, kind: str | None = None) -> dict | None:
    rows = [e for e in events.cycle(cycle_id)
            if e.get("kind", "").startswith("copilot_") and (kind is None or e.get("kind") == kind)]
    return rows[-1] if rows else None


def copilot_request(cycle_id: str, *, actor: str, request_id: str | None = None) -> dict:
    """Run bounded Copilot assistance after an initial reading exists.

    The first reviewer read is immutable in the event stream and its content is deliberately not
    passed to the Copilot model. Provider routing remains owned by inference.policy/orchestrator.
    """
    if not actor or not str(actor).strip():
        raise CycleError("a Copilot request must name the reviewer")
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    first_read = _first_read_event(cycle_id)
    if not first_read:
        raise CycleError("Copilot is unavailable until the initial reviewer reading is recorded")
    if not s.get("evidence"):
        raise CycleError("Copilot requires bound evidence")
    from copilot import request as request_copilot
    control = _control_for_state(s)
    request_id = request_id or f"COP-REQ-{events.new_cycle_id(s["control_id"]).split("-")[-1]}"
    requested = events.append(
        "copilot_requested", cycle_id=cycle_id, actor=actor,
        control_id=s["control_id"], framework=s.get("framework", ""),
        payload={"request_id": request_id, "schema_version": "copilot.response.1",
                 "initial_read_event_id": first_read.get("event_id"),
                 "initial_read_recorded_at": first_read.get("ts")},
    )
    try:
        try:
            result = request_copilot(control, s.get("evidence") or {},
                                     task_id=request_id, review_id=cycle_id)
        except TypeError as exc:
            text = str(exc)
            # Compatibility only for adapters/test doubles that genuinely lack a keyword.
            if "unexpected keyword argument 'review_id'" in text:
                result = request_copilot(control, s.get("evidence") or {}, task_id=request_id)
            elif "unexpected keyword argument 'task_id'" in text:
                result = request_copilot(control, s.get("evidence") or {})
            else:
                raise
    except Exception as exc:
        rejection = {"request_id": request_id, "schema_version": "copilot.response.1",
                     "reason_code": "transport_or_validation_error",
                     "reason": f"{type(exc).__name__}: {exc}"}
        events.append("copilot_rejected", cycle_id=cycle_id, actor=actor,
                      control_id=s["control_id"], framework=s.get("framework", ""),
                      payload=rejection)
        raise

    presented = {**result, "requested_event_id": requested.get("event_id"),
                 "initial_read_event_id": first_read.get("event_id")}
    events.append("copilot_presented", cycle_id=cycle_id, actor=actor,
                  control_id=s["control_id"], framework=s.get("framework", ""),
                  payload=presented)
    return presented




def challenge_copilot_request(cycle_id: str, *, actor: str, request_id: str | None = None) -> dict:
    """Run bounded Copilot assistance against the latest admitted disagreement challenge.

    This does not re-run the challenger and cannot alter challenge strength/supports or any
    governance state. It only helps the named reviewer understand what to verify or ask next.
    """
    if not actor or not str(actor).strip():
        raise CycleError("a Challenge Copilot request must name the reviewer")
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    rows = [x for x in (s.get("challenges") or [])
            if isinstance(x, dict) and (x.get("challenges") or [])]
    if not rows:
        raise CycleError("Challenge Copilot is unavailable until an admitted challenge exists")
    latest = rows[-1]
    if not s.get("evidence"):
        raise CycleError("Challenge Copilot requires bound evidence")
    from challenge_copilot import request as request_challenge_copilot
    control = _control_for_state(s)
    request_id = request_id or f"CHCOP-REQ-{events.new_cycle_id(s['control_id']).split('-')[-1]}"
    requested = events.append(
        "challenge_copilot_requested", cycle_id=cycle_id, actor=actor,
        control_id=s["control_id"], framework=s.get("framework", ""),
        payload={"request_id": request_id, "schema_version": "challenge_copilot.response.1",
                 "challenge_diff_sha": latest.get("diff_sha", "")},
    )
    try:
        result = request_challenge_copilot(control, s.get("evidence") or {}, latest,
                                           task_id=request_id, review_id=cycle_id)
    except Exception as exc:
        rejection = {"request_id": request_id, "schema_version": "challenge_copilot.response.1",
                     "reason_code": "transport_or_validation_error",
                     "reason": f"{type(exc).__name__}: {exc}"}
        events.append("challenge_copilot_rejected", cycle_id=cycle_id, actor=actor,
                      control_id=s["control_id"], framework=s.get("framework", ""),
                      payload=rejection)
        raise
    presented = {**result, "requested_event_id": requested.get("event_id"),
                 "challenge_diff_sha": latest.get("diff_sha", "")}
    events.append("challenge_copilot_presented", cycle_id=cycle_id, actor=actor,
                  control_id=s["control_id"], framework=s.get("framework", ""),
                  payload=presented)
    return presented

def copilot_reference(cycle_id: str, request_id: str, *, actor: str) -> dict:
    if not actor or not str(actor).strip():
        raise CycleError("a Copilot reference declaration must name the reviewer")
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    known = {str((x.get("payload") or {}).get("request_id")) for x in events.cycle(cycle_id)
             if x.get("kind") == "copilot_presented"}
    if str(request_id) not in known:
        raise CycleError("unknown Copilot request")
    return events.append("copilot_reference", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload={"request_id": request_id,
                                  "copilot_suggestion_used_as_reference": True})


def copilot_influence(cycle_id: str, final_read_override: dict | None = None) -> dict:
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    reads = [e for e in events.cycle(cycle_id) if e.get("kind") == "read"]
    first = (reads[0].get("payload") or {}).get("read") if reads else {}
    final = (reads[-1].get("payload") or {}).get("read") if reads else first
    if final_read_override is not None:
        final = dict(final_read_override)
    copilot_rows = [e for e in events.cycle(cycle_id)
                    if e.get("kind") in {"copilot_requested", "copilot_presented", "copilot_reference", "copilot_rejected"}]
    presented = [e for e in copilot_rows if e.get("kind") == "copilot_presented"]
    if not first or not presented:
        return {"copilot_present": bool(presented), "copilot_response_presented": bool(presented),
                "rating_changed_after_copilot": False, "rationale_changed_after_copilot": False,
                "element_judgement_changed_after_copilot": False, "changed_element_ids": [],
                "similarity_to_latest_draft": None}
    from copilot import compare_readings, similarity
    influence = compare_readings(first, final, copilot_interaction=True)
    draft = ((presented[-1].get("payload") or {}).get("response") or {}).get("rationale_draft", "")
    influence["similarity_to_latest_draft"] = similarity(draft, final.get("reason", ""))
    influence["copilot_reference_declared"] = any(e.get("kind") == "copilot_reference" for e in copilot_rows)
    return influence


def record_read(cycle_id: str, read: dict, *, actor: str) -> dict:
    """Record the reviewer's own reading.

    Accepts `element_verdicts` as [{element_id, status}] or as {element_id: status}; both are
    normalised by `compare`. A read with no element verdicts is allowed and will simply compare
    on the rating alone — recorded honestly as unset rather than refused, because refusing would
    push a reviewer toward filling boxes to get past a gate.
    """
    if not actor or not str(actor).strip():
        raise CycleError("a read must name its reviewer — an unattributed read is not a read")
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not read.get("sufficiency"):
        raise CycleError("a read must state a sufficiency")
    existing_reads = [e for e in events.cycle(cycle_id) if e.get("kind") == "read"]
    event = events.append("read", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                         framework=s.get("framework", ""), payload={"read": dict(read)})
    if existing_reads and any(e.get("kind") == "copilot_presented" for e in events.cycle(cycle_id)):
        inf = copilot_influence(cycle_id)
        events.append("copilot_revision", cycle_id=cycle_id, actor=actor,
                      control_id=s["control_id"], framework=s.get("framework", ""),
                      payload={"copilot_influence": inf, "read_event_id": event.get("event_id")})
    return event


def proposal_for_reviewer(cycle_id: str) -> dict | None:
    """The proposal, or None while no read has been recorded.

    This is the blindness control expressed as code rather than as screen order.
    """
    s = events.state(cycle_id)
    if not s.get("read"):
        # Routine reassessment is intentionally NOT a blind human read. Only
        # expose the proposal after the cycle records an active signed waiver.
        if s.get("blind_read_waiver"):
            from governance.routine_waiver import applied_waiver, eligibility
            if applied_waiver(s) and not eligibility(s):
                return s.get("proposal")
        return None
    return s.get("proposal")


def compare_reads(cycle_id: str, *, actor: str = "system") -> dict:
    from compare import compare
    s = events.state(cycle_id)
    if not s.get("read"):
        raise CycleError("no reviewer read recorded — there is nothing to compare against")
    if not s.get("proposal"):
        raise CycleError("no proposal recorded — run assess() first")
    c = _control_for_state(s)
    diff = compare(s["read"], s["proposal"], c)
    events.append("compared", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload={"diff": diff})
    return diff


def record_compare(cycle_id: str, diff: dict, *, actor: str = "system") -> dict:
    """Write a comparison the caller already computed.

    `compare_reads()` computes and writes; the UI computes the diff inline while rendering and
    only needs the write. The guard that matters is the one `compare.compare` already encodes and
    the UI had no reason to re-check: a diff must say whether it is comparable. An incomparable
    diff is still recorded — NOT_COMPARABLE is a result — but a diff missing the field entirely
    is not a comparison, it is a dict.
    """
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not isinstance(diff, dict) or "comparable" not in diff:
        raise CycleError("a comparison must record whether the two reads were comparable")
    return events.append("compared", cycle_id=cycle_id, actor=actor,
                         control_id=s["control_id"], framework=s.get("framework", ""),
                         payload={"diff": diff})


def challenge(cycle_id: str, *, actor: str = "challenger") -> dict:
    """Second-pass challenge, scoped to the disagreement, under the challenge role's model."""
    from challenge import challenge_disagreement
    s = events.state(cycle_id)
    diff = s.get("diff")
    if not diff:
        raise CycleError("run compare_reads() first — this pass attacks the disagreement, "
                         "not either read on its own")
    if not diff.get("comparable"):
        raise CycleError(f"not comparable: {diff.get('reason')}")
    if not diff.get("disagreements"):
        raise CycleError("the reviewer and the assessor agree on every compared element — "
                         "there is nothing for this pass to attack")
    c = _control_for_state(s)
    ev_text = (s.get("evidence") or {}).get("text", "")
    # Provider/model selection belongs to `challenge_disagreement()` -> inference orchestrator.
    # Do not wrap it in a second legacy Ollama context: that would misreport Colibri executions
    # and duplicate LLM telemetry.
    out = challenge_disagreement(c, ev_text, s["read"], s["proposal"], diff)
    events.append("challenged", cycle_id=cycle_id, actor=actor, control_id=s["control_id"],
                  framework=s.get("framework", ""), payload=out)
    return out


def _last_challenge_run(state: dict) -> dict:
    """The most recent challenge envelope for this cycle, or {} if the pass never ran.

    `state["challenges"]` is a list of whole challenger returns, each carrying its own
    `validation_status`. An envelope with `challenges: []` and `validation_status: "blocked"`
    is a pass that produced nothing admissible; that is not the same fact as a pass that ran
    cleanly and had nothing to say, and only this envelope distinguishes them.
    """
    rows = [x for x in (state.get("challenges") or []) if isinstance(x, dict)]
    return rows[-1] if rows else {}


def apply_routine_blind_read_waiver(cycle_id: str, *, actor: str = "governance-policy-engine") -> dict:
    """WB-125 policy-gated cycle contract edit. Does not record a reviewer read."""
    from governance.routine_waiver import apply
    return apply(cycle_id, actor=actor)


def decide(cycle_id: str, *, sufficiency: str, maturity: int, reason: str, reviewer: str,
           action: str = "accept") -> dict:
    """Close the cycle. The only step that produces a governance outcome.

    The reason is checked by the same rule the UI applies. A headless path that skipped it would
    reproduce the hollow record at machine speed, which is worse than not having the path.
    """
    from reasons import reason_error
    s = events.state(cycle_id)
    if not s:
        raise CycleError(f"no such cycle: {cycle_id}")
    if not reviewer or not str(reviewer).strip():
        raise CycleError("a decision must name its reviewer")
    # WB-125: only a signed, active, cycle-recorded waiver can replace intermediate
    # blind-read/compare on a routine re-review. Re-check at decision time; a new
    # strong challenge, withdrawn policy, or stale evidence restores the checkpoint.
    if s.get("blind_read_waiver"):
        from governance.routine_waiver import applied_waiver, eligibility
        if not applied_waiver(s):
            raise CycleError("routine waiver policy withdrawn or signature invalid")
        problems = eligibility(s, require_challenge=True)
        if problems:
            raise CycleError("routine waiver no longer eligible: " + "; ".join(problems))
        if s.get("diff") or s.get("read"):
            raise CycleError("routine waiver cannot coexist with blind-read or compare")
        if os.environ.get("WB_GAAR_RESULT_ENABLE", "0").lower() not in {"1","true","yes","on"}:
            raise CycleError("routine waiver requires sealed GovernanceResult output")
        if os.environ.get("WB_GAAR_QUALITY_GATE", "0").lower() not in {"1","true","yes","on"}:
            raise CycleError("routine waiver requires final Quality Gate enabled")
    blind = s.get("read") or {}
    revised = bool(blind) and (blind.get("sufficiency") != sufficiency
                               or blind.get("maturity") != maturity)
    err = reason_error(reason, rating=sufficiency, revised=revised)
    if err:
        raise CycleError(f"reason refused: {err}")

    # Decision-time freshness is checked against the evidence actually bound to this cycle.
    # The check belongs here, not only in the UI, because this is the last governed boundary
    # before the decided event is written.
    freshness = _decision_time_freshness(s)
    if freshness["status"] == "invalid":
        raise CycleError("decision blocked: malformed evidence freshness metadata")
    if freshness["status"] == "stale":
        raise CycleError("decision blocked: evidence is stale at the decision boundary")

    # v0.8: the human remains the decision authority, but the engine compiles the
    # governed evidence/challenge/falsification state and blocks only hard conflicts.
    from governance.decision_engine import evaluate as evaluate_governance
    prior_states = [x for x in events.iter_states() if x.get("control_id") == s["control_id"]
                    and x.get("cycle_id") != cycle_id and x.get("stage") == "decided"]
    reviewer_decision = {
        "action": action,
        "sufficiency": sufficiency,
        "maturity": int(maturity),
        "reason": reason.strip(),
    }
    governed = evaluate_governance(
        control_id=s["control_id"],
        reviewer_decision=reviewer_decision,
        claims=(s.get("claim_register") or {}).get("claims") or s.get("claims") or [],
        challenges=s.get("challenges") or [],
        probes=(s.get("falsification_engine") or {}).get("probes") or [],
        proposed=s.get("proposal"), reviewer_read=blind, history=prior_states,
        # WB-102: pass the challenger's envelope, not only its rows, so the engine can tell a
        # pass that found nothing from a pass whose output was rejected in validation.
        challenge_run=_last_challenge_run(s),
    )
    # Hard policy is enforced at the API boundary, outside prompts and UI.
    from governance.decision_engine import enforce as enforce_governance
    enforce_governance(governed)

    final_reviewer_record = dict(blind)
    final_reviewer_record.update({"sufficiency": sufficiency, "maturity": int(maturity), "reason": reason.strip()})
    copilot_inf = copilot_influence(cycle_id, final_read_override=final_reviewer_record)
    payload: dict[str, Any] = {
        "action": action, "sufficiency": sufficiency, "maturity": int(maturity),
        "governance_decision": governed,
        "reason": reason.strip(), "assessor_shown": bool(s.get("proposal")),
        "challenged": bool(s.get("challenges")), "revised_after_assessor": revised and bool(s.get("proposal")),
        "revised_after_compare": revised and bool(s.get("diff")),
        "revised_after_challenge": revised and bool(s.get("challenges")),
        "assessment_identity": s.get("assessment_identity"),
        "decision_time_freshness": freshness,
        "copilot_influence": copilot_inf,
        "blind_read_waiver": s.get("blind_read_waiver"),
    }
    if revised and blind:
        payload["supersedes"] = {k: blind.get(k) for k in ("sufficiency", "maturity", "reason")}
    if s.get("diff"):
        d = s["diff"]
        payload["element_diff"] = {"summary": d.get("summary"), "rating": d.get("rating"),
                                   "disagreements": d.get("disagreements"),
                                   "diff_sha": d.get("diff_sha")}
    # Optional GaaR Workstream A integration. Disabled by default. When enabled, the immutable
    # result is compiled before the decision event is committed. The pre-generated human_decision_id
    # is used as the decision event ID so the result and human decision share one authoritative ref.
    result_artifact = None
    if os.environ.get("WB_GAAR_RESULT_ENABLE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        import uuid
        from governance.result_integration import compile_for_decision, signer_from_env, persist_and_set_current
        human_decision_id = uuid.uuid4().hex
        decision_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        s_for_result = dict(s)
        s_for_result["_events"] = events.cycle(cycle_id)
        s_for_result["decision"] = payload
        s_for_result["decided_by"] = reviewer
        signer = signer_from_env()
        result = compile_for_decision(
            cycle_id=cycle_id,
            state=s_for_result,
            decision_payload=payload,
            human_decision_id=human_decision_id,
            decision_timestamp=decision_timestamp,
            signer=signer,
        )
        payload["human_decision_id"] = human_decision_id
        payload["governance_result_id"] = result.result_id
        events.append("decided", cycle_id=cycle_id, actor=reviewer, control_id=s["control_id"],
                      framework=s.get("framework", ""), payload=payload, event_id=human_decision_id)
        persisted = persist_and_set_current(result, actor_id=reviewer, decision_id=human_decision_id, governance_context=s.get("governance_context") or {}, cycle_id=cycle_id)
        result_artifact = persisted["result"]
        if persisted.get("quality_gate") is not None:
            gate = persisted["quality_gate"]
            payload["quality_gate"] = gate.model_dump(mode="json")
            events.append("quality_gate_evaluated", cycle_id=cycle_id, actor="quality-gate",
                          control_id=s["control_id"], framework=s.get("framework", ""),
                          payload={"quality_gate": gate.model_dump(mode="json"), "blocked": bool(persisted.get("blocked"))})
    else:
        events.append("decided", cycle_id=cycle_id, actor=reviewer, control_id=s["control_id"],
                      framework=s.get("framework", ""), payload=payload)
    if result_artifact is not None:
        payload["governance_result"] = result_artifact.model_dump(mode="json")
    return payload


# ---------------------------------------------------------------- views

def state(cycle_id: str) -> dict:
    return events.state(cycle_id)


def open_cycles() -> list[dict]:
    return [s for s in events.iter_states() if s.get("stage") != "decided"]


def record_observation(observation: dict, *, actor: str = "plugin", control_id: str = "",
                       framework: str = "") -> dict:
    """Record a globally scoped plugin observation before it is bound to any assessment cycle.

    `control_id` and `framework` are optional overrides for a caller that already knows which
    control it collected against. Without them the values are read off the observation itself,
    which is the right default for a provider sweep that is not yet attached to any control.
    """
    if not isinstance(observation, dict) or not observation:
        raise CycleError("an empty observation records nothing")
    return events.append("observed", cycle_id="", actor=actor,
                         control_id=(str(control_id).strip()
                                     or str((observation.get("resource") or "")).strip()),
                         framework=(str(framework).strip()
                                    or str((observation.get("provider") or "")).strip()),
                         payload={"observation": observation})
