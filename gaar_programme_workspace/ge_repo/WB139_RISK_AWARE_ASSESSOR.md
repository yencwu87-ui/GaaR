# WB139: broader risk investigation

This checkpoint extends WB138. It implements a bounded risk-investigation pass alongside the existing element assessment, and a deterministic asset-export reconciliation tool. It does not certify stronger-model reasoning quality or complete the M3.6 production golden path.

## User-facing behavior

The normal assessor now runs a separate broader-risk review by default. Its hypotheses are displayed after the existing independent-reading gate under **What else could go wrong?** Each includes a supporting evidence quote, possible consequence, related control topic, alternative explanation, proposed test and reason to investigate.

The pass uses the configured inference provider and existing bounded escalation route. It does not force a larger model or set a vendor-specific reasoning-effort option. The local model's ability to produce good hypotheses still needs a live benchmark. The existing role/model policy determines routing. An additional pass adds inference latency; schema/grounding failures are visible as UNAVAILABLE rather than an empty successful review. Set `WB_ASSESSOR_RISK_REVIEW=0` to disable this extra pass.

Proposals remain separate from canonical element verdicts. A wider risk hypothesis cannot invent a regulatory requirement or silently change a control score. A material wider finding may warrant escalation, but automatic gate integration is not implemented in this increment. The AI pass is not independent challenge and does not execute its suggested tests.

The element prompt now explicitly requires substantive support, compatible system/version/period, consideration of contradictions, and a distinction between design and operating obligations. Prompt wording alone is not proof of semantic reliability; live model evaluation remains necessary.

## Asset example: a real computation on synthetic exports

From `ge_repo`:

```bash
python tools/asset_risk_review.py eval/wb139/asset_exports.json --output eval/wb139/asset_result.json
```

The single-system fixture has three inventory IDs and three discovery IDs. Despite matching counts, discovered asset `c` is absent from the inventory, configuration and vulnerability exports. Inventory also contains `retired`, which was not discovered. The result preserves these differences, the denominator, input hash and source IDs. It does not declare `c` unpatched or `retired` improperly managed.

Before making that stronger claim, validate export coverage, stable identities, scope and time; investigate retired/ephemeral assets, collector failures and approved exceptions; then inspect actual configuration and patch findings. Read-only record reconciliation is implemented. Live infrastructure scans, automatic evidence acquisition and autonomous remediation are not.

## Corrections to the proposed specification

1. Agreement can be evidenced by an authorized workflow or decision record; a signature is not automatically required.
2. Not every element requires operating evidence. Design obligations can be supported by policy; operating obligations require evidence of operation. Preserve both.
3. The proposed three-way enum mixes source authority with evidence purpose. Prefer separate axes: authority (`binding`, `guidance`, `consultation`, `internal`, `unverified`), purpose (`requirement`, `design`, `execution`, `outcome`), authenticity/provenance, and scope. Classifications must themselves be evidenced; a document label proves nothing.
4. Admit relevant policy evidence as design evidence; prevent it from satisfying an operating obligation. Do not discard all policy material at admission.
5. In the inspected consultation snapshot, predeployment independent review is §4.18; high-risk formal validation is §4.19. §4.14(b) concerns testing approaches. The example YAML's e6 citation and `binding` label should not be adopted.
6. Adopting a draft as an internal standard does not change its external legal authority. A sealed result may attest to a limited internal-standard assessment if the engine's approved policy allows it, but must not claim binding-regulatory compliance on that basis. Sealing proves integrity, not legal correctness.
7. Acquisition and admission need authentic, scoped evidence; they need not require an already-passing 14/14 result. An admitted dossier can legitimately support an adverse or incomplete assessment. Otherwise failed controls disappear before assessment.
8. Keep synthetic cases individually scoped. A suite may contain multiple systems if each has its own dossier and outcome. There is no need to erase useful negative cases to manufacture one all-green corpus.

These corrections describe the proposed next contract. The typed admission redesign and canonical M3.6 wording changes have not been implemented here. Existing human element-disposition decisions remain untouched.

## Remaining implementation sequence

1. Approve source-grounded candidate element changes, including §4.14(c) placement, preserving draft authority and proportional applicability.
2. Implement independent authority/purpose/scope/provenance fields, with end-to-end evidence bindings and purpose-aware verdict guards.
3. Supply scoped linked exports automatically to approved read-only tests. Test outputs should be immutable artifacts fed back to assessment and independent challenge.
4. Govern promotion of a corroborated wider risk into an assurance finding and release escalation, while keeping it distinct from a breach of the assessed control.
5. Regenerate individually coherent M3.6 cases: positive, negative, contradictory, incomplete and not-applicable variants. Do not reuse training fixtures as independent validation ground truth.
6. Benchmark the configured model and escalation behavior with held-out examples; execute the full admission-to-result chain under the applicable human decision policy.

## Verification scope

Focused tests cover unequal IDs despite equal counts, duplicate handling, missing snapshots, mismatched times, empty populations, quote grounding, schema rejection, model failures, disabled mode and separation from the control verdict. Integration model responses are mocked. No live LLM quality claim, full regression-clean claim, browser UI verification, regulatory-currentness verification or sealed GovernanceResult is made.

The initial broader test attempt encountered an existing external knowledge lookup; automatic approval review blocked its unknown outbound payload. The focused suite was rerun with `WB_WEB_KNOWLEDGE=off`. That offline setting is for the test command and does not change the application's saved configuration.

## Changed files

- `assessor.py`: separate risk pass and stronger element-prompt semantics.
- `governance/risk_review.py`: bounded hypothesis schema and read-only asset reconciliation.
- `app.py`: plain-language risk panel behind the existing blind-read boundary.
- `tools/asset_risk_review.py`: executable export comparison.
- `tests/test_wb139_risk_review.py`, `tests/test_wb139_risk_integration.py`: new focused checks.
- `tests/test_element_pass_wb033.py`: isolate existing call-count tests from the optional extra pass.
- `eval/wb139/asset_exports.json`, `eval/wb139/asset_result.json`: labeled synthetic input and computed result.

Older WB138 demonstrations remain historical artifacts. Their pooled keyword-coverage results must not be interpreted as one system meeting M3.6.
