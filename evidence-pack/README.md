# GaaR constructed evidence pack — change management

**Constructed test data, not operating evidence.** Every system, person, ticket, hash and event here is invented. The change export carries `"synthetic": true` and `"data_classification": "CONSTRUCTED_TEST_DATA"`, every source id starts with `CONSTRUCTED-`, and the system id is `CONSTRUCTED-payments-api`, so the label follows the data into every test result and trace.

## Contents

- `evidence/` — the only folder the provisioner reads: `changes.json`, `population.json`, `change_policy.md`
- `answer_key_DO_NOT_PROVISION/` — what was planted, what the deterministic tests return, the correct treatment, and a scoring sheet. **Do not read it until you have attested.** Reading it first turns your own review into a check against the key rather than an independent judgment.
- `run_test.sh` — keygen (once), provision into `~/gaar-constructed-test`, verify, open the reviewer app
- `build_pack.py` — regenerates the pack byte-for-byte

## Run

1. Start Ollama with two different model families pulled.
2. `GAAR=/path/to/ge_repo EXAMINE_MODEL=<model> CHALLENGE_MODEL=<different model> bash run_test.sh`
3. Enter the printed token, press **Run**, read the result, open evidence and reasoning, attest.
4. Then open the answer key and fill in `scoring_sheet.json`.

## Keep it separate from a real pilot

The pilot on-ramp marks the investigation context non-synthetic, because it exists for real data. This pack keeps its own synthetic markers in the evidence, but the context flag will still say non-synthetic. Keep this workspace separate and delete it when you're done (`rm -rf ~/gaar-constructed-test`). Don't provision real data into it.
