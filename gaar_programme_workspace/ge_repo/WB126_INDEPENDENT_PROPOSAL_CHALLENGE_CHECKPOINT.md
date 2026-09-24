# WB-126 — Independent assessor-proposal challenge (bounded release)

**Lab checkpoint only.** The independent challenge now handles an admitted, signed-routine-waiver review **without ever consuming the assessor's rationale or inventing a human blind read**. It does not make the human decision, issue CURRENT, authenticate an operator, or automatically resolve strong findings. Full human-on-exception STP and one-click/batch decision remain pending.

## The operating boundary

1. Existing WB-124 cycle must contain ledger-verified admitted evidence and a current WB-125 signed routine waiver. First-time, unknown-risk, elevated, critical, stale and material-change cycles fail closed as before.
2. Input is an allowlisted assessor **verdict** (sufficiency, maturity, element ID/status), governed control requirement and actual admitted CAS content. Rationale, narrative, blind human read, and prior challenge are never forwarded. Strong claim of two **different models** is not warranted merely from context isolation; configure distinct `WB_MODEL_ASSESS` and `WB_MODEL_CHALLENGE` if supported by your runtime, and verify execution telemetry. Ollama's challenger role uses a distinct default seed (`29` vs `7`), configurable via `WB_CHALLENGE_SEED`.
3. Readable CAS bytes are rehashed again **before** the challenge. `WB_GAAR_EVIDENCE_BLOB_ROOT` must point to the same blob root used by admission if it was customized; default is `ge_repo/governance/evidence_blobs`. Exact source quotations are validated against the reverified admitted bytes.
4. A real configured LLM must return structured JSON with explicit limitations. `factual_pointer` may be proposed strong; `interpretation_pointer` may only be weak. In this first increment **absence-pointer challenges are intentionally not admitted**: general claims that an artefact is absent cannot be proved by searching a bounded bundle alone.
5. A provider timeout, malformed JSON, fabricated quotation or unsupported assertion is recorded as a **blocked challenge event**, not a clean result. A clean `[]` means *the model completed and no grounded challenge was validated*, not “the control is effective.” Failed runs require investigation/new cycle rather than silently erasing the original blocked event.
6. `independent_challenged` is a first-class append-only cycle event; the projection also displays it as a challenge envelope. It records verdict hash, source fingerprint, both configured model identities (as available), prompt version, exact pointers, validation status, and required human decision. Decision-time eligibility **rechecks the original challenge event**, the latest assessor verdict and admitted content, as well as the signed policy. A new strong unresolved challenge blocks the routine decision.
7. The existing final human decision through `core/cycle.decide()`, result signing and Quality Gate are unchanged. No shortcut transitions to CURRENT.

**Important:** A strong finding prevents use of the waived routine decision; it does not retroactively delete the signed waiver event, nor does it fabricate a blind read. Escalation requires a governed investigation and, where required, a fresh elevated cycle. Full automatic re-routing/restart is not implemented in this checkpoint.

## Install without overwriting your current workspace

```bash
mkdir -p "$HOME/gaar_wb126_workspace"
unzip -q "$HOME/Downloads/ge_reviewer_copilot_v1_GAAR_WB126_independent_challenge_checkpoint.zip" -d "$HOME/gaar_wb126_workspace"
cd "$HOME/gaar_wb126_workspace/ge_repo"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
source "$HOME/.config/gaar/result-signing.env"
python -m pytest -q tests/test_wb126_independent_challenge.py
python -m compileall -q .
```

Preserve your earlier signing key and **do not copy production governance ledgers into a synthetic acceptance fixture**. An extracted fresh ZIP is not a migration of the durable state from an older workspace. Back up and plan ledger migration explicitly before replacing your running GaaR app.

## Read-only status vs explicit model execution

The following assumes you already have an **actual** WB-124 admission and WB-125 waiver on a real eligible cycle in the selected workspace. Reuse the exact cycle ID returned by the earlier CLIs. Do not invent a prior decided cycle or favorable risk assertions.

```bash
cd "$HOME/gaar_wb126_workspace/ge_repo"
source .venv/bin/activate
source "$HOME/.config/gaar/result-signing.env"
export WB_GAAR_ROUTINE_WAIVER_ENABLED=1
export WB_GAAR_ROUTINE_POLICY_FILE="$HOME/.config/gaar/routine-waiver-policy.json"
export WB_GAAR_EVIDENCE_BLOB_ROOT="$PWD/governance/evidence_blobs"
python tools/independent_challenge_run.py --cycle 'YOUR_REAL_CYCLE_ID'    # read-only
```

To run the model and append one challenge event **only on a real eligible cycle**:

```bash
export WB_GAAR_INDEPENDENT_CHALLENGE_ENABLED=1
export WB_MODEL_CHALLENGE=llama3.2:latest   # only if installed; `ollama list`
python tools/independent_challenge_run.py --cycle 'YOUR_REAL_CYCLE_ID' --run
python tools/independent_challenge_run.py --cycle 'YOUR_REAL_CYCLE_ID'  # read-only verification
```

The Conductor's `run_to_checkpoint()` will run the independent challenger automatically only if `WB_GAAR_INDEPENDENT_CHALLENGE_ENABLED=1` **and** a signed waived cycle reaches `CHALLENGE_REQUIRED`. On an admitted clean response it advances to `HUMAN_DECISION`, never AI-owned approval. A blocked/strong result yields an exception, not CURRENT. No source discovery/admission happens from this CLI.

**Mac-live test not run here:** I cannot access your local Ollama, signing identity, regulatory network or persistent ledgers. The dedicated tests use fake LLM responses and disposable CAS files; they verify isolation and failure behavior, not the real model's audit judgment quality. Run live only after WB-124 admission, signed policy and actual cycle state are established. Never tamper with real CAS; the corruption test uses `tmp_path` only.

## Open full-STP items

- Authenticated policy approver/admission requester identity and production RBAC.
- Evidence-grounded challenge quality evaluation across representative control cases and model routing telemetry; prompt separation does not make two models statistically independent.
- UI presentation and a supported governed investigation/repair transition for strong findings.
- One-click/batch human decision wired through the existing signed result + final Quality Gate without bypass.
- Mac-live validation with actual admitted organisational evidence and model provider.
- Global Watcher source registry/admission quarantine remains a separate project.
