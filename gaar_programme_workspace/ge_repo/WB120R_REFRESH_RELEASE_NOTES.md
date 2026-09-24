# WB-120R — Evidence Scout refresh hardening (RC1 additive)

**Status:** LAB-VALIDATED; approved-local-root connectors only. This is not a claim of fully autonomous cloud evidence acquisition.

Adds `governance/evidence_scout/refresh.py`, `tools/scout_refresh.py` and `tests/test_wb120_refresh.py` on top of the existing WB-120 evidence candidate Scout. The existing API and Scout behavior remain intact.

## Reproducible Mac command

```bash
cd ge_repo
python -m pip install -r requirements.txt
python -m pytest -q tests/test_wb120_refresh.py tests/test_wb120_evidence_scout.py
python tools/scout_refresh.py --root /absolute/path/to/approved/evidence \
  --control 2.1 --framework SAFR --requirement-version req_v2.4 \
  --requirement 'Governed threshold approval before deployment' \
  --element 'Thresholds documented' --element 'Pre-deployment approval recorded'
```

Outputs include `PROPOSED_ONLY`, hash-stamped exact-file receipts, approved source IDs, freshness/staleness, gaps, source diversity and deterministic Evidence Examiner preflight. Receipts append to `governance/evidence_acquisitions.jsonl`; the Scout cannot bind the candidates or change the quality gate or a control result.

## Validated scope

- Existing WB-120 Scout candidate discovery and deduplication
- Explicit approved local roots only; no symlink escape or binary evidence
- File/byte quotas, age expiry, minimum distinct sources and honest gaps
- SHA-256 candidate receipts with append-only hash-chained acquisition records
- Typed deterministic Evidence Examiner preflight using explicit unbound proposal IDs
- No assertion that the preflight score proves compliance or quality-gate acceptance

## Not yet delivered (do not claim GREEN against the full external WB-120 spec)

- Authenticated AWS Config / GitHub / Trivy / SharePoint evidence connectors
- Long-running per-connector poller, API pagination/backoff/circuit breaker
- Persistent per-connector cursors and immutable evidence binary snapshot storage
- Automatic binding to the canonical EvidenceSet and triggering live reassessment
- Real Mac/cloud credentials/browser and local Ollama/Colibrì E2E run

**Authority invariant:** EvidenceScout proposals are not evidence accepted into a governance cycle. Only an explicit governed registration/binding action can change the evidence input; sufficiency and maturity are determined downstream.
