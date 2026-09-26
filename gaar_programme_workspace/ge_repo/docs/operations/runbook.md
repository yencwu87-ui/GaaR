# GaaR pilot operations runbook

This runbook is the authoritative statement of these rules. Messages in the software point here;
they implement the rules, they do not replace them.

## U1 — Software upgrades during an open series

Every result is bound to the exact software that produced it. After an upgrade, results produced
before it can no longer be attested, because the signature would bind a person to output the current
software never produced.

1. Before upgrading, attest every result that is awaiting attestation.
2. If a result cannot be attested before the upgrade, the scheduler reruns that period under the new version on
   its next tick (kit v20; `python tools/gaar_scheduler.py tick --config …`), and you attest the new result. It
   does so only when the software is the only change, never on an attested record, and on the clock the record
   was assessed on. The superseded journal is kept intact under `pilot/superseded/`.
3. Attestations already given are unaffected by an upgrade.
4. Record the upgrade (version, date, who) in the pilot log.

## O1 — Overdue evidence

A period's exports are expected in its inbox folder after the period ends. The grace period is a
named value in the signed standing authorisation (default 2 days).

| State | Meaning |
|---|---|
| NOT_YET_DUE | the period has not ended |
| AWAITING_EVIDENCE | the period ended, within the grace period |
| OVERDUE | the grace period has passed and the exports have not arrived |

An OVERDUE period is a pipeline failure, not a neutral state. The evidence owner is told once,
the cause is found, and the finding and its resolution are recorded in the pilot log.

## O2 — Exports that arrive before their period ends (D14)

Nothing is assessed before its period has ended. The slack window for clock skew is a named value in the
signed standing authorisation (default 10 minutes).

| Arrival | Treatment |
|---|---|
| Declares complete collection before the period ends | Not run. Moved, untouched, to the inbox's `_quarantine` folder and recorded as a signed integrity event (E1) |
| Partial, before the period ends | Not run. Waits for the period to end; a partial export never corroborates coverage |
| After the period ends (less the slack window) | Normal: the rules above apply |

The check sits in the collector contract, so every collector inherits it.

A simulated clock is permitted only for a series whose signed authorisation marks it as a constructed
demonstration. It is recorded in the result, shown prominently to the reviewer, and carried into the signed
attestation. It is never available for real evidence.

## S1 — One scheduler per workspace

Run either `watch` (for live demonstration) or the launchd job (unattended), never both. The software
enforces this with a lock; the rule states the intent.

## E1 — Changed evidence

A changed or missing export after a run is treated as a potential integrity event: find out who
changed it and why before anything else, and record the outcome.
