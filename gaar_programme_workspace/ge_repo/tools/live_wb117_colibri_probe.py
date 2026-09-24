#!/usr/bin/env python3
"""Read-only WB-117 governed Colibri escalation probe.

Builds the same deterministic inference plan used by the engine and prints the deep-reasoning
policy decision. It does not call an LLM unless --health is supplied, and --health only checks the
Colibri service endpoint.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from inference.policy import TaskSignals, build_plan, governed_colibri_decision


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--role', default='assess')
    ap.add_argument('--control-id', default='probe')
    ap.add_argument('--control-score', type=int, default=0)
    ap.add_argument('--ambiguity', type=float, default=0.0)
    ap.add_argument('--prior-failures', type=int, default=0)
    ap.add_argument('--reviewer-disagreement', action='store_true')
    ap.add_argument('--high-risk', action='store_true')
    ap.add_argument('--regulatory-freshness', action='store_true')
    ap.add_argument('--evidence-contradiction', action='store_true')
    ap.add_argument('--material-change', action='store_true')
    ap.add_argument('--unresolved-strong-challenge', action='store_true')
    ap.add_argument('--health', action='store_true')
    args=ap.parse_args()
    sig=TaskSignals(role=args.role, control_id=args.control_id,
                    ambiguity=args.ambiguity, prior_failures=args.prior_failures,
                    reviewer_disagreement=args.reviewer_disagreement, high_risk=args.high_risk,
                    regulatory_freshness=args.regulatory_freshness,
                    evidence_contradiction=args.evidence_contradiction,
                    material_change=args.material_change,
                    unresolved_strong_challenge=args.unresolved_strong_challenge,
                    control_complexity_score=args.control_score)
    plan=build_plan(sig)
    decision=governed_colibri_decision(plan.tier,sig)
    out={
        'control_id': args.control_id, 'role': args.role,
        'tier': plan.tier, 'provider': plan.provider, 'model': plan.model,
        'generation_budget': plan.num_predict, 'context_budget': plan.num_ctx,
        'control_complexity_band': plan.control_complexity_band,
        'deep_reasoning': plan.deep_reasoning,
        'escalation_policy': plan.escalation_policy,
        'escalation_reasons': list(plan.escalation_reasons),
        'policy_decision': decision,
    }
    if args.health:
        from llm.colibri import health
        out['colibri_health']=health()
    print(json.dumps(out, indent=2, default=str))
    return 0
if __name__=='__main__': raise SystemExit(main())
