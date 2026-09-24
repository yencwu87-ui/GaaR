# WB-104 — Evidence Intelligence

The live evidence scanner now has an additive retrieval path:

```text
Control query
   │
   ├── BM25 (existing, explainable)
   │
   └── Bi-encoder candidate expansion (optional)
             │
          candidate pool
             │
       Cross-encoder rerank (optional)
             │
        Sufficiency Gate
             │
        Evidence bundle
```

## Safety/compatibility

The current BM25 path remains the default. No model is downloaded merely by importing the
engine. Bi-encoder and cross-encoder stages are enabled independently through environment
variables so they can be activated after the Colibri work without destabilising the live path.

## Enable the bi-encoder

```bash
export WB_EVIDENCE_BI_ENCODER=1
```

The existing local embedding adapter is used (`WB_EMBED_MODEL`, default `nomic-embed-text`).
If the embedding backend/model is unavailable, the receipt records a degraded bi-encoder lane
and BM25 remains usable.

## Enable the cross-encoder

Install the optional dependency first:

```bash
pip install -r requirements-retrieval.txt
```

Then:

```bash
export WB_EVIDENCE_CROSS_ENCODER=1
export WB_CROSS_ENCODER_MODEL=\"cross-encoder/ms-marco-MiniLM-L6-v2\"
```

The model is loaded lazily on the first rerank call. No model download occurs until that path is
actually exercised.

## Candidate/rerank settings

```bash
export WB_EVIDENCE_CANDIDATE_K=12
export WB_EVIDENCE_RERANK_K=6
```

These control candidate-pool size and reranked output depth. They do not represent governance
thresholds.

## Sufficiency gate

The gate records a machine-readable result in every auto-built evidence bundle:

- `PASS` when configured structural/calibrated policy is satisfied;
- `BLOCKED` when configured candidate/score requirements are not met;
- `CALIBRATION_REQUIRED` when enforcement is configured but no calibrated score threshold exists.

No universal semantic threshold is assumed. Calibrate on the repository's labelled evaluation
set before enforcing a numeric cosine or cross-encoder score.

Optional enforcement:

```bash
export WB_EVIDENCE_GATE_ENFORCE=1
```

With enforcement enabled, a control whose retrieval gate does not return `PASS` is withheld from
`match_controls()` rather than being silently assessed on weak retrieval.

## Audit receipt

`pipeline.build_evidence()` preserves:

- candidate chunk IDs;
- BM25 score;
- bi-encoder cosine, when available;
- cross-encoder score, when available;
- retrieval methods used;
- reranker model;
- sufficiency-gate decision and policy.

This information is evidence-selection provenance only. It does not set sufficiency, maturity,
compliance, or a human governance decision.
