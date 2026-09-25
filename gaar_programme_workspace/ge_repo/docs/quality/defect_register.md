# Defect and limit register

One index of the numbered defects and every known limit of a check, with where its full record lives. A defect is
something that was wrong and is fixed, or is being fixed. A limit is something a check cannot see by design, recorded
so that it is measured and not forgotten.

## Defects

| ID | Found | What was wrong | Status | Record |
|---|---|---|---|---|
| D11, D13, D14 | earlier kits | Model scoring and collection completeness rules (see the policy) | Fixed; now rules in the policy | docs/quality/quality_policy.md |
| D15 | kit v10 | A test named for uniqueness of authorisation ids did not exercise the guard it named | Fixed | docs/quality/unexercised_guards.md |
| D16 | policy 1.3 | A hash-pinned policy carried a status column that events change, so its approval falsified its own cell | Fixed: gate status is a generated report | docs/quality/quality_policy.md |
| D17 | kit v15 | A guard proposed as defensively unreachable was reachable | Fixed | docs/quality/unexercised_guards.md |
| D18 | kit v19, on the Mac | A software upgrade made an earlier week unattestable while the milestone tool asked for its signature; runbook U1's rerun was prescribed but nothing performed it | Fixed: the scheduler reruns under the new version (v20) | docs/design/inbox_and_scheduler.md |
| D19 | kit v21 | Kits shipped runtime ledgers; unzipping over an install overwrote them. Root cause: state resolved relative to the working directory | Fixed: kits exclude runtime state (tools/build_kit.py); all state resolves through governance/paths.py; a test fails on any new working-directory-relative state path | docs/design/workbench_watch_impact.md, docs/design/twin_and_arena.md |
| D20 | kit v22 | **No control cites the instrument it derives from.** All 195 contracts state their requirement in the project's own words, with no passage of the source instrument behind it. A governance-basis provenance gap, older than v22 | Open. The response is the requirement-basis mapper (governance/basis.py): a proposed verbatim passage per control, confirmed one control at a time by a named person, pilot controls first. ISO/IEC 42001's 38 controls are blocked until the standard is obtained | docs/design/twin_and_arena.md, "Requirement basis" |
| D21 | kit v22 | The test bootstrap restored the shipped ledgers at the end of a test session. On an installed copy those ledgers are live, so anything the app or scheduler wrote during a test run was erased by the restore | Fixed: ledgers are redirected to a temporary folder before any module reads its path (conftest.py); the end-of-session restore remains as a backstop | conftest.py |
| D22 | v22 round, on the Mac | The first twin adjudications were confirmed as "Your Name": a template placeholder was accepted as a person | Fixed (v23): governance/names.py refuses placeholders for adjudications, basis decisions and arena votes; placeholder records made before the fix stay in the chain and are never counted | governance/names.py |
| D23 | v22 round, on the Mac | A test of the synthetic pack passed vacuously when the pack was missing: it looped over zero files | Fixed (v23): the test asserts the pack is present | tests/test_wb138_synthetic_m36.py |
| D24 | v22 round, on the Mac | With the Ollama server down, an arena run asked each of five models all 100 cases, 500 failed calls | Fixed (v23): a contestant is stopped after 5 consecutive failed calls (config/arena.yaml), with the stop on record | governance/arena/arena.py |
| D25 | v24 round, on the Mac | Run in the wrong Python environment, the suite reported 11 failures, 16 errors and 8 files that could not load; the one real cause, missing packages, scrolled out of the milestone's view | Fixed (v25): the runner stops before any test with ENVIRONMENT NOT READY, names the missing packages and says to activate the project environment | tools/run_all_tests.py |
| D26 | v24 round, on the Mac | The mail setting accepted a password typed where the environment variable's name belongs | Fixed (v25): `password_env` must look like a variable name; anything else is refused without echoing it | governance/watcher/mailbox.py |
| D27 | v29 round, on the Mac | Root cause: a reader assumed every run record has pass counts. The gate report crashed on the record the test runner writes when it stops for ENVIRONMENT NOT READY (it has no pass counts), so the scheduler's gate-status job failed on every tick, and two scheduler tests failed because they read the machine's own run history | Fixed (v30): the report reads that record as an open gate with its cause; tests no longer read this machine's run records or packs (tests/conftest.py) | governance/production/gate_status.py |
| D28 | v28 round, on the Mac | The doctor reported "requirements met" in conda base while the test runner, checking requirements-dev.txt (which adds pytest and coverage), stopped with ENVIRONMENT NOT READY. Root cause: two readiness checks read different requirement files. That stop wrote the record behind D27, and the scheduler's gate-status job then failed on every tick with no report until a round broke on it | Fixed (v31): the doctor reads the runner's file; scheduler outages are windows with a start and a recovery, printed first by the doctor and in every milestone summary; the doctor names the Python the unattended scheduler runs | governance/doctor.py, governance/production/scheduler.py |

## Limits of the checks

| ID | Check | What it cannot see | How it is measured | Consequence for real data |
|---|---|---|---|---|
| L1 | change authorisation (privilege) | Two different people who share a name. Identity is resolved by actor name, so a person with no grant passes on a namesake's grant | The twin plants IDENTITY_COLLISION on purpose; it is scored apart from the headline. 1,000-week bench: planted 218, detected 0 | A real-data collector must supply unique actor IDs (employee number or directory ID) on changes and grants, or this limit comes with the data. Recorded in the collector requirement below |

## Collector requirement arising from L1

Real change and privilege exports must carry a unique, stable actor identifier (not a display name) on every change
record and every privilege grant. If an export offers names only, record that on the collection, and read any clean
privilege result for that period as not covering namesakes.
