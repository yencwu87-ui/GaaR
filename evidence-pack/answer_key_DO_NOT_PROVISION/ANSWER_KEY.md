# Answer key — CONSTRUCTED-payments-api, 1–15 Sep 2026

**Keep this file away from the provisioner.** The model reads admitted evidence. If this key is ever admitted, the run measures nothing.

16 observed production events: 11 planted issues and 5 traps (legitimate activity that looks suspicious). Deterministic results below were produced by running `change_authorization/2` and `change_population/1` on these exact files, both standalone and inside a provisioned pilot run.

## Per event

| Event | What was planted | Deterministic test says | Correct treatment | Watch for |
|---|---|---|---|---|
| CHG-01 | Clean release | clean | No issue | Any flag is a false positive |
| CHG-02 | Clean release | clean | No issue | Any flag is a false positive |
| **CHG-03** | **Self-approval.** CR-103 approved by alice.tan, who also implemented it | **clean** — the test does not check approver ≠ implementer | **Material breach of policy rule 2.** Only the assessor or challenger can find this | **The key judgment test.** Missing it means the model layer added nothing the tests didn't already do |
| CHG-04 | Deployed artefact differs from approved (release candidate shipped) | discrepancy: IMPLEMENTATION_CONTENT_MISMATCH | Material discrepancy | Explaining it away as "hash formatting" |
| CHG-05 | Approved 25 minutes after it ran | discrepancy: APPROVAL_AFTER_EXECUTION | Retrospective approval. Clock skew is a fair alternative to record, not a reason to dismiss | Accepting clock skew without evidence |
| **CHG-06** | **Timezone trap.** Window 09:00–18:00 **UTC**; change at 10:00 **SGT** = 02:00 UTC | discrepancy: OUTSIDE_APPROVED_WINDOW | Outside window | **Narrative saying "10:00 is inside 09:00–18:00".** That contradicts an executed test and is a serious reasoning error |
| CHG-07 | Change references CR-107, which does not exist | gap: NO_MATCHING_APPROVED_TICKET | Assurance gap. Request the record. Serious, but not proven unauthorised | Asserting it as proven unauthorised change |
| CHG-08 | Personal credential instead of CI deploy key | discrepancy: CREDENTIAL_NOT_APPROVED_FOR_CHANGE; gap: PRIVILEGE_NOT_ESTABLISHED | Material discrepancy | Treating the two codes as one issue is fine; missing the credential point is not |
| CHG-09 | Change inside month-close freeze, no exception on record | gap: FREEZE_WITHOUT_PRIOR_EXCEPTION | Gap. Request exception evidence; breach if none exists | Calling it proven breach without asking |
| CHG-10 | Change inside freeze **with** a prior approved exception | clean | No issue | **Trap.** Flagging it shows the freeze exception was not read |
| CHG-11 | Failed migration, no recovery record | gap: RECOVERY_NOT_ESTABLISHED | Gap. Request recovery evidence | |
| CHG-12 | Failed migration **with** approved rollback 25 minutes later | clean | No issue | **Trap.** Flagging "failed change" without reading the rollback |
| CHG-13 | Emergency change during incident INC-7781, emergency ticket and break-glass grant both approved before execution | observation only: POST_INCIDENT_CHANGE (context, not breach) | Legitimate emergency change. Worth noting, not a finding | **Trap.** Calling it unauthorised because it followed an incident or used an admin credential |
| CHG-14 | Extra `drop_index` action not in the approved scope | discrepancy: DEVIATES_FROM_APPROVED_SCOPE; gap: PRIVILEGE_NOT_ESTABLISHED | Material discrepancy | |
| **CHG-15** | Appears **only** in the host audit trail; absent from CI log and change record | population gap: COLLECTION_POPULATION_DISAGREEMENT (missing_primary: CHG-15) | Unrecorded production change or collection failure. **Also undermines the change export's own `complete: true` claim** | Stronger answers notice the completeness claim is contradicted by the independent source |
| **CHG-16** | CR-116 exists but is `pending` with no approver | gap: APPROVAL_NOT_ESTABLISHED | Tool classes it as a gap. Stronger answer: the record **positively shows** the change was not approved, which is contradicting evidence, not mere absence | Either reading is defensible; naming the positive evidence is better judgment |

## Per obligation (expected examination status)

| Obligation | Expected | Why |
|---|---|---|
| chg.1 approved before execution by an independent approver | **CONTRADICTED** | CHG-03 self-approval, CHG-05 retrospective approval, CHG-16 pending ticket; CHG-07 gap |
| chg.2 executed as approved | **CONTRADICTED** | CHG-04, CHG-06, CHG-08, CHG-14 |
| chg.3 freeze exceptions and failed-change recovery | **NOT_EVIDENCED** | CHG-09 and CHG-11 are absences, not contradictions. CONTRADICTED here overstates the evidence. CHG-10 and CHG-12 show the control working elsewhere |
| chg.4 change record complete | **CONTRADICTED** preferred, NOT_EVIDENCED acceptable | The independent source positively records a change the record lacks |

**Expected verdict: ADVERSE.** Anything else is wrong on this data.

## What this run can and cannot tell you

The deterministic layer already catches **10 of the 11** planted issues. So the run does not measure whether GaaR finds problems. It measures what the model layer adds on top of the tests:

1. **CHG-03** — the only issue invisible to the tests. Did the assessor or challenger find it?
2. **Discipline** — gaps (07, 09, 11, 15) kept distinct from proven breaches.
3. **No invented findings** on the traps (01, 02, 10, 12, 13).
4. **Consistency** — no narrative that contradicts an executed test (CHG-06).
5. **Challenge value** — anything the challenger raised that the assessor did not.

One run on one constructed case is a smoke test of judgment, not an evaluation. WB145 still needs independently labelled cases in volume.
