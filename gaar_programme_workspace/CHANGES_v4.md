# Changes from v3 (GaaR_Evaluation_MVP_Reviewer_Onramp_v3)

Contract kept: `governance/decisions.py` and its seal test, as supplied. The test is `ge_repo/tests/test_decisions.py::test_sign_and_seal` and passes unchanged in substance.

## Added
- `ge_repo/tools/gaar_pilot.py` — pilot on-ramp. `keygen` (outside the package), `provision` (supplied human keys only; six minted service keys; governance-signed internal source and precedent corpus; non-synthetic initial stages; `deployment_profile: pilot`; `separation_of_duties` recorded), `verify`.
- `ge_repo/governance/decisions.py` — supplied contract plus `pilot_preflight`, `attest`, `existing_attestation`, and a panel that seals in production and attests in a pilot.
- `ge_repo/tests/test_decisions.py` — supplied contract test plus six pilot/app tests.
- `ge_repo/conftest.py` — restores the six legacy governance ledgers existing tests write to, and names them.

## Changed
- `governance/production/journal.py` — authorises `pilot_attestation`, signed only by `result_approver`.
- `governance/production/lifecycle.py` — `seal` refuses any approval carrying pilot reliance markers.
- `governance/production/qualification.py` — rejects identical examine/challenge model revisions at different endpoints.
- `governance/trace.py` — optional `sources` argument; per-obligation `source_status`; verified `pilot_attestation` read only from a VALID journal.
- `app_gaar.py` — signing/attestation panel; per-session, per-assessment reveal with access log; source-approval column and fixture warning; profile and single-reviewer banners; `width="stretch"` for the pinned Streamlit.
- `config/programme_operations.json` — `reviewer_ui.reveal_on_request: true`.
- `tools/gaar_console.py` — option P for the pilot on-ramp.
- `tests/test_wb133_instrument_conversion.py` — `importorskip("fitz")`.
- Manuals, status, receipt, verification record, content manifest.
