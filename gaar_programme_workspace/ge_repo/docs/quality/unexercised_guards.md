# Unexercised guards register

A refusal no test reaches is untested, however green the suite looks. `tools/trace_unreached_guards.py` fails
if any refusal line in the pilot's modules is unreached and not listed here with a reason.

**Scope of the trace.** The tracer covers the eleven modules named in `tools/trace_unreached_guards.py` (kit v20 added
the scheduler and the inbox). The
command-line tools under `tools/` are exercised by tests through separate processes, which the in-process
tracer cannot see; their refusals are not covered by this register's count.

History: the first trace (kit v14) found 36 unreached refusal lines. One belonged to a test that passed anyway
(defect D15): `test_authorisation_ids_are_unique_per_signing_and_cannot_be_edited`, shipped in kit v10. It
accepted any ValueError; editing the signed authorisation broke its signature, so the signature check refused
first and the guard it is named for ("does not match the inputs it was derived from") was never reached. It now
re-signs the edited document and expects that exact refusal. 22 were then reached by tests that expect the
exact refusal (tests/test_guards_exercised.py), leaving 12 registered: 11 "Test required" and 1 "Proposed —
pending external review".

Kit v19 reached all 12 (tests/test_core_guards_exercised.py). Each test expects the whole refusal message,
anchored, and each was checked by disabling its guard and confirming that the test then fails.

**Defect D17: a proposed disposition was wrong.** The one guard proposed in kit v15 as defensive-unreachable
("sealed result belongs to a different investigation head: only if the append-only, signed, trigger-protected
store is altered after sealing") is reachable without any tampering. A holder of the trusted `result_sealer`
key can append a second, validly signed `result_sealed` event carrying the same human approval but a result
bound to another head. The guard is what refuses it. This is the case §10's external-review rule exists for:
the proposer (Claude) was wrong, and a test, not a reviewer, settled it. The proposal is withdrawn.

## Reached in kit v19

- runtime.py: 'untrusted signing identity for ' (role not trusted; trusted public key differs)
- runtime.py: 'independent challenger key required'
- runtime.py: 'registry source identity mismatch'
- runtime.py: 'evaluation fixture source is forbidden outside evaluation mode' (production mode; non-internal authority)
- runtime.py: 'evaluation fixture source hash mismatch'
- runtime.py: 'collector path outside approved root'
- runtime.py: 'evidence export exceeds collector budget' (static collector)
- runtime.py: 'duplicate collected evidence identity'
- runtime.py: 'production entry point rejects synthetic investigations'
- lifecycle.py: 'signed result-state anchor is missing or altered' (missing pin; pin to another result's state)
- lifecycle.py: 'inconclusive requires explicit assurance-only FAIL mapping; no operational breach inferred'
- lifecycle.py: 'sealed result belongs to a different investigation head' (D17)

## Remaining

None. Any new unreached refusal line must be listed here in a table row with its disposition, or the trace
fails:

- **Test required**: an integrity-class refusal reachable through a configuration no test constructs yet.
  It counts as validated only once a test triggers it and expects its exact message.
- **Proposed — pending external review**: a claim that the guard cannot fire unless an earlier guard is
  bypassed. It is tracked, not validated. It becomes "justified defensive-unreachable" only when a reviewer
  outside the project (neither the code's owner nor the proposer) records agreement with the reason.

| Module | Refusal | Reached through | Disposition |
|---|---|---|---|

Summary: 0 registered; all 12 previously registered guards are reached by exact-message tests (kit v19). Trace scope: eleven modules; command-line tools not traced.
