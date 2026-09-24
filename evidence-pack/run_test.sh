#!/usr/bin/env bash
# Provision the CONSTRUCTED test pack as a throwaway pilot workspace.
# Usage: GAAR=/path/to/gaar_programme_workspace/ge_repo bash run_test.sh
# Edit the two model names first. Examine and challenge should be different families.
set -euo pipefail
GAAR="${GAAR:?set GAAR to your ge_repo folder}"
PACK="$(cd "$(dirname "$0")" && pwd)"
EXAMINE_MODEL="${EXAMINE_MODEL:-qwen2.5:14b}"
CHALLENGE_MODEL="${CHALLENGE_MODEL:-llama3.1:8b}"
KEYS="$HOME/.gaar-test-keys"
WORK="$HOME/gaar-constructed-test"
PY="$GAAR/.venv/bin/python"; [ -x "$PY" ] || PY=python3

[ -f "$KEYS/owner.key" ]    || "$PY" "$GAAR/tools/gaar_pilot.py" keygen --out "$KEYS/owner.key"
[ -f "$KEYS/reviewer.key" ] || "$PY" "$GAAR/tools/gaar_pilot.py" keygen --out "$KEYS/reviewer.key"

"$PY" "$GAAR/tools/gaar_pilot.py" provision \
  --output-config "$WORK/operations.json" \
  --investigation-id CHG-TEST-001 --confirm CHG-TEST-001 \
  --system-id CONSTRUCTED-payments-api --version 4.x --period "2026-09-15T00:00:00+08:00" \
  --framework INTERNAL --control CHANGE.MGMT --requirement-version constructed-cm-v1 \
  --policy "$PACK/evidence/change_policy.md" --policy-version v1 \
  --element "chg.1=Every production change is approved before execution by an authorised approver who is not its implementer" \
  --element "chg.2=Every production change is executed as approved: window, targets, actions, implementer, credential, artefact and a valid privilege grant" \
  --element "chg.3=Changes inside a freeze have a prior approved exception, and failed changes have a recorded approved recovery" \
  --element "chg.4=The change record is complete against an independent record of production changes" \
  --evidence CHANGES="$PACK/evidence/changes.json" --evidence POPULATION="$PACK/evidence/population.json" \
  --owner-key "$KEYS/owner.key" --owner-name "Test Owner" \
  --governance-key "$KEYS/owner.key" --governance-name "Test Owner" \
  --approver-key "$KEYS/reviewer.key" --approver-name "Test Reviewer" \
  --examine-model "$EXAMINE_MODEL" --explain-model "$EXAMINE_MODEL" --plan-model "$EXAMINE_MODEL" \
  --challenge-model "$CHALLENGE_MODEL"

"$PY" "$GAAR/tools/gaar_pilot.py" verify --config "$WORK/operations.json" || true
export GAAR_REVIEWER_TOKEN="$(openssl rand -hex 16)"
echo; echo "Reviewer token: $GAAR_REVIEWER_TOKEN"
echo "Do NOT open answer_key_DO_NOT_PROVISION until you have attested."
cd "$GAAR" && WB_INVESTIGATION_CONFIG="$WORK/operations.json" "$PY" -m streamlit run app_gaar.py --server.address 127.0.0.1 --server.port 8502
