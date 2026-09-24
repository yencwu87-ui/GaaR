# WB-122 Evidence Dossier + Scrutiny — Lab-validated increment

## Scope

Evolves the existing WB-120R Evidence Scout. From a **specific** append-only WB-120R acquisition receipt, the Assembly component:

1. Resolves only explicitly approved source IDs to local roots.
2. Confirms every candidate belongs to a fresh receipt snapshot.
3. Rejects `..`, absolute candidate paths, symlinks, source escapes, changed bytes (SHA-256), and altered quotes.
4. Preserves exact verified bytes in local SHA-256 content-addressed blobs, never overwriting a blob.
5. Builds a `PROPOSED_ONLY` dossier with anchors, candidate element links, explicit limitations, and a structured scrutiny surface.
6. Appends a hash-chained dossier record and offers a read-only blob/chain probe.
7. Displays dossiers in the Streamlit **Living Results → Evidence Dossiers · scrutinise proposed evidence** drawer, visibly separate from any CURRENT governance result.

This implementation does **not** claim the Scout or dossier has admitted evidence, judged maturity, proved operating effectiveness, checked independent event chronology, issued a human decision, invoked the Challenger, or transitioned a GovernanceResult. An integrity hash is **not** a digital signature or authentication of the source owner. The sample records in the demo are synthetic and are not audit evidence of an actual organization.

## Reproduce on Mac

Extract the full ZIP, `cd ge_repo`, and run:

```bash
python -m compileall -q .
python -m pytest -q tests/test_wb122_evidence_dossier.py tests/test_wb120_refresh.py tests/test_wb120_evidence_scout.py
```

Use an **approved, non-sensitive local evidence folder** to build a proposal. Never clear your existing governance history. Keep the acquisition and dossier ledgers at the same paths across invocations:

```bash
export WB_GAAR_SCOUT_ACQUISITION_STORE="$PWD/governance/evidence_acquisitions.jsonl"
export WB_GAAR_DOSSIER_STORE="$PWD/governance/evidence_dossiers.jsonl"
python tools/scout_refresh.py \
  --root "/absolute/path/to/approved/evidence" \
  --control 2.1 --framework SAFR \
  --requirement-version req_v2.4 \
  --requirement "Threshold approval before deployment" \
  --element "Threshold policy" \
  --element "Pre-deployment approval"
```

Copy the ACTUAL printed `acquisition_id` (starts `EA-`), then:

```bash
python tools/assembly_run.py \
  --acquisition-id 'EA-REPLACE-WITH-ACTUAL-ID' \
  --source "root1=/absolute/path/to/approved/evidence" \
  --assertion "Threshold approval before deployment" \
  --element "Threshold policy" \
  --element "Pre-deployment approval" \
  --output dossier_SAFR_2_1.md
python tools/dossier_probe.py
./start_ui.sh
```

`root1` is the source ID that `tools/scout_refresh.py` assigns to its first `--root`; repeating `--root` produces root2, root3, etc. Bind every used source explicitly with corresponding `--source` values. `assembly_run.py` will fail closed if a candidate changed after discovery. The probe only reads dossier ledger and CAS blobs; it does not register evidence.

## Actual isolated lab output (2026-09-19)

```text
Scout acquisition_id: EA-b9e17e84705d459291b9296adb87e506
Scout binding: PROPOSED_ONLY
Scout candidates: 2, source_count: 1
Assembly dossier_id: ED-cbca632466385d8497d01b910c0b7d7b
Assembly anchors: 2
Assembly challenge_points: 3
Assembly binding: PROPOSED_ONLY
Probe ledger_chain: OK
Probe dossiers: 1
Probe anchors_verified: 2
Probe binding: PROPOSED_ONLY
Read-only probe: no change in SHA-256 of acquisition or dossier ledger
WB-122 unit tests: 12 passed
A→RaaS selected critical regression: 81 passed
compileall: PASS
```

All IDs above are **isolated synthetic lab artifacts**, not Mac-live evidence and not part of the shipped runtime ledgers.

## What remains before full WB-122 GREEN

- Independently validated operational chronology, not just a source inventory and challenge questions.
- Governed evidence admission (separate policy-controlled service, TOCTOU reverify from immutable snapshot, EvidenceSet binding).
- Independent Challenger interrogation of dossier assertions with admitted challenge outputs.
- Mac-local proof with real, approved evidence sources and UI rendering.
- True external authenticated connector + source-origin authentication as a distinct control from SHA-256.

Never label a dossier `CURRENT`, `FINALIZABLE`, or `SIGNED` based solely on the assembly process.
