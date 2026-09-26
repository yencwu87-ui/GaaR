# Result as a Service

GaaR sold as a **Warranted Control Period**: one control family, one period, every in-scope control tested on real
evidence, every exception closed or formally accepted, and a published false-assurance rate backed by a capped
warranty. Parameters: `config/raas.yaml`. Code: `governance/raas/`. Tests: `tests/test_raas.py`.

| Module | File | Idea | Rule that makes it trustworthy |
| --- | --- | --- | --- |
| M1 Reg-to-Control | reg_to_control.py | Regulation to working controls | Each obligation quoted verbatim with offsets and the publication hash. One named person decides each item. Bulk sign-off refused. Never proposes a retirement |
| M2 Outcome Verifier | verifier.py | Verify any agent's results | The agent receives the prompt only. FAR published with sample size and an exact 95% upper bound, or not at all (min 50 planted) |
| M3 Closure Desk | closure.py | Pay per closed finding | Closed only by a retest from someone other than the owner. Risk acceptance by a non-owner, with a reason and an expiry of at most 365 days. An expired acceptance reopens |
| M4 Assurance Warranty | warranty.py | Insure AI outcomes | Issued only when the 95% upper bound on FAR is at or below 1%. Refund 3x the control fee, capped at 25% of the period fee, 12-month claim window, assessor is not the claimant |

`result.py` assembles the pack and the outcome-priced invoice. `python -m governance.raas.demo` runs one constructed
quarter end to end, with state in `GAAR_RAAS_HOME` (default `~/gaar-raas`).

## Block 1: the chain, wired (25 September 2026)

One command runs an order's period and ends in a sealed pack: `python -m governance.raas.period ORD-DEMO` (or
`python tools/gaar_raas.py period ORD-DEMO`); the scheduler's `raas` job seals any order in the RaaS home whose period
has ended.

| Task | What is now true | Code |
| --- | --- | --- |
| B1-1 Period orchestrator | An order file (`config/raas_orders/ORD-DEMO.yaml` is the constructed one; real ones live in `<RaaS home>/orders/`) runs M1 to M4 and seals the pack once | `period.py`, scheduler job `raas` |
| B1-2 Watch to M1 | A MAS publication marked RELEVANT in the watch becomes an inbox item to save its text; `propose-from-watch` runs M1 on the saved file (text, or a PDF read locally) and keeps the text under its hash; undecided proposals are inbox items, decided one item at a time | `watch_link.py`, `production/inbox.py` |
| B1-3 Exception hook | Every finding in a series period's reconciliation opens one closure exception, keyed by its issue id, with the hash of the export that raised it; running it again opens nothing twice | `series.py` |
| B1-4 Retest by re-execution | A retest PASS needs a passing rerun the desk itself executed, after the latest fix, on evidence other than the evidence that raised the exception. For series findings the rerun is the series' own procedure (change_authorization) on the corrected export; an export it cannot compare is a FAIL | `closure.rerun`, `series.retest_for` |
| B1-5 Planted cases in periods | Each period verifies the order's agent on 500 planted cases mixed with 500 clean ones, drawn with a seed derived from the tenant's secret signing key, new each period; the pack carries a commitment to the seed, never the seed | `period.sealed_seed` |
| B1-6 Sealed pack | The pack is sealed with its own passport (`gaar.raas.pack-passport.v1`): content hash, Merkle root over its sections, Ed25519 signature with the tenant key. It verifies offline and fails if one byte changes or another key signed it | `seal.py` |
| B1-7 Read-only API | `/v1/periods`, `/v1/periods/{pack_id}`, `/v1/verifications`, `/v1/warranties`, and `POST /v1/packs/verify`, each needing the API token even when none is configured elsewhere; the seed is never served | `services/raas_api.py` |

A warranty is issued only when the bound qualifies **and** the period is complete: a warranty over exceptions still
open, or over an unsigned regulatory change, would insure known failures.

## Eligibility: decided 25 September 2026

| Band, by the 95% upper bound on FAR | Tier | What is sold |
| --- | --- | --- |
| at or below 1% | WARRANTED | Assured controls, with the warranty |
| above 1%, at or below 3% | MONITORED_ONLY | Monitored controls at a lower price (`prices.control_monitored`, set by the owner; unset, such a control cannot be priced). No warranty |
| above 3% | NOT_ASSURED | M1 and M2 only, as tools |

- **The bound, not the point estimate.** A point estimate of 0.3% on 300 cases cannot support a warranty; the bound
  can, and it is the figure a bank's model risk team asks for.
- **The method, so anyone can reproduce it.** Clopper-Pearson, exact and one-sided at 95%, rounded up to 4 decimals
  (`verifier.BOUND_METHOD`, stated on every verification and pack). D33: the first version rounded half-up, which let a
  bound of 1.0011% read as 1.00%; that is why 471 and 625 appeared as thresholds before the exact 473 and 628.
- **Sample size.** Against 1%: 0 misses need 299 planted cases, 1 miss 473, 2 misses 628. A period plants 500
  (`verification.planted_per_period`): **500 planted cases tolerate exactly one miss** (1 in 500: 0.95%, a pass;
  2 in 500: 1.26%, monitored-only).
- **Two figures, never one.** FAR comes from planted cases. Precision comes from real detections labelled under the
  real-records protocol. They are reported side by side and never merged.
- **Hosted models.** Unchanged: hosted models receive constructed cases only. Widening this to a bank's approval is a
  separate, deliberate change with its own conditions, not part of this design.

## Known limit, stated on every pack

Twin truth is self-authored: a regression measure, not independent qualification. Planted mutations of real records
are self-authored too. Only an independent reviewer's adversarial pack answers that, so it gates the first real
warranty.
