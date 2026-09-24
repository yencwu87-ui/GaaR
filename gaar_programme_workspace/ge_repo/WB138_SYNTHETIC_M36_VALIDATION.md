# WB-138 Synthetic M3.6 validation

## Outcome

The regenerated synthetic pack reached `READY_FOR_HUMAN_REVIEW` and intentionally stopped before
evidence admission. It demonstrates the governed acquisition and dossier preparation stages; it
does not establish production readiness or MAS compliance.

| Check | Result |
|---|---|
| Frozen prior use cases preserved | PASS — cases d, e, f and g |
| Evidence classification | `SYNTHETIC_DEMO_ONLY` |
| Exact-control candidates | 5/5 |
| Governed elements visible | 14/14 |
| Preflight status | `EVALUATED` |
| Deterministic triage score | 0.964 |
| Open acquisition gaps | 0 |
| Dossier anchors | 5 |
| Open dossier gaps | 0 |
| Binding status | `PROPOSED_ONLY` |
| Next checkpoint | Named human admission |

Snapshot artifacts:

- Acquisition ID: `EA-2fab6879e70349f0a685cbd4ba1b7389`
- Dossier ID: `ED-8784760fc91f5d709b53be199a7cb246`
- Requirement version: `SYNTHETIC-M3.6-DEMO-v1`

## Cases reused

1. Retail credit decisioning validation — strong independent validation with open findings.
2. Contact-centre generative assistant — delivery-led pilot with material coverage and independence gaps.
3. AML alert prioritisation change — material-change validation with mixed strengths and limitations.
4. High-impact customer eligibility — conduct-focused assessment with fairness and scope evidence.

A fifth synthetic lifecycle-policy artifact supplies the re-validation triggers that properly sit
outside an individual validation report.

## Gate behaviour observed

The first run stopped because e14 was not visible within the bounded discovery excerpt. The policy
abstract was corrected to expose the re-validation scope without weakening the gate. A second run
then exposed inconsistent stop-word handling between Scout and dossier assembly; the two stages now
use the same significant-term vocabulary. The final run passed with no gaps.

## Human boundary

No admission, assessment conclusion, human decision, signed CURRENT result, or replay PASS was
fabricated. Double-click `Run_Synthetic_M36.command` to regenerate the proposed dossier. A named
human must still admit the evidence before the rest of the experimental golden path can run.

