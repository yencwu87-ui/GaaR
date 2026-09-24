# GaaR integrated programme candidate — WB143–WB149 (pilot MVP revision)

This complete package extends WB142 with one resumable investigation runner, active dependency treatment, full-contract evaluation, additional change checks, signed result lifecycle, local remediation records, and recovery/security checks.

**This is an engineering candidate. WB143–WB149 production acceptance is not complete.** No live model, real operating evidence, approved production identity store, independent judgment labels, or macOS acceptance environment was available for this build. Do not interpret software test results as auditor superiority or compliance certification.

1. Extract into a NEW folder. Keep WB136/WB142 and their records intact.
2. Open the outer **Start_GaaR.command**. If needed, open Terminal, type `bash `, drag that file into Terminal, and press Enter.
3. Choose **1** to check prerequisites; **2** to save your existing approved configuration and assessment ID.
4. Choose **9** for the reviewer front door: select system → assessment → **Run / resume**. Or choose **3** to run the saved assessment in the console.
5. Read the result or precise missing-evidence/authorization request. Select Run again after resolving a recoverable boundary. Machine stages do not need manual file transfers or head updates.

Python 3 is required. Initial dependency installation needs internet access. The launcher does not download a model or manufacture trust identities. Default configuration is unconfigured and evaluation-only.

Open **MANUAL.html** for operation, implementation, evaluation, and acceptance details. **PROGRAMME_STATUS.json** is the machine-readable status. Test reports are in `ge_repo/verification/wb143_149/`.

For a 90-second synthetic evaluation on-ramp, use `tools/gaar_provision.py --help`. It generates separate service keys, hashes and whole-file UTF-8 evidence offsets, then creates the first two signed stages. It refuses production mode and marks the investigation synthetic.

For a pilot on real exports, use `tools/gaar_pilot.py` (console option **P**). Each person first runs `keygen --out <path they control, outside this package>`. `provision` then accepts those owner, governance and approver keys, never creates or copies a human key, mints only service keys, has the governance person sign the internal policy source and precedent corpus, and creates a non-synthetic investigation. A pilot ends in a signed **pilot attestation** made in the reviewer app: decision support bound to the exact record, recorded in the operational journal, and refused by result sealing. It is not a governance result.

Production cannot be switched on by changing a flag: qualification, source authority, evidence scope, policies and signatures are checked. Deployment remains unauthorized in this candidate, including for finalized adverse results.
