# WB107 — Governance Change Intelligence

This workstream introduces a first-class `GovernanceChange` and `ImpactAssessment` without allowing a
source upload, semantic match, or model output to mutate governance state directly.

## Flow

`Source metadata → authority assessment → requirement diff → GovernanceChange → ImpactAssessment → REVIEW_REQUIRED event`

The only automatic state opening supported here is `CURRENT → REVIEW_REQUIRED`, represented by a system
state event carrying `trigger_id=<GovernanceChange.change_id>`. It intentionally has no human `decision_id`.
Human approval remains required for finalisation and supersession.

## Authority rules

The registry's `normative_status` establishes the source class. Additional metadata is mandatory:
issuer, jurisdiction, legal basis, enforcement status, and applicability. The module does not infer legal
force from wording such as `shall`, nor does semantic similarity establish authority.

- `BINDING` + effective + applicable → may support canonical requiredness and governance-impact review.
- `SUPERVISORY_EXPECTATION` + effective + applicable → may trigger governance-impact review, but does not
  become a binding requirement through this module.
- `GUIDANCE`, `CONSULTATION`, `INDUSTRY_CONTEXT`, `BACKGROUND` → awareness/context only here.

## Impact rules

`ImpactAssessment` maps changed controls to existing `GovernanceResult` artifacts using the current
requirement-version index. The output is only `NO_MATERIAL_IMPACT` or `REVIEW_REQUIRED`.

It never creates `FAIL`, `CONDITIONAL_PASS`, or a final governance conclusion.

Materiality is policy input (`LOW`, `MEDIUM`, `HIGH`, etc.), not an LLM confidence score and not a
hard-coded universal threshold.
