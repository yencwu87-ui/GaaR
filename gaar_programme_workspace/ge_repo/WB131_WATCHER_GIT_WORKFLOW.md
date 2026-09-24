# WB-131 — Watcher Regulatory Git: ADD → DIFF → COMMIT → PUSH

## One-screen explanation

The Watcher **discovers** candidate regulatory publications, standards, research and
threats. It does **not** decide that a new law applies to your company. An operator
then **ADDs** a specific source version to an assessment staging area, checks its
**DIFF**, **COMMITs** an explicit human-reviewed classification and control mapping,
and **PUSHes** the signed relationship to the assessment-impact-review queue.

| Action | Actual effect | Does NOT do |
|---|---|---|
| SCAN | fetch source item, retain connector-extracted bytes in local SHA-256 CAS, record candidate/health | create binding obligation or CURRENT result |
| ADD | validate domain + metadata, snapshot original input, append `PROPOSED_ONLY` stage | admit an organisational evidence set |
| DIFF | show changed text against previous committed source version (binary/PDF: metadata-only notice) | claim semantic/legal interpretation is verified |
| COMMIT | append Ed25519-signed version + human attribution + rationale | authenticate the human with SSO/IAM |
| PUSH | append immutable assessment relationship; eligible law/rule/guidance emits typed **impact-review request** | change requirement contract or publish a result |

**Do not use Watcher commits as a replacement for WB-124 organisational Evidence Admission.**
The regulatory-reference linkage and the operational evidence binding are different.

## Mac install

Download the WB-131 full-repo ZIP. Preserve your WB-129 workspace and its ledgers.

```bash
mkdir -p "$HOME/gaar_wb131_workspace"
unzip -q "$HOME/Downloads/ge_reviewer_copilot_v1_GAAR_WB131_watcher_git_checkpoint.zip" -d "$HOME/gaar_wb131_workspace"
cd "$HOME/gaar_wb131_workspace/ge_repo"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
source "$HOME/.config/gaar/result-signing.env"
python -m pytest -q tests/test_wb131_watcher_gitflow.py tests/test_wb119_watcher.py tests/test_wb119_integration.py
./start_ui.sh --server.address 127.0.0.1 --server.port 8503
```

Open http://127.0.0.1:8503 → **Watcher → Regulatory Git workspace**.
Port 8503 lets you compare with existing 8501/8502. A fresh repo starts with its
own durable ledgers; the old Mac live ledger is NOT magically imported.

## Actual CLI contract

Run `python tools/watcher_git.py --help` and the subcommand `--help` for all options.
The example below assumes you deliberately enabled a vetted `official` source
with `filters.approved_domains: [www.mas.gov.sg]` in `config/watcher_sources.yaml`.
No new MAS/FCA live connector is shipped in this checkpoint: **do not turn a
catalogue entry into an enabled source without connector validation.**

For a new record from `python tools/watcher_probe.py --run`, use its
`source_snapshot_id` from the Watcher UI or `watcher_emissions.jsonl`:

```bash
python tools/watcher_git.py add \
  --snapshot-id "WS-ACTUAL_ID" \
  --issuer MAS --document-class regulatory_guidance --lifecycle effective \
  --landing-url 'https://www.mas.gov.sg/regulation' \
  --assessment ASM-ACTUAL_ID --framework MAS --control M3.6 \
  --actor 'Your Name' --reason 'Potential change to this control' \
  --attestation 'I checked the source landing page and document type/version'

python tools/watcher_git.py diff "WST-ACTUAL_ID"
python tools/watcher_git.py commit "WST-ACTUAL_ID" \
  --reviewer 'Your Name' --note 'I reviewed origin, version, lifecycle and applicability'
python tools/watcher_git.py verify "WCM-ACTUAL_ID"
python tools/watcher_git.py push "WCM-ACTUAL_ID"
python tools/watcher_git.py status
```

For a manually downloaded HTML/PDF use `add --file /path/to/source.pdf` and provide
`--source-id`, `--document-id`, `--source-url`, `--title`, `--published-at` as well as
all other mandatory metadata above. **Local file/imported URL origin is human
attested, not proof that GaaR downloaded the file from an official site.**
Use a licensed official copy for ISO/IEC 42001; a standards publisher's landing
page does not grant permission to scrape/paywall-circumvent its full text.

## Watcher workflow safety

- A high-authority regulator domain is only an *authority ceiling*; the individual
  `document_class` sets normative status. `consultation` never emits a regulatory
  obligation trigger; `research`, `standard` and `policy` remain reference links.
- Threat advisories create an exposure-review link, **not** a binding-law trigger.
- Invalid title, non-HTTPS/unapproved official domain, missing publisher/date,
  invalid lifecycle, missing applicability for binding items: ADD blocked.
- No commit without configured Ed25519 key, reviewer attribution and decision note.
  A local name plus a signing key is **not** verified human identity.
- Each commit references the exact SHA-256 content snapshot and its last committed
  version; old assessment links never silently retarget new source versions.
- Push verifies the signed commit against the local trusted key and re-hashes CAS.
  Pending delivery is recoverable by rerunning `push` (idempotent trigger payload).
- The automatic Watcher → Autopilot trigger previously present in WB-119 is **now
  disabled for all new feed discoveries by design**. Impact review is requested
  after explicit signed COMMIT + PUSH only.
- Watcher source scan cursor can advance after durable discovery receipts; this is
  **not** a governance admission cursor. A malformed publication leaves the source
  degraded and stops cursor advancement.
- No signed result, authoritative EvidenceSet, human control verdict, or CURRENT
  state is created by ADD, COMMIT or PUSH.

## What is still open

The global reference catalogue `config/global_watcher_catalogue.yaml` is **not live
coverage**. MAS/FCA/PRA/UK legislation and other source-specific collectors need
parsing, API/HTML/PDF authenticity checks, rate-limit/retry and uptime validation.
Current feeder snapshots contain the connector's extracted text or feed excerpt;
they do **not** assert retention of a whole linked regulator PDF. A manually
provided PDF is retained as its exact bytes but independently authenticated
retrieval is not yet implemented. Runtime IAM/OIDC review identity, multi-tenant
permissions, policy-controlled push, publisher signatures, remote Git hosting,
and actual control-requirement contract revision are future work.

Do not claim production-ready global regulatory monitoring from this checkpoint.

## Demonstrate the exact flow without touching your live ledgers

```bash
python tools/watcher_git_demo.py
```

The demo creates an ephemeral **fictional** source, runs the actual CLI's ADD,
DIFF, COMMIT, VERIFY and PUSH operations, and asserts an idempotent retry and
exactly one queued impact-review Autopilot job. It operates entirely in `/tmp`.

An impact-review job being QUEUED does **not** mean a real control was reassessed
or a governance result was issued. The typed trigger still needs the existing
governed impact/reassessment adapter and a running worker. `autopilot_run.py
--claim` only claims queue work; it is not a fully autonomous runner.

For Watcher source health, a successful fetch of zero items is **not proof of
complete coverage**. The Watcher UI separately shows `NOT_RUN`, `DEGRADED`,
`ERROR`, and a derived `STALE` when the last successful scan is older than the
configured `max_staleness_hours` (48 hours by default). Invalid fetched records
are quarantined and do not advance the source's discovery cursor.

## Lab verification scope

The focused WB-119/124–127/129/131 integration set passed 98 tests in the
assistant's isolated Python environment; compileall and the synthetic CLI
rehearsal passed. The exploratory all-tests run exceeded the execution-time
budget and is **not** claimed as a full-suite pass. No code or source was tested
against your Mac, MAS or UK regulator servers in this build.
