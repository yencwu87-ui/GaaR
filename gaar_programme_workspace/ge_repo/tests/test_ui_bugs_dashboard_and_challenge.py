"""Two reported defects: the Completed counter never moved, the challenger always errored."""
import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ------------------------------------------------------------------ dashboard

def test_cycle_state_resolves_from_the_ledger_not_only_the_session_cache():
    """`Completed` sat at zero because `_cycle_states` read only `S["cycle_ids"]`.

    Delete assessments.json, or open a new session, and every completed cycle became invisible —
    the queue saw no state, `next_action` stayed at step one, and the counter never moved however
    many decisions the ledger held.
    """
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    fn = src[src.index("def _cycle_states"):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert "events.cycles(control_id=" in fn, "the ledger is not consulted"
    assert "S.get(\"cycle_ids\")" in fn, "the session cache is still the fast path"


def test_the_ledger_lookup_takes_the_newest_cycle():
    """A control accumulates cycles; the current one is the last, not the first."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    fn = src[src.index("def _cycle_states"):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert "reversed(events.cycles(" in fn


def test_a_resolved_cycle_is_written_back_to_the_cache():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    fn = src[src.index("def _cycle_states"):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert 'S.setdefault("cycle_ids", {})[c.key] = candidate' in fn


def test_the_ledger_actually_holds_cycles_to_resolve(tmp_path):
    import events
    log = tmp_path / "events.jsonl"
    events.append("cycle_started", cycle_id="M3-6-test", actor="test",
                  control_id="M3.6", framework="MAS", path=log)
    assert events.cycles(path=log, control_id="M3.6") == ["M3-6-test"]


# ------------------------------------------------------------------ challenger

def _model(role="challenge", tier="critical", **env):
    import importlib
    keep = {k: os.environ.get(k) for k in
            ("OLLAMA_MODEL", "WB_INFERENCE_FALLBACK", "WB_MODEL_CHALLENGE_FALLBACK",
             "WB_MODEL_FAST", "WB_MODEL_CHALLENGE", "WB_MODEL_STRONG", "WB_MODEL_CRITICAL")}
    try:
        for k in keep:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in env.items() if v is not None})
        import inference.policy as P
        importlib.reload(P)
        return P._model_for_tier(tier, role)
    finally:
        for k, v in keep.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        import inference.policy as P
        importlib.reload(P)


def test_the_challenge_fallback_stays_within_the_operators_models():
    """The reported symptom: every challenge failed naming a model the user never asked for.

    Launching with OLLAMA_MODEL=qwen2.5:14b and only that model pulled, the first attempt timed
    out, the fallback engaged, and it pointed at a hardcoded llama3.1:8b that was not installed —
    so the challenger looked permanently broken when the fault was the fallback target.
    """
    got = _model(OLLAMA_MODEL="qwen2.5:14b", WB_INFERENCE_FALLBACK="1")
    assert got == "qwen2.5:14b", f"fallback left the operator's models: {got}"


def test_an_explicit_fallback_is_still_honoured():
    got = _model(OLLAMA_MODEL="qwen2.5:14b", WB_INFERENCE_FALLBACK="1",
                 WB_MODEL_CHALLENGE_FALLBACK="llama3.2:latest")
    assert got == "llama3.2:latest"


def test_the_fast_model_still_wins_over_the_default_when_set():
    got = _model(OLLAMA_MODEL="qwen2.5:14b", WB_INFERENCE_FALLBACK="1",
                 WB_MODEL_FAST="phi3:mini")
    assert got == "phi3:mini"


def test_no_fallback_leaves_the_normal_resolution_alone():
    assert _model(OLLAMA_MODEL="qwen2.5:14b") == "qwen2.5:14b"


def test_the_hardcoded_default_remains_only_as_a_last_resort():
    assert _model() == "llama3.1:8b"


def test_the_fallback_is_transport_only_and_never_a_verdict():
    """A model swap must not be able to change a governance outcome."""
    src = (ROOT / "inference" / "policy.py").read_text(encoding="utf-8")
    assert "never changes a governance verdict" in src


# ------------------------------------------------------------------ challenge status is current

def _counts(*envelopes):
    from review_queue import challenge_counts
    return challenge_counts({"challenges": list(envelopes)})


OK = {"validation_status": "ok",
      "challenges": [{"element_id": "e1", "response": None},
                     {"element_id": "e2", "response": None}]}
BLOCKED = {"validation_status": "blocked", "challenges": []}


def test_a_successful_retry_clears_an_earlier_blocked_pass():
    """One failed attempt used to mark the control blocked forever.

    The reported symptom: first attempt failed validation, the retry admitted two challenges, and
    the UI still showed a red Challenge pill and "no challenge survived validation" while the
    queue said "Review 2 open challenges" — three signals from the same data.
    """
    c = _counts(BLOCKED, OK)
    assert c["blocked"] is False
    assert c["produced_a_result"] is True
    assert c["unresolved"] == 2


def test_a_later_blocked_pass_is_the_current_state():
    c = _counts(OK, BLOCKED)
    assert c["blocked"] is True and c["produced_a_result"] is False


def test_earlier_attempts_are_not_discarded():
    """A pass that needed two attempts is a fact about the challenger worth keeping."""
    c = _counts(BLOCKED, OK)
    assert c["attempts"] == 2 and c["blocked_attempts"] == 1


def test_a_single_clean_pass_reports_no_blocked_attempts():
    c = _counts(OK)
    assert c["attempts"] == 1 and c["blocked_attempts"] == 0 and c["blocked"] is False


# ------------------------------------------------------------------ cycle duplication

def _fn(name):
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    body = src[src.index(f"def {name}("):]
    return body[:body.index("\ndef ", 10)]


def test_a_cache_miss_reuses_the_ledger_cycle_instead_of_starting_another():
    """The dashboard's real cause: 33 cycles for M3.6, 33 for M1.2, across 4 controls.

    Every session-cache miss started a fresh cycle, so a reading recorded against one cycle was
    invisible to a queue projecting another — "Your reading ✓" and Completed 0 were both true,
    about different cycles.
    """
    fn = _fn("_ensure_cycle")
    assert "events.cycles(control_id=c.id)" in fn
    assert "reversed(" in fn
    assert fn.index("events.cycles(control_id=c.id)") < fn.index("governance_cycle.start("), \
        "the ledger must be consulted before a new cycle is started"


def test_a_superseded_cycle_is_not_reused():
    """Superseding is deliberate; a cache miss must not undo it."""
    assert 'st_.get("superseded_by")' in _fn("_ensure_cycle")


def test_a_new_cycle_is_still_started_when_the_ledger_has_none():
    fn = _fn("_ensure_cycle")
    assert "governance_cycle.start(" in fn


# ------------------------------------------------------------------ challenge labelling

def test_the_challenge_label_does_not_invent_a_severity():
    """"Challenge 1 · MEDIUM · rejected" — MEDIUM was a default, not an assessment."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'q.get("severity","medium")' not in src
    assert 'f\' · severity {_sev}\' if _sev else \'\'' in src


def test_rejected_is_explained_as_the_machine_refusing_the_challenge():
    """It is the gate's verdict on the challenge, not the reviewer rejecting a finding."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "not admitted — the challenger could not ground this" in src
    assert "weak — refining, not a rebuttal" in src
    assert "strong — a substantive rebuttal" in src


# ------------------------------------------------------------------ defect repairs

def test_the_history_tab_has_a_body():
    """It was declared in the tab strip and implemented nowhere — it rendered empty."""
    import re
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*with tab_h:", src, re.M)) == 1       # kit v21: indented under `if tab_h.shown:`


def test_the_history_tab_reads_the_ledger_not_the_session_cache():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    tab = src.split("with tab_h:")[1]
    assert "events.iter_states" in tab and "events.cycle(" in tab


def test_contract_validation_prefers_the_contract_over_the_workbook_column():
    """25 controls were CONTRACT_INVALID because `write_back` corrupts the workbook's evidence
    column with requirement sentences. The clean artefact names were in the contract all along."""
    src = (ROOT / "governance" / "contract_integrity.py").read_text(encoding="utf-8")
    fn = src[src.index("def status_for_control"):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert 'contract.get("expected_evidence")' in fn
    assert fn.index('contract.get("expected_evidence")') < fn.index('getattr(control, "artefacts"'), \
        "the contract must be consulted before the workbook column"


def test_the_workbook_column_is_still_the_fallback():
    """For controls whose contract declares nothing, it is the only source there is."""
    src = (ROOT / "governance" / "contract_integrity.py").read_text(encoding="utf-8")
    fn = src[src.index("def status_for_control"):]
    assert "if not declared:" in fn


def test_no_control_is_contract_invalid_any_more():
    import glob
    import playbook
    from governance.contract_integrity import status_for_control
    books = glob.glob(str(ROOT / "data" / "*.xlsx"))
    if not books:
        pytest.skip("no workbook present")
    idx = playbook.load_controls(books[0])
    bad = [c.id for lib in idx.values() for c in lib
           if not status_for_control(c).get("executable", True)]
    assert bad == [], f"still invalid: {bad[:8]}"


# ------------------------------------------------------------------ challenge retry path

def test_a_barren_disagreement_run_can_be_retried():
    """`if not ch2` hid the button after ANY stored result, including one that admitted nothing.

    The challenger must quote the evidence character for character and a paraphrase is refused by
    design, so two or three attempts is normal operation. Removing the retry path after a barren
    run left the reviewer stuck with no way to run it again.
    """
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "if not ch2 and st.button" not in src, "the old gate is back"
    assert "_ch2_admitted and st.button" in src


def test_the_gate_is_admitted_challenges_not_the_existence_of_a_run():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '_ch2_admitted = bool((ch2 or {}).get("challenges"))' in src


def test_a_barren_run_explains_itself_rather_than_going_silent():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "admitted nothing" in src
    assert "not the same as" in src and "nothing being found" in src
    assert "often needs more than one" in src


def test_the_retry_button_says_it_is_a_retry():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "Try the disagreement challenge again" in src


def test_challenge_my_reading_was_already_retryable():
    """The asymmetry that made this reproducible: one button retried, the other vanished."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    i = src.index('st.button("Challenge my reading"')
    window = src[max(0, i - 200):i]
    assert "if not ch and" not in window
