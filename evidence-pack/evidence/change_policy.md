# Production change management standard (CONSTRUCTED TEST POLICY)

Version v1. Applies to production systems in scope for this assessment.

1. Every change to a production system is recorded against a change request before it is executed.
2. A change request is approved before execution by an authorised approver who is not the person who implements it.
3. A change is executed only within its approved implementation window, against its approved targets, using only its approved actions, implementer and credentials.
4. The artefact deployed is the version that was approved.
5. Implementers act only under a privilege grant that is approved in advance and valid at the time of the change.
6. No change is made to a system inside a declared freeze unless an exception for that change was approved before it ran.
7. A failed change is recovered by an approved rollback or approved fix-forward, and the recovery is recorded.
8. Emergency changes follow the same rules, with approval obtained before execution through the emergency route.
9. The record of changes is complete: every production change observed on the system appears in the change record.
