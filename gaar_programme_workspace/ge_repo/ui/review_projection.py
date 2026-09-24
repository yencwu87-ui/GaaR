"""Pure shared review-state projection. Importing this never starts Streamlit."""

def _queue_markers(r) -> str:
    """The one-line step summary on each review-queue row.

    WB-108: this row ticked `AI ✓` while `Read —`, announcing across every row in the queue that
    a proposal was finished and waiting before the reviewer had read anything. WB-106 fixed the
    same display in the workspace progress bar and missed this one, which is the more exposed of
    the two — the queue is the first screen, and it says it for every control at once.

    A ready proposal behind an open blind read is shown `⏸`, matching the workspace. The
    proposal itself stays withheld either way; what changes is that the queue no longer presents
    a gated step as a completed one.

    Completeness and Challenge are included because the queue previously showed four of the
    seven steps, and a summary that silently omits steps is how the two indicators drifted apart
    in the first place.
    """
    ch = r.get("challenge") or {}
    if r.get("proposal_error"):
        ai = "!"
    elif not r.get("has_proposal"):
        ai = "—"
    elif not r.get("has_read"):
        ai = "⏸"
    else:
        ai = "✓"
    if not r.get("has_compare"):
        chal = "—"
    elif ch.get("blocked"):
        chal = "⚠"
    elif ch.get("produced_a_result"):
        chal = "✓" if not (ch.get("unresolved") or ch.get("unresolved_strong")) else "!"
    else:
        chal = "—"
    if r.get("contract_blocked"):
        # GE-110: one line, not a step strip. A blocked contract has no steps to be partway
        # through, and showing "Evidence ✓" beside it would imply progress that cannot happen.
        return "⛔ CONTRACT INVALID — assessment not executable"
    tick = lambda v: "✓" if v else "—"
    marks = {"evidence": tick(r.get("has_evidence")),
             "completeness": tick(r.get("has_completeness")),
             "reading": tick(r.get("has_read")),
             "assessment": ai,
             "compare": tick(r.get("has_compare")),
             "challenge": chal}
    # Keyed by REVIEW_STEPS so a step added to the workflow cannot silently vanish from the
    # queue summary — the drift that produced two disagreeing indicators in the first place.
    return " · ".join(f"{QUEUE_LABELS[k]} {marks[k]}" for k in REVIEW_STEPS if k in marks)


def _ai_proposed_clause(d, proposal):
    """How the report describes the assessor's position beside the recorded decision.

    WB-107: this line crashed with KeyError on every decision made through the review
    workspace. It guarded with `d.get('aiSufficiency')` and then read `d['aiSufficiency']`, and
    since `cycle.decide()` never writes that key the guard was always true and the read always
    failed. Only `pipeline.record_decision` sets it, and the app stopped using that path.

    The deeper error is the one the guard was making: `None != 'partial'` was read as "the AI
    proposed something different". Absent is not a value. There are three cases and the report
    now says which — the assessor agreed, the assessor proposed something else, or the assessor
    produced nothing at all. Reporting a failed or missing assessment as a difference of opinion
    would put a disagreement in the record that never happened.
    """
    ai = (d.get("aiSufficiency")
          or (proposal or {}).get("sufficiency"))
    if (proposal or {}).get("model") == "error":
        return " (the assessor call failed — no proposal was produced)"
    if not ai:
        return " (no assessor proposal was recorded)"
    if ai == d.get("sufficiency"):
        return ""
    return f" (AI proposed {ai})"


REVIEW_STEPS = ["evidence", "completeness", "reading", "assessment", "compare", "challenge",
                "decision"]


QUEUE_LABELS = {"evidence": "Evidence", "completeness": "Completeness", "reading": "Read",
                "assessment": "AI", "compare": "Compare", "challenge": "Challenge"}


def _review_step_states(row, current):
    """(label, state) for every step, from one projection of the cycle.

    `state` is 'done', 'now', 'wait' or 'held'. 'held' is the one worth explaining: a step whose
    own work is finished but which is gated behind an upstream step the reviewer has not reached.
    The assessor runs concurrently so the reviewer never waits on it, which previously meant the
    strip showed a green tick on 'AI assessment' while 'Your reading' was still pending — a
    completed step displayed ahead of the step that gates it. It never leaked the rating, but it
    announced that a proposal was ready and had succeeded, which is a nudge toward hurrying the
    reading, and it made the enforced order look broken. 'held' says ready-but-withheld instead.
    """
    ch = row.get("challenge") or {}
    done = {
        "evidence": bool(row.get("has_evidence")),
        # A scan that ran is done, whatever it found: gaps are a result, not an unfinished step.
        "completeness": bool(row.get("has_completeness")),
        "reading": bool(row.get("has_read")),
        "assessment": bool(row.get("has_proposal")) and not row.get("proposal_error"),
        "compare": bool(row.get("has_compare")),
        # A challenge step is done when a challenge pass actually produced a result and nothing
        # is left unresolved. A pass that never ran, or whose output was rejected in validation,
        # is not a clean challenge — it is no challenge, and must not show as complete.
        "challenge": (ch.get("produced_a_result", False)
                      and not (ch.get("unresolved") or ch.get("unresolved_strong"))
                      if row.get("has_compare") else False),
        "decision": bool(row.get("decision")),
    }
    out = []
    for step in REVIEW_STEPS:
        if step == "assessment" and done["assessment"] and not done["reading"]:
            state = "held"
        elif step == "challenge" and ch.get("blocked"):
            state = "blocked"
        elif done[step]:
            state = "done"
        elif step == current:
            state = "now"
        else:
            state = "wait"
        out.append((_review_label(step), state))
    return out


def _review_label(step):
    return {
        "evidence": "Evidence", "completeness": "Completeness", "reading": "Your reading",
        "assessment": "AI assessment", "compare": "Compare", "challenge": "Challenge",
        "decision": "Decision", "summary": "Complete"
    }.get(step, step.title())
