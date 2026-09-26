# GaaR RaaS: build plan to live attestation

Written 26 September 2026, after kit v34 (block 1, "Wire the chain"). For the Claude Code builder in `~/dev/gaar` and for
the owner. Kit numbers are assigned in order as kits ship; this plan names blocks and tasks, never kit numbers.

## What "live attestation" means here

A named person attests a period of **real records**, and the sealed pack behind the attestation holds up:

1. The records were collected under a signed plan and a signed mandate, with receipts, not supplied by hand.
2. Every finding is on the closure desk and ends closed by an independent rerun, or under a signed risk acceptance.
3. The false-assurance rate is measured on 500 planted cases made from real records, and published as a 95% upper bound.
4. Precision on real detections is labelled by an **independent** reviewer, reported apart from the false-assurance rate.
5. Every sign-off is bound to a personal key, not a typed name.
6. The pack verifies offline with the tenant's key, and a mistake can be corrected by a superseding pack.

The first live attestation is on the one real data source available now: the python-poetry change history from the
real-records pilot (1 March to 1 September 2026). A bank's records come after that (block 5).

## The success story, in one line

"Over six months of a real project's change history, GaaR tested every change against four controls, closed or accepted
every finding, measured its own miss rate on 500 planted defects, and an independent reviewer confirmed the results.
The pack verifies with one public key."

## Milestones

| Block | Name | Exit test (all must pass) | Target |
|---|---|---|---|
| 0 | Task 0 (builder's first task) | As in the builder's brief; shipped alone | 27 Sep |
| 2 | Prove on real records | Pilot collected and complete against the git baseline; 500 planted cases from real records; M1 run on a real MAS publication | 4 Oct |
| 3 | Make it trustworthy | F5, F6, F7, F12, F13 fixed; trace clean; the pack of a constructed period supersedes cleanly | 11 Oct |
| 4 | Live attestation | Dry run on the pilot period, then the real attestation by the owner, with the independent reviewer's review recorded | 18 Oct |
| 5 | Make it buyable | Bank-hosted install, order form and warranty terms drafted, workpaper export | after block 4 |

Every block ends the same way: full suite and refusal trace pass, one kit is built, rehearsed away from live state,
passes `release_check`, and the owner's Mac round ends ALL GATES AS EXPECTED.

## Block 2: Prove on real records

| ID | Task | Done when (a test checks it) |
|---|---|---|
| B2-1 | Owner runs the pilot: `plan`, `approve`, `collect` (python-poetry) | `status` says COMPLETE; evaluation does not refuse; git baseline has no commit missing from the collection |
| B2-2 | Planted cases from real records: mutate real pilot pull-request records into violations of RC1–RC4 (drop the approval, approve after merge, self-approve, merge with failing checks), 500 per period, seeded by the tenant key | `verifier` runs on them; each mutation's rule is recorded; no planted case is ever shown to the agent with its label |
| B2-3 | M1 on a real MAS publication: owner saves one real MAS publication; `propose-from-watch`; owner decides each item | A signed control set with every quote re-verified against the saved text; spot-check result recorded |
| B2-4 | Pilot evaluation into the chain: real RC1–RC4 findings open closure exceptions (same hook as the series) | Every real finding is on the desk once; rerunning opens nothing |
| B2-5 | Sample and labelling packet for the reviewer (already built: `sample`, `packet`) | Packet generated; rubric reviewed |

## Block 3: Make it trustworthy (the high failures)

| ID | Fixes | Task | Done when |
|---|---|---|---|
| B3-1 | F5 | Scope proposals to an order: framework and effective period in the order file | An unrelated undecided proposal leaves another order's period complete |
| B3-2 | F7 | Rerun tests for change_segregation:1 and change_population:1 | Self-approval and population findings can close by rerun |
| B3-3 | F12 | Personal signing keys for every sign-off role (decide, retest, accept risk, issue, claim, assess, attest); separation of duties compares key fingerprints | Two spellings of one person are refused as the same key |
| B3-4 | F6 | A corrected export counts for a rerun only when it was re-collected under the signed plan or mandate (receipt required) | A hand-supplied export is refused for a PASS |
| B3-5 | F13 | Superseding pack: names the pack it replaces and why; both stay verifiable | The API and CLI show the chain of packs |
| B3-6 | F2, F10, F11 | Record the source page hash where fetchable; state the correlation limit on every pack; key stays outside the agent's working folder, rotation logged | Each has a test |

## Block 4: Live attestation

| ID | Task | Done when |
|---|---|---|
| B4-1 | Order for the pilot period: `ORD-PILOT` over the collected python-poetry history, controls RC1–RC4 | `gaar_raas.py period ORD-PILOT` seals a pack |
| B4-2 | Dry run: the whole period on a copy of the state, with the checklist below | Every checklist line passes |
| B4-3 | Independent reviewer: labels the sample, reviews the rubric, writes the adversarial pack | Precision figure labelled "independent"; reviewer's findings recorded |
| B4-4 | Live: the owner attests the period with a personal key | Sealed pack, passport verifies with the tenant key, attestation recorded |
| B4-5 | The success-story page: one page with the figures, the pack id, and how to verify it | Published; every number traces to the pack |

Dry-run checklist: collection complete; every exception closed or accepted; 500 planted cases, bound reported;
precision labelled by the reviewer; every sign-off key-bound; pack verifies; a deliberate one-byte change fails.

## Rules that keep the builder on track

1. **One task, one commit, one test.** A task is done when a test expects its behaviour, including every refusal
   message word for word. New refusals are reached by tests (the trace must stay at 0 unreached).
2. **Never on live state.** Tests use the conftest isolation; no command in a session runs against `~/gaar-*`,
   `~/gaar-recurring-demo` or the install in `~/gaar-test`. Rehearsals use a throwaway HOME and
   `tools/rehearsal_series.py`, or the kit zip goes to the cloud session for rehearsal.
3. **The zip that ships is the zip rehearsed.** Build once per block; any change after the rehearsal means a new build.
4. **Stop at people.** When the next step needs the owner or the reviewer, write it in `docs/raas/HUMAN_STEPS.md` and
   move to the next task that does not.
5. **No hosted model sees real records.** Real evidence goes to deterministic rules or local models only.
6. **Say what was measured.** Every figure states its sample, its provenance (self or independent), and what it
   does not cover.

## What only the owner can do (critical path)

| When | Step |
|---|---|
| Now | Run the kit v35 round on the Mac |
| Now | Name the independent reviewer and book about four hours of their time for block 4 |
| Now | Subscribe to MAS alerts; mark the FCA alerts as not spam |
| Block 2 | Keychain token for GitHub; run `plan`, `approve`, `collect`; save one real MAS publication and decide its items |
| Block 3 | Create a personal signing key; set the monitored-only price |
| Block 4 | Attest the pilot period |

The reviewer is the one dependency that cannot be built. Without them, block 4 can finish only as "self-labelled",
which is not a live attestation.
