# Unexercised guards register

A refusal no test reaches is untested, however green the suite looks. `tools/trace_unreached_guards.py` fails
if any refusal line in the pilot's modules is unreached and not listed here with a reason.

History: the first trace (kit v14) found 36 unreached refusal lines. One belonged to a test that passed anyway
(defect D15): `test_authorisation_ids_are_unique_per_signing_and_cannot_be_edited`, shipped in kit v10. It
accepted any ValueError; editing the signed authorisation broke its signature, so the signature check refused
first and the guard it is named for ("does not match the inputs it was derived from") was never reached. It now
re-signs the edited document and expects that exact refusal. 22 are now reached by
tests that expect the exact refusal (tests/test_guards_exercised.py). The rest are listed below.

## Remaining — base-package core, predating the pilot programme

These guard the original investigation core: service-key trust, the source registry, the static file
collector and production sealing. The pilot's own configurations do not reach them.

Registered is a tracking state, not a validation state. Each guard carries a disposition:

- **Test required**: an integrity-class refusal reachable through a configuration no test constructs yet.
  It counts as validated only once a test triggers it and expects its exact message.
- **Proposed — pending external review**: a claim that the guard cannot fire unless an earlier guard is
  bypassed. It is tracked, not validated. It becomes "justified defensive-unreachable" only when a reviewer
  outside the project (neither the code's owner nor the proposer) records agreement with the reason.

| Module | Refusal | Reached through | Disposition |
|---|---|---|---|
| runtime.py | 'untrusted signing identity for ' | a signer whose key is not trusted for its role | Test required |
| runtime.py | 'independent challenger key required' | challenger configured with the assessor's key | Test required |
| runtime.py | 'registry source identity mismatch' | a source registered under a different id | Test required |
| runtime.py | 'evaluation fixture source is forbidden outside evaluation mode' | fixture source in production mode | Test required |
| runtime.py | 'evaluation fixture source hash mismatch' | a changed fixture snapshot | Test required |
| runtime.py | 'collector path outside approved root' | a static collector path escaping its root | Test required |
| runtime.py | 'evidence export exceeds collector budget' (static collector) | a static export over 20 MB | Test required |
| runtime.py | 'duplicate collected evidence identity' | two collectors emitting the same evidence id | Test required |
| runtime.py | 'production entry point rejects synthetic investigations' | a synthetic investigation run in production mode | Test required |
| lifecycle.py | 'signed result-state anchor is missing or altered' | a result event pinned to a state that is not there | Test required |
| lifecycle.py | 'inconclusive requires explicit assurance-only FAIL mapping; no operational breach inferred' | sealing an INCONCLUSIVE record without that mapping | Test required |
| lifecycle.py | 'sealed result belongs to a different investigation head' | only if the append-only, signed, trigger-protected store is altered after sealing; the store's chain verification refuses first | Proposed — pending external review (proposer: Claude, kit v15; no reviewer yet) |

Summary: 11 test required, 1 proposed — pending external review. None of the 12 counts as validated today.
