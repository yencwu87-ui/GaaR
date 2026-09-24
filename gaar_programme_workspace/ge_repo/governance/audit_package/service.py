"""WB-123 package preparation from real existing cycle and Scout dossier state.

This module is a preparation boundary, NOT a new result-deciding engine. The existing
core cycle retains its blind-read and human decision requirements until a separately
approved policy migration is implemented and tested in the authoritative API.
"""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime,timezone
from typing import Any
from .policy_engine import ReviewContext, route_policy


def _stable_id(payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True, default=str, separators=(',', ':')).encode()
    return 'pkg_' + hashlib.sha256(data).hexdigest()[:24]


def prepare_package(*, cycle_id: str | None = None, dossier: dict | None = None,
                    context: ReviewContext | None = None, run_machine_steps: bool = False) -> dict:
    """Build honest review queue item; only existing Conductor may run machine steps.

    Scout dossier is automatically a collection checkpoint, not an admitted evidence
    set. A legacy cycle with missing blind read remains HUMAN_READ even for a policy
    classified routine; policy classification does not bypass the core cycle API.
    """
    if not cycle_id and not dossier:
        raise ValueError('cycle_id or verified dossier required')
    from governance.ai_auditor.conductor import ReviewConductor
    import events
    context = context or ReviewContext()
    policy = route_policy(context)
    inspection = None
    state = {}
    if cycle_id:
        conductor = ReviewConductor()
        if run_machine_steps:
            inspection = conductor.run_to_checkpoint(cycle_id)
        else:
            inspection = conductor.inspect(cycle_id)
        state = events.state(cycle_id) or {}
    if dossier:
        if dossier.get('binding_status') != 'PROPOSED_ONLY':
            raise ValueError('unrecognized dossier binding state')
        if not dossier.get('dossier_id') or not dossier.get('content_hash'):
            raise ValueError('verified dossier ID and content hash required')
    if not state and not dossier:
        raise ValueError('cycle not found')
    admitted_in_cycle = False
    if dossier and cycle_id and state.get('evidence'):
        from governance.admission import AdmissionStore
        proof = AdmissionStore().completed(dossier['dossier_id'], cycle_id)
        evidence = state['evidence']
        admitted_in_cycle = bool(proof and proof.get('evidence_set_id') == evidence.get('evidence_set_id')
            and evidence.get('admission_dossier_id') == dossier['dossier_id'])
        # A source validity deadline is evidence metadata, not a free-form context flag.
        fresh = False
        if admitted_in_cycle and evidence.get('fresh_until'):
            try:
                fresh = datetime.fromisoformat(evidence['fresh_until']) >= datetime.now(timezone.utc)
            except (ValueError, TypeError):
                pass
        context = replace(context, admitted_evidence=admitted_in_cycle,
                          freshness_verified=fresh)
        policy = route_policy(context)
    blockers: list[str] = []
    if dossier and not admitted_in_cycle:
        blockers.append('proposed_scout_dossier_requires_governed_evidence_admission')
    if not cycle_id:
        blockers.append('no_bound_review_cycle')
    if inspection and inspection.checkpoint not in {'HUMAN_DECISION','COMPLETE'}:
        blockers.append('core_cycle_checkpoint:' + inspection.checkpoint)
    if inspection and inspection.checkpoint == 'HUMAN_READ' and policy.name == 'routine':
        blockers.append('routine_blind_read_exemption_not_yet_enforced_in_core_cycle')
    if inspection and inspection.quality_audit and not inspection.quality_audit.ready:
        blockers.extend('preflight:' + b for b in inspection.quality_audit.blockers)
    if not context.admitted_evidence or not context.freshness_verified:
        blockers.append('authoritative_evidence_admission_or_freshness_unverified')
    if state.get('decision'):
        blockers.append('cycle_already_decided')
    if context.quality_blocked:
        blockers.append('quality_gate_blocked')
    if context.unresolved_strong_challenge:
        blockers.append('strong_challenge_unresolved')
    payload: dict[str,Any] = {'cycle_id':cycle_id,'control_id':state.get('control_id') or (dossier or {}).get('control_id'),
        'framework':state.get('framework') or (dossier or {}).get('framework'),
        'dossier_id':(dossier or {}).get('dossier_id'),'dossier_content_hash':(dossier or {}).get('content_hash'),
        'proposal':state.get('proposal'),'review_policy':asdict(policy),'policy_context':asdict(context),
        'conductor':inspection.model_dump(mode='json') if inspection else None,
        'binding_status':('ADMITTED_IN_CYCLE' if admitted_in_cycle else (dossier or {}).get('binding_status') if dossier else 'EXISTING_CYCLE'),
        'blockers':list(dict.fromkeys(blockers)), 'requires_human_decision':True,
        'human_decision_id':None, 'governance_result_id':None,
        'quality_gate_bypassed':False}
    payload['status'] = 'READY_FOR_HUMAN_REVIEW' if not payload['blockers'] else 'CHECKPOINT_REQUIRED'
    payload['package_id'] = _stable_id({k:v for k,v in payload.items() if k not in {'status','blockers'}})
    return payload


def batch_eligibility(packages: list[dict]) -> dict:
    """Read-only eligibility probe, never a batch decision or a result publisher."""
    if not packages:
        raise ValueError('nonempty package list required')
    if len(packages) > 25:
        raise ValueError('batch limit 25')
    ids = [p.get('package_id') for p in packages]
    if any(not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('unique valid package IDs required')
    reasons = {}
    for p in packages:
        problems = list(p.get('blockers') or [])
        if (p.get('review_policy') or {}).get('name') != 'routine':
            problems.append('nonroutine_individual_review')
        if p.get('status') != 'READY_FOR_HUMAN_REVIEW':
            problems.append('package_not_ready')
        if p.get('human_decision_id') or p.get('governance_result_id'):
            problems.append('already_decided')
        if p.get('quality_gate_bypassed') is not False:
            problems.append('quality_gate_integrity_unknown')
        if not p.get('cycle_id'):
            problems.append('no_governed_cycle')
        if problems:
            reasons[p['package_id']] = list(dict.fromkeys(problems))
    return {'eligible':not reasons, 'count':len(packages), 'blockers':reasons,
            'mode':'READ_ONLY_PREVIEW', 'human_decisions_created':0, 'results_published':0}


def require_explicit_human_action(*args, **kwargs):
    """Fail closed instead of impersonating the reviewer via a machine-side batch CLI."""
    raise PermissionError('Human decision must use the authorised, governed decision path; WB-123 preview is read-only')
