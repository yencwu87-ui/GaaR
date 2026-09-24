from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import events
from core import cycle as governance_cycle
from review_queue import challenge_counts
from governance.control_contract import requirement_context as governed_requirement_context

from .policy import load_policy
from .schemas import (
    ChallengeAuditInput, ConductorDecision, ControlNarrativeInput, EvidenceExaminerInput,
    QualityAuditInput, RequirementElement,
)
from .skills import evidence_examiner, challenge_auditor, control_narrative, quality_auditor


@dataclass
class ReviewConductor:
    """The only agentic component in WB-115.

    It may sequence approved functions and bounded skills, but it never synthesizes a human read,
    never records a final decision, and never writes GovernanceResult validity state directly.
    """

    policy_path: str | None = None

    @property
    def policy(self):
        return load_policy(self.policy_path)

    def _control(self, state: dict):
        return governance_cycle._control_for_state(state)

    def _req_elements(self, control, state: dict) -> list[RequirementElement]:
        override = (state.get("governance_context") or {}).get("requirement_override") or {}
        raw = override.get("elements") if isinstance(override, dict) else None
        if not raw:
            raw = [{"element_id": eid, "text": text} for eid, text in (getattr(control, "elements", ()) or ())]
        out = []
        for idx, item in enumerate(raw or []):
            if isinstance(item, dict):
                eid = str(item.get("element_id") or item.get("id") or f"e{idx+1}")
                text = str(item.get("text") or "").strip()
                note = str(item.get("note") or "")
            else:
                continue
            if text:
                out.append(RequirementElement(element_id=eid, text=text, note=note))
        if not out:
            ctx = governed_requirement_context(state.get("control_id", ""), state.get("framework", "")) or {}
            for idx, item in enumerate(ctx.get("elements") or []):
                if isinstance(item, dict) and str(item.get("text") or "").strip():
                    out.append(RequirementElement(
                        element_id=str(item.get("id") or item.get("element_id") or f"e{idx+1}"),
                        text=str(item.get("text") or "").strip(), note=str(item.get("note") or "")))
        return out

    def inspect(self, cycle_id: str) -> ConductorDecision:
        state = events.state(cycle_id)
        if not state:
            raise ValueError(f"cycle not found: {cycle_id}")
        control = self._control(state)
        ev = state.get("evidence") or {}
        invoked: list[str] = []
        reasons: list[str] = []
        evidence_report = None
        challenge_report = None
        quality = None

        from governance.investigation.bridge import required as investigation_required, cycle_gate
        investigation_mode = investigation_required(state)
        investigation_gate = cycle_gate(state) if investigation_mode else {}
        if investigation_mode and not investigation_gate.get("assessment_finalizable"):
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                stage="investigation", next_action="Complete the signed investigation through the engine service",
                checkpoint="INVESTIGATION_REQUIRED", reasons=investigation_gate.get("blockers", []),
                invoked_skills=["investigation_context"])

        if not ev:
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                     stage="evidence", next_action="Bind evidence", checkpoint="EVIDENCE_REQUIRED",
                                     reasons=["No evidence is bound to the cycle."])

        elems = self._req_elements(control, state)
        req_vid = str((state.get("governance_context") or {}).get("requirement_version_id") or f"cycle:{cycle_id}:requirement")
        evid = str((state.get("governance_context") or {}).get("evidence_set_id") or f"cycle:{cycle_id}:evidence")
        evidence_report = evidence_examiner.run(EvidenceExaminerInput(
            control_id=state["control_id"], framework=state.get("framework", ""), requirement_version_id=req_vid,
            evidence_set_id=evid, requirement_context=elems, evidence_text=str(ev.get("text") or ""),
            evidence_age_days=ev.get("age_days"),
        ), threshold=self.policy.evidence_sufficiency_threshold, max_age_days=self.policy.freshness_max_age_days)
        invoked.append("evidence_examiner")
        if evidence_report.recommended_action == "COLLECT_MORE" and not investigation_mode:
            reasons.extend(evidence_report.open_evidence_gaps or ["Evidence preflight recommends collection before autonomous progression."])
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                     stage="evidence", next_action="Collect or confirm evidence", checkpoint="EVIDENCE_REQUIRED",
                                     reasons=reasons, invoked_skills=invoked, evidence_examiner=evidence_report)

        # The approved routine waiver replaces a mid-cycle read/compare, not a
        # challenge or the final human decision. No synthetic comparison is written.
        if state.get("blind_read_waiver"):
            from governance.routine_waiver import applied_waiver, eligibility
            if not applied_waiver(state):
                return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                    stage="policy", next_action="Restore signed policy or use the standard blind read", checkpoint="HUMAN_EXCEPTION",
                    reasons=["Routine waiver policy not active or signature invalid"], invoked_skills=invoked,
                    evidence_examiner=evidence_report)
            if not state.get("proposal"):
                return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                    stage="assessment", next_action="Run assessor", checkpoint="NONE", invoked_skills=invoked,
                    evidence_examiner=evidence_report)
            if not state.get("challenges"):
                return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                    stage="challenge", next_action="Run independent proposal challenge", checkpoint="CHALLENGE_REQUIRED",
                    reasons=["No independent challenge is recorded; a waived blind read is not a waived challenge"],
                    invoked_skills=invoked, evidence_examiner=evidence_report)
            blockers = eligibility(state, require_challenge=True)
            if blockers:
                return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                    stage="policy", next_action="Review new exception and restore full review if necessary", checkpoint="HUMAN_EXCEPTION",
                    reasons=blockers, invoked_skills=invoked, evidence_examiner=evidence_report)
            quality = quality_auditor.run(QualityAuditInput(cycle_id=cycle_id, require_human_decision=bool(state.get("decision"))))
            invoked.append("quality_auditor")
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                stage="decision", next_action="Record human governance decision", checkpoint=("COMPLETE" if state.get("decision") else "HUMAN_DECISION"),
                reasons=quality.blockers if not quality.ready else ["Routine waiver applied; final human decision still required"],
                invoked_skills=invoked, evidence_examiner=evidence_report, quality_audit=quality)

        if not state.get("read"):
            # Proposal may be prepared before the blind read, but must remain hidden. This reduces latency
            # without compromising the blindness rule enforced by proposal_for_reviewer().
            next_action = "Record independent reviewer reading"
            if not state.get("proposal"):
                next_action = "AI may pre-compute assessment; human blind read remains the next visible checkpoint"
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                     stage="blind_read", next_action=next_action, checkpoint="HUMAN_READ",
                                     reasons=["Reviewer blindness is a governed checkpoint."], invoked_skills=invoked,
                                     evidence_examiner=evidence_report)

        if not state.get("proposal"):
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                     stage="assessment", next_action="Run assessor", checkpoint="NONE",
                                     invoked_skills=invoked, evidence_examiner=evidence_report)
        if not state.get("diff"):
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                     stage="comparison", next_action="Compare reviewer and assessor", checkpoint="NONE",
                                     invoked_skills=invoked, evidence_examiner=evidence_report)

        ch = challenge_counts(state)
        if state.get("challenges"):
            latest = [x for x in state.get("challenges") or [] if isinstance(x, dict)][-1]
            challenge_report = challenge_auditor.run(ChallengeAuditInput(control_id=state["control_id"], challenge_envelope=latest))
            invoked.append("challenge_auditor")
            if challenge_report.recommended_action == "REQUIRE_HUMAN":
                return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                         stage="challenge", next_action="Resolve challenge exception", checkpoint="HUMAN_EXCEPTION",
                                         reasons=challenge_report.reasons, invoked_skills=invoked,
                                         evidence_examiner=evidence_report, challenge_audit=challenge_report)

        if not state.get("decision"):
            quality = quality_auditor.run(QualityAuditInput(cycle_id=cycle_id, require_human_decision=False))
            invoked.append("quality_auditor")
            return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                     stage="decision", next_action="Record human governance decision", checkpoint="HUMAN_DECISION",
                                     reasons=quality.blockers if not quality.ready else ["Automated review stages are complete."],
                                     invoked_skills=invoked, evidence_examiner=evidence_report,
                                     challenge_audit=challenge_report, quality_audit=quality)

        quality = quality_auditor.run(QualityAuditInput(cycle_id=cycle_id, require_human_decision=True))
        invoked.append("quality_auditor")
        return ConductorDecision(cycle_id=cycle_id, control_id=state["control_id"], framework=state.get("framework", ""),
                                 stage="complete", next_action="Governance result complete", checkpoint="COMPLETE",
                                 reasons=quality.blockers, invoked_skills=invoked, evidence_examiner=evidence_report,
                                 challenge_audit=challenge_report, quality_audit=quality)

    def run_to_checkpoint(self, cycle_id: str, *, actor: str = "ai-auditor", reviewer_actor: str | None = None) -> ConductorDecision:
        """Advance approved machine steps until the next human/evidence checkpoint.

        The method deliberately has no branch that calls governance_cycle.decide().
        """
        for _ in range(8):
            decision = self.inspect(cycle_id)
            if (decision.checkpoint == "CHALLENGE_REQUIRED" and
                    __import__("os").environ.get("WB_GAAR_INDEPENDENT_CHALLENGE_ENABLED") == "1"):
                from governance.independent_challenge import run as independent_challenge
                state = events.state(cycle_id)
                if not state.get('challenges'):
                    independent_challenge(cycle_id)
                    continue
            if decision.checkpoint != "NONE":
                # Opportunistically prepare the assessor before the human blind read. The result remains
                # inaccessible through proposal_for_reviewer until a read is recorded.
                if decision.checkpoint == "HUMAN_READ":
                    state = events.state(cycle_id)
                    if not state.get("proposal") and state.get("evidence"):
                        governance_cycle.assess(cycle_id, actor="assessor")
                        continue
                # A weak/admitted challenge may be explained automatically once the reviewer identity is
                # known. Challenge Copilot cannot alter strength/supports or any governance state.
                if decision.checkpoint == "HUMAN_DECISION" and reviewer_actor:
                    state = events.state(cycle_id)
                    rows = [x for x in (state.get("challenges") or []) if isinstance(x, dict) and (x.get("challenges") or [])]
                    if rows and not state.get("latest_challenge_copilot"):
                        try:
                            governance_cycle.challenge_copilot_request(cycle_id, actor=reviewer_actor)
                        except Exception:
                            pass
                        decision = self.inspect(cycle_id)
                return decision
            state = events.state(cycle_id)
            if decision.next_action == "Run assessor":
                governance_cycle.assess(cycle_id, actor="assessor")
                continue
            if decision.next_action == "Compare reviewer and assessor":
                diff = governance_cycle.compare_reads(cycle_id, actor=actor)
                if diff.get("comparable") and diff.get("disagreements"):
                    governance_cycle.challenge(cycle_id, actor="challenger")
                continue
            return decision
        raise RuntimeError("Review Conductor exceeded bounded step budget")

    def control_narrative(self, cycle_id: str) -> Any:
        state = events.state(cycle_id)
        if not state or not state.get("evidence"):
            raise ValueError("evidence must be bound before a control narrative can be grounded")
        control = self._control(state)
        elems = self._req_elements(control, state)
        return control_narrative.run(ControlNarrativeInput(
            control_id=state["control_id"], framework=state.get("framework", ""),
            requirement=str(getattr(control, "req", "")), requirement_context=elems,
            evidence_text=str((state.get("evidence") or {}).get("text") or ""),
        ), control=control, review_id=cycle_id)
