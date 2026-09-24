# GaaR RC1 Demo Runbook

## Story in one sentence
A regulatory change is detected, only affected governance results are reopened, the AI Auditor performs bounded audit work, deeper reasoning is used only when policy warrants it, a human resolves material judgment, the Quality Gate decides whether the package is publishable, and a new immutable Living Governance Result replaces the old one with full lineage.

## Demo sequence
1. Open **Living Results** and show an existing `CURRENT` result and Governance Passport.
2. Open **Watcher** and show an authoritative source, healthy cursor, and no background-source authority leak.
3. Inject/receive a regulatory change; show Watcher emission and Autopilot job.
4. Open **Autopilot**; show `CURRENT -> REVIEW_REQUIRED -> REASSESSING` and processing timeline.
5. Open **AI Auditor**; show Evidence Examiner, Assessor, Challenge, Control Narrative and bounded Copilots.
6. Show Colibri escalation reason codes only if ambiguity/contradiction/materiality policy requires it.
7. At the human checkpoint, record the human decision.
8. Show Quality Gate `FINALIZABLE` (or demonstrate a `BLOCKED` package once).
9. Return to **Living Results**: R1 is `SUPERSEDED`, R2 is `CURRENT`.
10. Download the **Governance Passport** and verify the signature/digest via the RaaS API.

## Commercial closing line
**Governance that breathes with change — continuously maintained, human-governed, and independently provable.**
