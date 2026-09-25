# Result as a Service (kit v31)

GaaR sold as a **Warranted Control Period**: one control family, one period, every in-scope control tested on real
evidence, every exception closed or formally accepted, and a published false-assurance rate backed by a capped
warranty. Parameters: `config/raas.yaml`. Code: `governance/raas/`. Tests: `tests/test_raas.py`.

| Module | File | Idea | Rule that makes it trustworthy |
| --- | --- | --- | --- |
| M1 Reg-to-Control | reg_to_control.py | Regulation to working controls | Each obligation quoted verbatim with offsets and the publication hash. One named person decides each item. Bulk sign-off refused. Never proposes a retirement |
| M2 Outcome Verifier | verifier.py | Verify any agent's results | The agent receives the prompt only. FAR published with sample size and an exact 95% upper bound, or not at all (min 50 planted) |
| M3 Closure Desk | closure.py | Pay per closed finding | Closed only by a retest from someone other than the owner. Risk acceptance by a non-owner, with a reason and an expiry of at most 365 days. An expired acceptance reopens |
| M4 Assurance Warranty | warranty.py | Insure AI outcomes | Issued only when the measured FAR is at or below 1%. Refund 3x the control fee, capped at 25% of the period fee, 12-month claim window, assessor is not the claimant |

`result.py` assembles the pack and the outcome-priced invoice. `python -m governance.raas.demo` runs one constructed
quarter end to end, with state in `GAAR_RAAS_HOME` (default `~/gaar-raas`).

## Known limit, stated on every pack

A 0/50 false-assurance count gives a 95% upper bound of 5.8%, not 1%. Showing the upper bound itself below 1% needs
about 300 clean planted cases. Until then the warranty's eligibility reads the point estimate (each certificate's `eligibility_basis` says so, and
whether the upper bound would also have qualified), the reserve is checked
against the upper bound, and the cap bounds the exposure. Twin truth is self-authored: a regression measure, not
independent qualification.
