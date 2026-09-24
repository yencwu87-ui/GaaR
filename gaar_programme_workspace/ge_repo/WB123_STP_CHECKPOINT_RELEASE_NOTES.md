# WB-123 STP preparation checkpoint — what is implemented and what is not

**This is an executable incremental build on WB-122, not WB-123 full acceptance or Mac-live green.**

## Implemented

- Typed, deterministic review routing with conservative unknown-risk/first-assessment defaults, critical > elevated > routine. Any missing confidence, evidence admission, or freshness signal prevents routine routing. Classification is advisory; the approved core decision path is unchanged.
- One-command Scout refresh → verified source snapshots → PROPOSED_ONLY Evidence Dossier → typed, honest AI audit package checkpoint (`tools/audit_stp_prepare.py`). It writes proposal acquisition/dossier ledgers, never admits evidence or decides for a human.
- Existing bound review cycle package inspection and optional bounded Conductor machine-step execution (`tools/audit_package_run.py --cycle-id ... [--run]`); legacy mandatory blind-read remains intact. `--run` may call the real assessor and write existing audit events.
- Read-only batch-eligibility preview (`tools/batch_approval_probe.py`), fail closed on non-routine/blocked/duplicate/already-decided/unspecified quality. NO new batch approval backend is claimed.
- Sidebar imports moved into collapsed Administration; read-only observed counts for AI Auditor, Autopilot, Watcher and Scout; unified real-ledger activity timeline under AI Auditor. Status counts are observations, NOT claims that Watcher or Autopilot workers are continuously running.
- 19 new policy, package, guardrail tests and 86 focused + cross-workstream regression tests in isolated lab; compileall passed.

## Explicit open gates

1. WB-120R/WB-122 Scout dossier is PROPOSED_ONLY. Authenticated connectors and governed admission into authoritative EvidenceSet are not yet shipped. No auto-evidence binding is attempted.
2. Existing `core/cycle.py` and Conductor still enforce the human blind read and comparison stage. Policy classification alone **does not** override that. Routine blind-read waiver requires an explicit approved policy change **and** a corresponding core-contract migration; it is not implemented here.
3. One-click or batch human decision UI integrated with the actual signed result compiler and Quality Gate is not shipped. `batch_approval_probe.py` is read-only. No AI invokes `decide()` or CURRENT transition.
4. No claims of 5 real controls fully audited, zero human checkpoints, full autonomous STP publication, live Mac acceptance, or global regulator coverage.
5. The policy YAML is a proposal; Python router is the deterministic implemented pilot. YAML modifications do not silently modify approved policy.

## Install on Mac without overwriting your existing work

```bash
mkdir -p "$HOME/gaar_wb123_workspace"
unzip -q "$HOME/Downloads/ge_reviewer_copilot_v1_GAAR_WB123_STP_checkpoint.zip" -d "$HOME/gaar_wb123_workspace"
cd "$HOME/gaar_wb123_workspace/ge_repo"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
source "$HOME/.config/gaar/result-signing.env"  # existing key, if already configured
python -m pytest -q tests/test_wb123_audit_package.py
```

Do not delete or overwrite the durable ledgers in your existing WB-122 workspace. New extracted workspaces may include the repository's baseline sample ledgers; keep demo/acceptance and production data separate. Back up key and ledgers using your existing operator runbook.

## One-command STP preparation on real approved evidence

```bash
cd "$HOME/gaar_wb123_workspace/ge_repo"
source .venv/bin/activate
python tools/audit_stp_prepare.py \
  --root "/ABSOLUTE/PATH/TO/YOUR/APPROVED/EVIDENCE" \
  --framework SAFR --control 2.1 --risk-tier low \
  --requirement-version req_v2.4 \
  --requirement "Governed threshold approval before deployment" \
  --assertion "Thresholds approved before deployment" \
  --element "Thresholds documented" \
  --element "Pre-deployment approval recorded" \
  --output "$HOME/gaar_wb123_dossier.md"
```

Exit code **2 is expected** when a proposal correctly stops at its admission/review checkpoint; inspect the JSON `status`, `blockers`, `acquisition_id`, `dossier_id`, and counts. This is not a crash. Do not treat lexical matching as evidence sufficiency, chronology proof or regulatory compliance.

## Existing governed audit cycle: inspection (read only)

```bash
python tools/audit_package_run.py --cycle-id REAL_CYCLE_ID
```

Optional existing machine-only processing (may write review events and call Ollama):

```bash
python tools/audit_package_run.py --cycle-id REAL_CYCLE_ID --run
```

No CLI here issues human approval. Record actual reviewer read and human decision in the existing GaaR Review UI. Existing signing configuration still required when result sealing is enabled.

## UI

```bash
source "$HOME/.config/gaar/result-signing.env"
./start_ui.sh --server.address 127.0.0.1 --server.port 8502
```

Open AI Auditor to view WB-123 package checkpoint and unified activity timeline. Imports are under Administration in sidebar. Watcher/Autopilot polling remains separately operated; ledger observations do not imply they are running as daemons.

## Lab verification

```
python -m compileall -q .             PASS
new WB-123 tests                      19 passed
WB-123 + WB-122 + Scout + Watcher + AI Auditor + Quality Gate + Colibri + Copilot  86 passed
isolated STP sample: 1 acquisition, 2 anchors, 3 scrutiny questions, CHECKPOINT_REQUIRED (correct)
```

`WB-123-READY` for **full STP** is NOT claimed by this checkpoint. Implement governed admission and core-policy migration before advertising one human decision per routine result.
