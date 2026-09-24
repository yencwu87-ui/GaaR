# WB-125 — Signed Routine Blind-Read Waiver (bounded checkpoint)

## Scope and constraints

The *existing* core cycle now accepts a signed, opt-in **routine-only** waiver event. It replaces only intermediate blind-read and comparison. No fabricated read or diff is recorded. A challenge is **still required** before decision, as are human final decision, signed GovernanceResult and enabled final Quality Gate. A missing independent proposal challenger means the Conductor stops at `CHALLENGE_REQUIRED`; this checkpoint is **not** complete straight-through or batch approval.

Eligibility fails closed without: a prior decided cycle of the same framework/control; ledger-verified WB-124 admission into the current cycle; known fresh evidence; explicit risk tier `low` or `medium`; explicit governance context flags `material_change=false`, `evidence_contradiction=false`, `unresolved_strong_challenge=false`, `quality_blocked=false`, `governance_exception=false`, `independent_review_required=false`, explicit confidence >=.75; a recorded assessor proposal; and an externally approved Ed25519-signed local policy whose verification key matches configured signing identity. All conditions are rechecked at the human decision boundary. Disable the waiver flag to restore the standard path for any not-yet-decided cycles. The signed policy file contains no private signing key.

**Not production identity assurance:** `--actor` is a local self-declared identity; this release does not implement SSO, RBAC or a real human authorisation service. Do not treat issuance of the policy file as proof of organisational approval. Keep the actual approval outside GaaR and use the signed artifact as a traceable representation.

**Important:** The prior decision and risk-tier conditions intentionally mean a first assessment, a control lacking reliable risk metadata, or a missing contextual declaration cannot be classified routine. An LLM cannot choose its review tier. A missing challenge is not a clean challenge.

## Install

Extract the ZIP into a **new** workspace; do not overwrite your live repo or copy its ledgers into a fresh demo. Create venv and install `requirements-dev.txt`. Reuse the *existing* `~/.config/gaar/result-signing.env`, do not rotate its private key.

```bash
cd "$HOME/gaar_wb125_workspace/ge_repo"
source .venv/bin/activate
source "$HOME/.config/gaar/result-signing.env"
python -m pytest -q tests/test_wb125_routine_waiver.py
python -m compileall -q .
```

## Sign and activate an approved policy **only after your governance approval**

```bash
python tools/routine_waiver_policy.py \
  --output "$HOME/.config/gaar/routine-waiver-policy.json" \
  --approve --actor 'YOUR_HUMAN_POLICY_APPROVER' \
  --reason 'Approved controlled waiver for eligible routine reassessments'
export WB_GAAR_ROUTINE_WAIVER_ENABLED=1
export WB_GAAR_ROUTINE_POLICY_FILE="$HOME/.config/gaar/routine-waiver-policy.json"
python tools/routine_waiver_policy.py --output "$WB_GAAR_ROUTINE_POLICY_FILE"
```

The policy issuance CLI refuses to overwrite an existing artifact; preserve old approvals for provenance. The signed policy must be kept and backed up with the signed results; policy revocation disables use of the waiver on pending cycles. Key rotation needs an explicit migration plan.

## On an **eligible admitted cycle**

Start a new cycle using the existing WB-124 admission procedure. It must have **cycle-start** `governance_context` containing explicit risk and change/exception flags, and must have an earlier decided same-control cycle. WB-125 extends `tools/admission_cycle_start.py` with explicit `--risk-tier`, `--assessment-confidence` and six `--assert-no-...` flags. Missing flags are **unknown**, not false. These are local operator assertions, not an authenticated policy registry or independently validated risk/classification. Use controlled organizational records to determine their values; never enter favorable values merely to unlock routine status. Do **not** fabricate a previous human decision. For example:

```bash
python tools/admission_cycle_start.py --control S2.2 --framework SAFR \
  --requirement-version req_v2.4 --actor 'YOUR_LOCAL_OPERATOR' \
  --risk-tier low --assessment-confidence 0.90 \
  --assert-no-material-change --assert-no-evidence-contradiction \
  --assert-no-unresolved-strong-challenge --assert-no-quality-blocker \
  --assert-no-governance-exception --assert-no-independent-review-required
```

This starts a fresh cycle; it does **not** create a prior decision or admit evidence. After your actual dossier is admitted and a proposal is recorded, use the waiver check/apply commands below.

```bash
python tools/routine_waiver_cycle.py --cycle '<REAL_CYCLE_ID>'        # READ ONLY
python tools/routine_waiver_cycle.py --cycle '<REAL_CYCLE_ID>' --apply # explicit event
```

The resulting `blind_read_waived` event records the signed policy hash and approver, and is hash-chained in the cycle ledger. The result provenance includes the policy hash. The Quality Gate checks the current signed waiver and re-evaluates eligibility. This **does not** create a GovernanceResult or act as an approval.

## Remaining work for WB-125 FULL / WB-123 FULL STP

1. Validated, independent AI **proposal** challenge (existing challenger is explicitly a reviewer-read/disagreement challenger, not an assessor-proposal challenger); automatic run must preserve that distinction.
2. Real policy approval identity/RBAC and UI to set authoritative risk and contextual metadata; current CLI is locally attributed.
3. End-to-end routine integration test on admitted evidence through actual model provider, challenger, individual/batch signed decision and CURRENT with final gate; Mac-live verification pending.
4. Elevated and critical paths remain existing full-blind review. No claim of automatic batch approvals.
5. Watcher global source catalogue and quarantine remain separate pending work; do not conflate source approval with evidence admission.

## Warning about previous pasted Mac protocols

`tools/admit_evidence.py --help` and `tools/admission_probe.py --help` show actual supported flags; the two quoted protocol variants disagree. Never mutate a live CAS blob for a tamper test. Use isolated tests with temp evidence blobs. Also do not assume a fixed number of real evidence anchors or a fixed proposal rating.

## Bundled Watcher source-safety correction (NOT global monitoring)

The disabled `demo-mas-regulatory-feed` now has `source_type: background` and `authority: background` instead of pretending a static demonstration feed is binding MAS regulation. The CISA KEV connector maps documented `cveID`, `vendorProject`, `product` and `dateAdded` fields into a meaningful title and publication date when that source is used. The enabled CISA source configuration explicitly requests `require_source_validation`; when such a source produces `Untitled`, no HTTPS origin, empty content, or no parseable publication date, Watcher records `INVALID_DOCUMENT`, reports `DEGRADED`, emits no governance trigger for that item, and does not advance the cursor past invalid items.

**Not implemented**: production document-level legal authority classification, human source approval, official landing-page validation, immutable source HTML/PDF preservation, live MAS/FCA/PRA/ISO connector coverage, and a universal quarantine process for all sources. Do **not** mark Watcher global coverage GREEN based on this correction. A CISA threat item must not become a binding regulation or a mandatory legal obligation.
