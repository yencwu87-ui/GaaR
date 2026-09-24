# Coverage reporting — design note

Status: decided and implemented in kit v12. Owner of the semantics: governance (the mapping signer).

## Why

Before this change, D8 recorded findings only. A quiet obligation could mean three different
things, and the record could not tell them apart:

1. the checks ran over every relevant record and found nothing;
2. nothing the checks apply to happened this period (no freeze, no failed change);
3. the checks did not effectively cover the obligation (a collector broke, a procedure could not run).

Phase 0 already lost information this way: in constructed week 2 the population check positively
confirmed that both change records list the same six changes, and the record reported it exactly
like silence.

## The four outcomes an obligation can have

| What happened | Recorded status | Basis | Reviewer reads | Permits |
|---|---|---|---|---|
| A mapped check found a violation | CONTRADICTED | DETERMINISTIC_DISCREPANCY | a test found a record that contradicts it | blocks, as before |
| A mapped check found a missing record | NOT_EVIDENCED | DETERMINISTIC_ASSURANCE_GAP | a record needed to decide is missing | blocks, as before |
| A mapped check could not run | NOT_EVIDENCED | PROCEDURE_DID_NOT_RUN | the check behind this obligation did not run | never silence |
| The population is empty | NOT_EVIDENCED | EMPTY_POPULATION | checked 0 of 0: usually a broken collector | never clean |
| Checks ran, corroborated, N > 0 applicable, 0 violations | NO_EXCEPTIONS_FOR_PERIOD | COVERAGE_CORROBORATED | checked N, none violated: clean for this period | may read clean *for the period* |
| Checks ran, corroborated, 0 applicable events | NO_EXCEPTIONS_FOR_PERIOD | NO_APPLICABLE_EVENTS | nothing to breach this period | may read clean *for the period* |
| Checks ran but population not corroborated | unchanged (not positively shown) | COVERAGE_UNCORROBORATED | checked N, none violated — a claim, not evidence | never clean |

NO_EXCEPTIONS_FOR_PERIOD is deliberately not called SUPPORTED. It says what the tests saw in this
period's records. It is not a conclusion that the control is designed or operating effectively.

## Coverage statements

A new procedure, `change_coverage` version 1, states for each finding code how many records the
check actually applied to, using the same applicability conditions as `change_authorization`:

| Codes | Applies to |
|---|---|
| NO_MATCHING_APPROVED_TICKET, PRIVILEGE_NOT_ESTABLISHED | every observed change |
| APPROVAL_NOT_ESTABLISHED, OUTSIDE_APPROVED_WINDOW, DEVIATES_FROM_APPROVED_SCOPE, IMPLEMENTER_NOT_APPROVED, CREDENTIAL_NOT_APPROVED_FOR_CHANGE | changes whose ticket exists |
| APPROVAL_AFTER_EXECUTION | changes whose ticket carries an established approval |
| SELF_APPROVAL | changes whose ticket names an approver |
| IMPLEMENTATION_CONTENT_MISMATCH | changes whose ticket carries an approved specification hash |
| FREEZE_WITHOUT_PRIOR_EXCEPTION | changes inside a declared freeze on their own system |
| RECOVERY_NOT_ESTABLISHED | failed changes, when policy requires recovery |
| COLLECTION_POPULATION_DISAGREEMENT | the union of the primary and independent change lists |

It is a separate, separately versioned procedure. `change_authorization` version 2 is unchanged, so
earlier signed results still replay exactly.

If the change export is not declared complete, the coverage procedure reports NOT_COMPARABLE and no
obligation can be read as clean.

## The corroboration rule

A coverage statement is the procedure vouching for its own thoroughness. It counts as evidence only
when all of these hold, otherwise it is shown as a claim:

1. the population check ran on this period's population export;
2. both the primary and the independent record are declared complete;
3. the two records list exactly the same changes;
4. the change export assessed lists exactly those changes too.

## What coverage never does

- It never enables PASS. The deterministic verdict becomes NO_EXCEPTIONS_FOUND only when every
  obligation is NO_EXCEPTIONS_FOR_PERIOD. The decision available is still assurance-only.
- It never proves the tests are complete. That is the job of adversarial test packs written by
  someone other than the test author, and of every pilot defect turned into a regression case.
- It never bypasses D8. It is an input to the same reconciliation, recorded in the same signed event.
- It never upgrades a model's CONTRADICTED or NOT_EVIDENCED. Coverage replaces silence only where
  the model was not asked, or where it said SUPPORTED and the tests agree.

## Attestation wording

When coverage statements are part of the record, the sentence the reviewer confirms names them:
"I have read the reconciled statuses, the deterministic findings, the coverage statements and the
evidence behind them, and I take accountability for this decision." The exact sentence is stored in
the signed attestation.

## Decided: "no exceptions noted" (kit v13)

The verdict says what the machine found; the decision says what the human notes. Machine finds, human notes.

| Verdict (machine) | Decisions a reviewer may sign (closed set) |
|---|---|
| ADVERSE | FAIL |
| NO_EXCEPTIONS_FOUND | No exceptions noted for this period (assurance only) |
| INCONCLUSIVE | FAIL (assurance only) |

- "No exceptions noted" is offered only when every obligation is NO_EXCEPTIONS_FOR_PERIOD with corroborated
  coverage, and that is checked again at the moment of signing. A mixed record never softens.
- It is never PASS, and it can never be sealed as a governance result. It ships with a test proving that.
  Standing rule: every new decision-vocabulary item ships with its non-promotion test.
- The sentence the reviewer confirms: "I have read the reconciled statuses, the coverage statements and the
  evidence behind them; no findings were raised this period; I take accountability for this decision."
- Prospective only. Signatures given before this change stand as signed.
- ADVERSE deliberately offers FAIL only: assurance-only means "could not conclude", while ADVERSE means a test
  positively found a contradiction.

## Appendix A — decision-model adapter contract (Jev and Laya)

Applies before any decision model enters the record, for either model, since both use the same
system_one request and response shape.

1. Every decision question is a **choice** question with the options SUPPORTED, CONTRADICTED and
   INSUFFICIENT. Yes/no ("noul") questions are not used for decisions, because in the published
   quickstart their answers carry no confidence field.
2. **An answer without a confidence-bearing field is a HOLD.** It goes to a person. A missing field
   never defaults to a pass.
3. Code decides from the returned probabilities against thresholds set in signed configuration.
   Contradiction blocks; low confidence holds; nothing else passes on the model's word alone.
4. Every call is recorded as a signed receipt, like any other model call.
