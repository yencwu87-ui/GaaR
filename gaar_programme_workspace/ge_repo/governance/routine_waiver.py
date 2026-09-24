"""WB-125: explicit, signed, fail-closed policy for waiving an intermediate *blind* read.

This does not authenticate CLI-supplied people, waive a final human decision, or prove
that an LLM challenge actually ran. The policy must be enabled and approved by an
external governance process. In local mode --actor is an attribution, not IAM/RBAC.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

VERSION = 'gaar.routine-blind-waiver.v1'
ENV_FILE = 'WB_GAAR_ROUTINE_POLICY_FILE'
ENV_ENABLED = 'WB_GAAR_ROUTINE_WAIVER_ENABLED'


class WaiverDenied(ValueError):
    pass


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def policy_approval(*, approved_by: str, reason: str, signer, approved_at: str | None = None) -> dict:
    if not approved_by.strip() or approved_by.strip().lower() in {'ai','system','anonymous','ai-auditor'}:
        raise WaiverDenied('named human policy approver required')
    if len(reason.strip()) < 16:
        raise WaiverDenied('policy approval requires a substantial reason')
    body = {'schema':VERSION, 'tier':'routine', 'waive':['blind_read','comparison'],
            'human_final_decision_required':True, 'quality_gate_required':True,
            'require_admitted_evidence':True, 'require_prior_decision':True,
            'approved_by':approved_by.strip(), 'reason':reason.strip(),
            'approved_at':approved_at or datetime.now(timezone.utc).isoformat()}
    return {**body,'seal':{'algorithm':'Ed25519','key_id':signer.key_id,
            'public_key_b64':signer.public_key_b64,
            'signature':signer.sign(canonical(body))}}


def verify_policy(approval: dict, *, signer=None) -> bool:
    from governance.result_integration import signer_from_env
    signer = signer or signer_from_env()
    try:
        body = {k:v for k,v in approval.items() if k != 'seal'}
        seal = approval['seal']
        if (body['schema'] != VERSION or body['tier'] != 'routine' or
            body['waive'] != ['blind_read','comparison'] or
            body['human_final_decision_required'] is not True or
            body['quality_gate_required'] is not True or
            body['require_admitted_evidence'] is not True or
            body['require_prior_decision'] is not True or
            not body['approved_by'] or len(body['reason']) < 16 or
            seal['algorithm'] != 'Ed25519' or seal['key_id'] != signer.key_id or
            seal['public_key_b64'] != signer.public_key_b64):
            return False
        return signer.verify(canonical(body), seal['signature'])
    except (KeyError, TypeError, ValueError):
        return False


def approved_policy() -> dict:
    if os.environ.get(ENV_ENABLED,'').lower() not in {'1','true','yes','on'}:
        raise WaiverDenied('routine waiver disabled by default')
    loc = os.environ.get(ENV_FILE,'').strip()
    if not loc:
        raise WaiverDenied('explicit signed routine policy path required')
    path = Path(loc)
    if path.is_symlink() or not path.is_file():
        raise WaiverDenied('signed policy file absent or symlinked')
    try:
        approval = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError) as exc:
        raise WaiverDenied('policy file invalid') from exc
    if not isinstance(approval,dict) or not verify_policy(approval):
        raise WaiverDenied('policy signature or terms invalid')
    return approval


def _prior_decision(state: dict) -> bool:
    """A synthetic `decided` event is insufficient; require its sealed stored result."""
    import events
    from governance.result_store import ResultStore
    try:
        result_path = os.environ.get('WB_GAAR_RESULT_STORE','').strip()
        results = ResultStore(result_path).read() if result_path else ResultStore().read()
        by_id = {r.result_id:r for r in results}
        for s in events.iter_states():
            if (s.get('cycle_id') == state['cycle_id'] or
                s.get('control_id') != state['control_id'] or
                s.get('framework') != state['framework'] or not s.get('decision')):
                continue
            d=s['decision']
            r=by_id.get(d.get('governance_result_id'))
            if (r and d.get('human_decision_id') and
                r.provenance.human_decision_id == d['human_decision_id'] and
                r.provenance.human_decider_id == s.get('decided_by') and
                r.control_id == state['control_id']):
                r.validate_internal_consistency()
                return True
    except (ValueError,KeyError,OSError,RuntimeError):
        return False
    return False


def _verified_admission(state: dict) -> bool:
    """Verify the completed ledger event AND its signed prepared/bound bundle."""
    from governance.admission import AdmissionStore
    from governance.result_integration import signer_from_env
    from governance.evidence_scout.dossier import canonical as admission_canonical, sha256
    ev = state.get('evidence') or {}
    dossier_id = ev.get('admission_dossier_id')
    eid = ev.get('evidence_set_id')
    if not dossier_id or not eid:
        return False
    try:
        rows = AdmissionStore().read()
        bound = [r['payload'] for r in rows if r['record_type']=='EvidenceCycleBound'
                 and r['payload'].get('dossier_id')==dossier_id and
                 r['payload'].get('cycle_id')==state['cycle_id']]
        if len(bound)!=1 or bound[0].get('cycle_evidence_bound') is not True or bound[0].get('evidence_set_id')!=eid:
            return False
        prepared = [r['payload'] for r in rows if r['record_type']=='EvidenceAdmissionPrepared'
                    and r['payload'].get('dossier_id')==dossier_id and
                    r['payload'].get('cycle_id')==state['cycle_id']]
        if len(prepared)!=1:return False
        admission=prepared[0]
        signer=signer_from_env()
        seal=admission.get('seal') or {}
        return bool(admission.get('evidence_set_id')==eid and
                    admission.get('bundle_hash')==sha256(admission_canonical(ev)) and
                    bound[0].get('admission_signature')==seal.get('signature') and
                    seal.get('key_id')==signer.key_id and
                    seal.get('public_key_b64')==signer.public_key_b64 and
                    signer.verify(admission_canonical({k:v for k,v in admission.items() if k!='seal'}),
                                  seal.get('signature','')))
    except (KeyError,TypeError,ValueError,OSError,RuntimeError):
        return False

def eligibility(state: dict, *, require_challenge: bool = False) -> list[str]:
    """Fail closed. Context alone cannot assert `first_assessment=False` or admission."""
    from governance.audit_package.policy_engine import ReviewContext, route_policy
    from core.cycle import _decision_time_freshness
    if not state or state.get('decision'):
        return ['missing_or_decided_cycle']
    ctx = state.get('governance_context') or {}
    evidence = state.get('evidence') or {}
    issues = []
    if not _prior_decision(state): issues.append('first_assessment_or_no_prior_decision')
    if not _verified_admission(state): issues.append('no_ledger_verified_admitted_evidence')
    fresh = _decision_time_freshness(state)
    if fresh['status'] != 'known': issues.append('freshness_unknown_stale_or_invalid')
    if not state.get('proposal'): issues.append('assessor_proposal_missing')
    # Confidence is not assumed; must be independently provided in governed cycle context.
    confidence = ctx.get('assessment_confidence')
    if not isinstance(confidence,(int,float)) or isinstance(confidence,bool) or not 0<=confidence<=1:
        confidence = None
    review_context = ReviewContext(
        risk_tier=str(ctx.get('risk_tier') or 'unknown'),
        first_assessment=not _prior_decision(state),
        material_change=ctx.get('material_change') is not False,
        evidence_contradiction=ctx.get('evidence_contradiction') is not False,
        unresolved_strong_challenge=ctx.get('unresolved_strong_challenge') is not False,
        quality_blocked=ctx.get('quality_blocked') is not False,
        governance_exception=ctx.get('governance_exception') is not False,
        assessment_confidence=confidence,
        admitted_evidence=_verified_admission(state),
        freshness_verified=fresh['status']=='known',
        independent_review_required=ctx.get('independent_review_required') is not False,
    )
    try:
        tier=route_policy(review_context)
        if tier.name != 'routine': issues.append('policy_router_requires_'+tier.name)
    except (TypeError,ValueError): issues.append('invalid_review_context')
    if state.get('read') or state.get('diff'):
        issues.append('blind_read_or_compare_already_exists_use_standard_path')
    if require_challenge:
        from governance.independent_challenge import verify_for_decision
        issues.extend(verify_for_decision(state))
        chs = state.get('challenges') or []
        if not chs: issues.append('independent_challenge_not_recorded')
        for c in chs:
            if c.get('validation_status') == 'blocked' or c.get('blocked') or c.get('validation_error'):
                issues.append('challenge_validation_blocked')
            for row in c.get('challenges') or []:
                if (str(row.get('strength') or row.get('challenge_strength') or '').lower() == 'strong'
                    and not (row.get('resolved') is True or row.get('status') == 'resolved'
                             or row.get('resolution') in ('accepted','rejected'))):
                    issues.append('unresolved_strong_challenge')
    return list(dict.fromkeys(issues))


def applied_waiver(state: dict) -> dict | None:
    import events
    rows = [e for e in events.cycle(state.get('cycle_id','')) if e.get('kind')=='blind_read_waived']
    if len(rows)!=1: return None
    record=rows[0].get('payload') or {}
    try:
        policy=approved_policy()
    except (WaiverDenied,RuntimeError):
        return None
    if (record.get('policy_sha256') != hashlib.sha256(canonical(policy)).hexdigest() or
        record.get('policy_version') != VERSION or record.get('control_id') != state.get('control_id')):
        return None
    return record


def apply(cycle_id: str, *, actor: str = 'governance-policy-engine') -> dict:
    """Append one waiver event; never synthesize a read, diff, challenge, decision or result."""
    import events
    policy=approved_policy()
    state=events.state(cycle_id)
    if not state: raise WaiverDenied('no such cycle')
    if applied_waiver(state): raise WaiverDenied('waiver already recorded')
    issues=eligibility(state)
    if issues: raise WaiverDenied('; '.join(issues))
    payload={'schema':VERSION,'control_id':state['control_id'],'cycle_id':cycle_id,
             'policy_sha256':hashlib.sha256(canonical(policy)).hexdigest(),
             'policy_version':VERSION, 'approved_by':policy['approved_by'],
             'policy_key_id':policy['seal']['key_id'],
             'waived':['blind_read','comparison'],'human_final_decision_required':True,
             'quality_gate_required':True,'reasons':['admitted prior-review routine cycle, all required eligibility conditions met']}
    return events.append('blind_read_waived',cycle_id=cycle_id,actor=actor,
                         control_id=state['control_id'],framework=state.get('framework',''),payload=payload)
