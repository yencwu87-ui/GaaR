# Inbox and scheduler (kit v20)

**Principle.** A view exists only where a person must decide or read something. Machine work runs in the
background and leaves a signed receipt; its results reach people as inbox items or as a frozen pack.

## The UI invariant

> The UI reads journals and hosts signed human actions. All machine work executes in the scheduler. There is no
> second execution path.

Enforced by tests (`tests/test_inbox_and_scheduler.py`):

- the inbox module makes no governed call and writes no journal event (static check), and reading the inbox and
  the status line leaves every journal byte-identical (dynamic check);
- the simple view's only button opens an item: no Run, no re-run, no inline execution (static check), and
  rendering and opening an item writes nothing (dynamic check).

**Known exception, stated rather than hidden:** the classic view (`GAAR_UI` unset) keeps its Run button until it is
retired. Retiring classic is a governed decision with a changelog entry, taken once every classic surface is
reachable in the simple view (pinned by `test_every_assessment_the_classic_view_lists_is_reachable_in_the_simple_view`),
not something that happens by neglect.

## The scheduler

`tools/gaar_scheduler.py tick` runs every registered job once; `install` writes the launchd job `com.gaar.scheduler`,
which replaces `com.gaar.recurring` (it refuses to install while the old one is loaded: one scheduler per workspace).

Job contract:

1. A job's outcome is a signed `job_outcome` event in `scheduler/operations.sqlite`; each tick ends with a signed
   `scheduler_tick` event carrying its interval.
2. **Isolation.** A job that raises does not stop the others. Its failure is its outcome, and the inbox shows it.
3. **Stopping at a gate is what creates work.** A job runs up to a governed gate and stops. It never writes the
   inbox item: the item is derived from the journals the job wrote. It never writes past the gate (no reading, no
   decision, no attestation).

Jobs registered in v20:

| Job | What it does |
|---|---|
| `series` | The standing-authorisation series: runs periods whose exports arrived; reruns a record blocked only by a software upgrade (runbook U1) |
| `watcher` (kit v21) | Regulatory watch: checks each subscribed source when due, every 8 hours by default; does nothing until `tools/gaar_watch.py setup` |
| `gate_status` | Regenerates the live gate-status report the status line reads |

**Not yet in the scheduler:** the AI Auditor, Autopilot and measurement runs keep their existing paths (manual, or
their own jobs). Each moves in as its own change, with a job test. On the pilot's deterministic path, model stages
are disabled, so the AI Auditor and Autopilot have nothing to run there anyway. The status line names the jobs it
covers, so a green line never implies coverage of anything outside them.

## The inbox

Derived, read-only, from the signed journals. Each item names the event it comes from and its age.

**Order:** system items first (while one is open, the rest cannot be trusted), then overdue, then oldest first.

**Aging is signed policy, not a UI preference:**

- an attestation is due within one cadence of its record becoming ready: the series' `cadence_days`, signed in the
  standing authorisation;
- missing exports are overdue after the signed `grace_days` (the existing rule).

Proposed for the next policy revision: state the attestation-due rule in the policy text itself. It is not changed
now, because changing the policy text stops every series pinned to 1.3 (§9.3), including the open demonstration.

**The empty-inbox trust problem.** A dead scheduler produces an empty inbox, not a failing one. So the scheduler's
health is on the inbox page itself: "never ran" and "stale" (no tick for two intervals) are system items, and the
status line says when it last ran. This delivers, and retires, the deferred scheduler-staleness flag ("the scheduler
hasn't checked since X").

## The status line

"Gates: 6 held, 1 open · 1 item(s) waiting · scheduler last ran 5 min ago". **The status line reports governance; it
is not governance.** It is derived from the gate-status report the scheduler generates and from the journals, never
typed in by hand, and its tooltip says so and how to verify the report.

## Frozen packs

A live report is an operating view: regenerated later, it can differ. What is handed to a reader outside the team is
a frozen pack (`tools/gaar_pack.py freeze`): the report verified at that moment, its rendering and the workpaper, with
a manifest of hashes, zipped. `verify` checks the frozen bytes and the report's own hash. It deliberately does not
regenerate: the pack is what was true when it was frozen, and says so.

## Reading order and read-versus-sign

- The opened item shows the period delta and the reconciliation **before** the decision form (anti-anchoring order,
  policy 1.3 §8), pinned by `test_the_reviewer_reads_the_evidence_before_the_decision_form`.
- The confirmation is keyed to the record on screen. If the scheduler reruns the record while the reviewer reads
  (U1), the confirmation resets and must be given again.

## Defect D18 (found on the Mac, kit v19)

v19 changed code inside the software fingerprint, so week 3 (produced under v18) could no longer be attested, while
the milestone tool told the reviewer to go and sign it. Runbook U1 already prescribed the remedy (rerun under the new
version); nothing performed it. v20 does, in the scheduler's `series` job:

- only when the software or knowledge base is the **only** change: a changed evidence export is a potential integrity
  event (runbook E1) and is never rerun away; a changed policy is not an upgrade;
- never on an attested record;
- on the clock the record was assessed on (a constructed demonstration is not re-judged against real time);
- the superseded case journal is moved aside intact and the new journal opens with a signed `record_superseded`
  event naming its head and file hash;
- if the rerun produces no record, the previous record is restored, so the period never reads as unassessed.

## Scope of v20

The pilot reviewer app (`app_gaar.py`, `GAAR_UI=simple`). The 16-tab workbench (`app.py`) is not migrated yet; its
tabs map to the three views as in the proposal (Inbox, Control page, Prove), one move at a time, each with a
reachability test.
