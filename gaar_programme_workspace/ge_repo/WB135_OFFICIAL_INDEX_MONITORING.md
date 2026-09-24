# WB-135 — Existing-basis official publication index monitoring

## Operator summary
This is an *opt-in, bounded official HTML publication-index monitor*, not an assertion of full MAS/FCA site or PDF coverage. It does not reimport or overwrite your governance basis. The ISO/IEC 42001 official reference is marked `AWAITING_OPERATOR_DOCUMENT` in `config/governance_basis_status.yaml` and must not be interpreted as missing organisational assessment evidence.

The Watcher Update Centre now has a separate section **Official publication checks · WB-135**. Its table shows source, scope, last check, new publication links, listing-title changes and failures. No source is enabled out of the box. A disabled source displays `NOT_CONFIGURED`, never `UP_TO_DATE`.

## Prepare your own source configuration
Copy `config/official_publication_indexes.yaml` to a local file (recommended outside the repository) and enable only source indexes verified to present useful publication links on your network. Review their `approved_hosts`, `path_prefixes`, `max_items` and intervals; HTML structures may change. Set `WB_GAAR_OFFICIAL_INDEX_CONFIG=/path/to/your-copy.yaml` and `WB_GAAR_OFFICIAL_INDEX_STORE=/path/to/durable-ledger.jsonl`. If `max_items` limits results, any status covers **only those observed links**, not the whole regulator website.

## On-demand status and explicit scan
```
python tools/official_publication_monitor.py status
python tools/official_publication_monitor.py scan --force
```
A disabled source remains disabled even with `--force`. Successful initial scan is `BASELINE_ESTABLISHED`, *not* `UPDATES_AVAILABLE`. Subsequent identical link/title inventories are `UP_TO_DATE`; a newly observed official link or changed listing title is `UPDATES_AVAILABLE`. A listing title change is NOT verified evidence of a changed PDF. Missing links on a paginated/rolling first page are reported as `not_seen_on_current_page`, NOT automatically classified as withdrawn.

Failures (DNS, blocked/challenge pages, 403/429, invalid redirects, missing qualifying links, wrong content-type) are `UNABLE_TO_CHECK`, with last successful inventory retained. `CHECK_OVERDUE` is derived from the last successful scan date, but after failure `UNABLE_TO_CHECK` takes priority. A changed index HTML hash alone is not a changed instrument. Never interpret zero update counts from a failed or disabled source.

## Opt-in hourly macOS launchd
```
python tools/install_official_index_launchd.py --print
python tools/install_official_index_launchd.py --install
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/org.gaar.official-publication-index.plist"
```
This uses your active venv Python absolute path. `StartInterval=3600`, while each source has its own 6-hour due interval by default. Work runs only while macOS can run scheduled jobs; the durable record preserves prior observations. Test install/resume on your actual Mac. Do not enable alongside another instance writing to the same store until locking and deployment paths are reviewed. Disable: `launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/org.gaar.official-publication-index.plist"`.

## Governance boundary
A link on an index is only a discovery candidate. It has *not* been fetched as the complete official PDF, converted, classified as a binding obligation, staged or admitted. Use WB-132 fetch/WB-133 conversion for the actual document and WB-131 ADD→DIFF→signed COMMIT→PUSH for governed impact review. **No automatic ADD, COMMIT, PUSH, result modification or control FAIL is performed here.** No dependency on uploading your previous framework workbooks.

## Honest validation
Local fixture tests cover baseline, repeat, addition, listing title change, 403, empty/challenge page, host validation, redirect rejection, disable, opt-in and overdue. They do NOT show a successful MAS/FCA network retrieval. Run with `python -m pytest -q tests/test_wb135_official_indexes.py`. Do not treat the reference `official_publication_indexes.yaml` as verified live source support until each index returns qualifying links in your environment.
