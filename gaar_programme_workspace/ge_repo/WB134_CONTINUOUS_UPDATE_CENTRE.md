# WB-134 · Publication Update Centre, domain tags and opt-in polling

## What this checkpoint does

The Watcher tab now displays an Update Centre that separates `NOT_CONFIGURED`, `NEVER_CHECKED`, `UP_TO_DATE`, `UPDATES_AVAILABLE`, `UNABLE_TO_CHECK`, and `CHECK_OVERDUE`. `UP_TO_DATE` means the configured **feed or index** returned successfully and no new stageable snapshot was recorded during that poll. It does **not** certify the entire official site or every linked PDF. `UPDATES_AVAILABLE` means new extracted feed/index snapshots were persisted; it does not mean regulatory applicability is confirmed. A failed fetch/validation is `UNABLE_TO_CHECK`, never `UP_TO_DATE`.

The publications table includes *suggested domains* (AI and model governance, cybersecurity and resilience, data privacy, financial crime, outsourcing, consumer protection, capital/reporting, payments/digital assets, governance). These are simple searchable keyword tags, **not** an LLM legal interpretation, obligation or severity verdict. A publication can belong to multiple domains. It is still separately classified by issuer, publication class/normative status and lifecycle at WB-131 human ADD/COMMIT.

No new automatic admission, commit, push, regulatory impact trigger, control verdict or GovernanceResult is added by WB-134.

## Enable in a separate Mac workspace

```bash
mkdir -p "$HOME/gaar_wb134_workspace"
unzip -q "$HOME/Downloads/ge_reviewer_copilot_v1_GAAR_WB134_update_centre_domain_polling.zip" -d "$HOME/gaar_wb134_workspace"
cd "$HOME/gaar_wb134_workspace/ge_repo"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_wb134_updates.py
python tools/watcher_updates.py status
```

All sources in the packaged `config/watcher_sources.yaml` are **disabled**. The MAS source is a static demo, not an official MAS publication-index connector. Do not enable that entry and claim live MAS coverage. The optional CISA KEV JSON connector is a threat source, not a MAS/UK/US regulatory-publication feed. Only enable a connector after validating its official feed URL, coverage, publication metadata, allowlist and response integrity.

Explicit single poll (after configuring an enabled source):

```bash
python tools/watcher_updates.py scan --force
python tools/watcher_updates.py status
```

Opt-in background monitoring on macOS (inspect before activation):

```bash
python tools/install_watcher_launchd.py --print
python tools/install_watcher_launchd.py --install
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/org.gaar.regulatory-watcher.plist"
```

The LaunchAgent runs the configured-feed scanner hourly. Each source's `schedule.interval_minutes` defaults to 360 (threat feeds 60); sources not due are skipped. Minimum interval is 60 minutes. It is not a native Mac test until you execute it on your Mac. To disable:

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/org.gaar.regulatory-watcher.plist"
```

Logs live in `$HOME/.gaar/logs/watcher_scheduler.log` and `watcher_scheduler.error.log`; scan receipts live by default in `governance/watcher_scan_receipts.jsonl` within the selected repository. Configure `WB_GAAR_WATCHER_SCAN_STORE` for a persistent alternate location. Polling resumes after sleep when launchd next runs; a `CHECK_OVERDUE` warning tells operators a schedule was missed. No guarantee of zero missed publications when a feed omits history or source cursor is inconsistent; reconciliation/robust regulator-specific collectors remain future work.

### Honest scope and open risks

- This checkpoint does **not** provide a verified MAS/FCA/PRA/SEC live index connector or continuous regulator-wide coverage. Those real source adapters are a separately required gate.
- RSS/JSON payloads are excerpts/index entries in the existing Watcher; WB-132/133 fetch and PDF-to-TXT conversion still require a complete original document URL and validation. Do not equate an index snapshot with an original regulator-published PDF.
- Existing Watcher cursor comparisons may be inappropriate for feeds ordered inconsistently or documents republished without increasing cursor; per-document ID+hash reconciliation is needed before production coverage claims.
- The LaunchAgent path points to the virtualenv interpreter active **when installed**. If the workspace is moved, regenerate after inspecting the old plist.
- Reviewer names and locally signed commits are not enterprise identity verification.

## Actual isolated verification

`tests/test_wb134_updates.py`: five passed; relevant WB-125/127/129/131/132/133 focused suite: 75 passed total including WB-134; Python compileall passed. Separate static fictional-source CLI rehearsal observed `UPDATES_AVAILABLE` with one snapshot, then `UP_TO_DATE` with zero new snapshots on forced repeat. This was **not** a live MAS retrieval nor an Apple Silicon execution.
