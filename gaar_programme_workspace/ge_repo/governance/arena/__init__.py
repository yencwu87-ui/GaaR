"""The model arena (kit v22): blind battles between models on labelled cases.

Founding rule: a model can raise a flag or hold a result; only a signed person can clear one. Winning the arena earns
a model an advisory seat under policy §8, never a signature.

- Cases come from the digital twin, so every case has labelled truth, and that truth is self-authored: every report
  says so until an independent corpus exists.
- Scoring reads what the model attempted (its raw answer), not what a validator later let through (D13).
- An answer without a confidence is a HOLD (Jev adapter contract, coverage note Appendix A).
- The cost of a false "authorised" is a named parameter (config/arena.yaml), and raw precision and recall are reported
  beside the weighted score.
- A case goes to an endpoint off this machine only if it is constructed.
"""
