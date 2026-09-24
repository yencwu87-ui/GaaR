"""WB-129: one understandable audit outcome, never a surrogate governance state."""
from __future__ import annotations


def cycle_trace(rows: list[dict], cycle_id: str) -> list[dict]:
    return [e for e in rows if e.get('cycle_id') == cycle_id]


def audit_outcome(state: dict, trace: list[dict], *, checkpoint: str = '', reasons: list[str] | None = None,
                  living: dict | None = None) -> dict:
    """Project ONE cycle. Missing evidence beats any historical assessment proposal.

    An evidence-free proposal is an integrity alert, not a decision-ready package.
    A sealed FINALIZED/BLOCKED result never becomes 'audit complete'.
    """
    reasons = list(reasons or [])
    evs = cycle_trace(trace, str(state.get('cycle_id') or ''))
    kinds = [e.get('kind') for e in evs]
    evidence_at = next((i for i,e in enumerate(evs) if e.get('kind') == 'evidence_bound'), None)
    stray = [e for i,e in enumerate(evs) if e.get('kind') == 'proposed' and (evidence_at is None or i < evidence_at)]
    outcome = dict(control_id=state.get('control_id') or '—', cycle_id=state.get('cycle_id') or '—',
                   framework=state.get('framework') or '—', proposed=state.get('proposal'),
                   status='AUDIT_RUNNING', headline='Audit needs another step', detail='',
                   action='Inspect the next governed checkpoint', evidence_free_proposals=len(stray),
                   events=len(evs), reasons=reasons)
    if stray:
        outcome.update(status='PROBLEM_NEEDS_ATTENTION', headline='Assessment recorded before evidence was bound',
                       detail='This cycle has an assessment proposal without preceding bound evidence. The proposal is not a grounded audit result.',
                       action='Investigate this cycle; do not approve the proposal')
        return outcome
    if not state.get('evidence'):
        outcome.update(status='EVIDENCE_NEEDED', headline='Evidence needed before an audit conclusion',
                       detail='No evidence is bound to this review cycle.',
                       action='Find evidence, inspect the dossier and explicitly admit it')
        return outcome
    living = living or {}
    if state.get('decision'):
        if living.get('current_state') == 'CURRENT' and living.get('quality_gate') == 'FINALIZABLE':
            outcome.update(status='AUDIT_COMPLETE', headline='Governance result is current',
                           detail='A human decision was recorded and the result passed the final gate.',
                           action='View the Governance Passport')
        else:
            outcome.update(status='PROBLEM_NEEDS_ATTENTION', headline='Decision recorded; publication not verified',
                           detail=f"Result state: {living.get('current_state', 'not verified')}; quality: {living.get('quality_gate', 'not verified')}.",
                           action='Inspect the final Quality Gate and result state')
        return outcome
    if checkpoint in {'HUMAN_EXCEPTION', 'CHALLENGE_REQUIRED'}:
        outcome.update(status='PROBLEM_NEEDS_ATTENTION', headline='An issue needs your attention',
                       detail='; '.join(reasons) or 'A required independent challenge or exception remains open.',
                       action='Investigate the blocker before deciding')
    elif checkpoint in {'HUMAN_READ', 'HUMAN_COMPARISON'}:
        outcome.update(status='YOUR_REVIEW_NEEDED', headline='Your independent review is needed',
                       detail='This review policy requires a human reading or comparison before the final decision.',
                       action='Complete the independent review in the Review tab')
    elif checkpoint == 'HUMAN_DECISION':
        outcome.update(status='READY_FOR_DECISION', headline='Ready for your decision',
                       detail='Review the proposal, evidence, challenge and limitations before approving.',
                       action='Approve, investigate or reject the proposal')
    elif checkpoint == 'EVIDENCE_REQUIRED':
        outcome.update(status='EVIDENCE_NEEDED', headline='More evidence needed',
                       detail='; '.join(reasons) or 'The evidence preflight requires more records.',
                       action='Find and admit evidence')
    return outcome
