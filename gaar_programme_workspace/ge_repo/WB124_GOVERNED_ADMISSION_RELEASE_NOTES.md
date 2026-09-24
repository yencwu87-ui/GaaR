# WB-124 — Governed evidence admission to the existing core review cycle

**Lab checkpoint, not Mac-live acceptance, not full STP, and not production identity/access management.**

## Actual new functionality

- `governance/admission/service.py`: admission read-only dry-run by default; explicit apply checks ledger-backed WB-120R acquisition and WB-122 dossier, content hash, source CAS bytes, exact anchored excerpt, time/freshness, required elements, distinct byte hashes and bounded quotas. Existing Evidence Examiner runs deterministic lexical coverage preflight, **not a semantic sufficiency/compliance verdict**.
- Explicit `human` or `service` requester category, default `allow_service=False`. Claimed local operator names are **not authenticated identities**; use restricted CLI/filesystem access until authenticated UI/RBAC integration is built.
- Ed25519 signing using the **already configured** `WB_GAAR_RESULT_SIGNING_KEY_B64` and `WB_GAAR_RESULT_KEY_ID`; never invent a signature or silently disable result sealing. The existing signing key is reused, never bundled in the ZIP.
- Hash-chained `governance/evidence_admissions.jsonl`: `EvidenceAdmissionPrepared` includes per-anchor references, content identity and signature; then `core.cycle.bind_admitted_evidence` verifies signature against the configured trusted public key and exact bound bundle, writes existing `evidence_bound`; `EvidenceCycleBound` records completed handoff. The evidence set is authoritative **within that review cycle**; it is not a new global evidence registry and does not retroactively change sealed results.
- The existing GovernanceResult compiler reads admitted `evidence_set_id` when no pinned reassessment source ID takes precedence.
- WB-123 audit package inspection can now detect the actual admitted cycle/dossier pair; a raw Scout dossier alone remains PROPOSED_ONLY. Blind-read, compare, human decision and final Quality Gate still apply.
- `tools/admission_cycle_start.py`, `tools/admit_evidence.py`, `tools/admission_probe.py` for real local acceptance; no fake result creation.

## Before doing anything on your Mac

Back up your existing `ge_repo/governance/` durable ledgers and your **private** signing configuration to a secure destination. Do not overwrite the WB-123 workspace. Install this complete ZIP to `~/gaar_wb124_workspace`; source `~/.config/gaar/result-signing.env`, do not regenerate the key. Treat the bundled baseline ledger content as lab/demo data; do not merge it into production.

```bash
mkdir -p "$HOME/gaar_wb124_workspace"
unzip -q "$HOME/Downloads/ge_reviewer_copilot_v1_GAAR_WB124_governed_admission_checkpoint.zip" -d "$HOME/gaar_wb124_workspace"
cd "$HOME/gaar_wb124_workspace/ge_repo"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
source "$HOME/.config/gaar/result-signing.env"
python -m pytest -q tests/test_wb124_admission.py tests/test_wb124_integration.py
```

## Live local admission against YOUR evidence (not synthetic)

**Use the exact playbook control ID**. SAFR examples often use `S2.2` (not the shorthand `2.1` used in older notes). Check `python -c 'from core.cycle import _control;print(_control("S2.2","SAFR"))'` first. Use the requirement wording and elements for that **actual** control; do not claim a synthetic threshold example is the official control statement.

1. Run `tools/audit_stp_prepare.py --root /YOUR/APPROVED/ROOT --control S2.2 --framework SAFR --requirement-version req_your_real_version --requirement 'YOUR ACTUAL REQUIREMENT' --assertion 'YOUR ACTUAL ASSERTION' --element 'EXACT ELEMENT A' --element 'EXACT ELEMENT B'`. Capture `dossier_id`. Preparation returns exit 2 when CHECKPOINT_REQUIRED, which is expected.
2. Create a new review cycle: `python tools/admission_cycle_start.py --control S2.2 --framework SAFR --requirement-version req_your_real_version --actor YOUR_LOCAL_OPERATOR`; capture `cycle_id`. **This writes a real cycle event**, do not repeat needlessly.
3. Read-only admission preflight:

```bash
python tools/admit_evidence.py \
  --dossier-id REAL_DOSSIER_ID --cycle-id REAL_CYCLE_ID \
  --actor-id YOUR_LOCAL_OPERATOR \
  --element 'EXACT ELEMENT A' --element 'EXACT ELEMENT B'
```

4. Only after preflight returns `PREFLIGHT_PASSED` and the actual evidence has been scrutinised, repeat it with `--admit` at the end. This writes the admission ledger and existing authoritative review-cycle `evidence_bound` event. It does **not** record a human governance decision.
5. Read-only verification: `python tools/admission_probe.py --cycle-id REAL_CYCLE_ID`. Expect `PASS`, verified blobs, signed admission and `AUTHORITATIVE_CYCLE_EVIDENCE`. Run `python tools/audit_package_run.py --cycle-id REAL_CYCLE_ID --dossier-id REAL_DOSSIER_ID` for the combined checkpoint (may return exit 2 until the normal review is completed).
6. Continue review via existing Review UI, human blind read, compare, challenge, decision and Quality Gate. **Do not assert CURRENT based only on WB-124 admission**.

If freshness, evidence gaps or Examiner preflight blocks admission, provide stronger current evidence and **create a new dossier**, not a fabricated approval or a lowered universal threshold.

## Operational limitations and crash behavior

- The local CLI is an operator tool, not an authenticated web identity/RBAC endpoint. Admission signing proves use of the configured software key, not who was physically at the keyboard.
- Origin authenticity (e.g. GitHub API identity), independent corroboration, verified operational chronology, and semantic control effectiveness are NOT proven by byte hashes/lexical coverage. Full authenticated external connectors remain open.
- Quality Gate cannot declare a complete GovernanceResult FINALIZABLE before assessor/challenger and a genuine human decision; WB-124 does **not** pretend to run final Quality Gate as an evidence preflight.
- The append-only admissions ledger and legacy cycle-event ledger are **two distinct files** and not a distributed atomic transaction. The prepared/committed record split makes interrupted binding visible to the read-only probe; recover manually after investigating rather than deleting/replaying ledgers. Production crash-recovery/concurrent admission lock is an open hardening task.
- WB-125 review policy migration and WB-126 one-click/batch human decision are not shipped here.

## Verified isolated lab

`python -m compileall -q .` PASS; focused WB-124 11 tests PASS; extended A→RaaS critical regression 97 tests PASS. An isolated subprocess rehearsal ran dry-run → applied signed admission → read-only probe, verifying two CAS blobs and one `evidence_bound` cycle event. This was synthetic lab evidence, **not** your Mac and **not** evidence of control effectiveness.
