# WB-132: Official-document quarantine intake (MAS/FCA)

## What is implemented

An on-demand exact-URL fetcher with strict MAS/FCA official-host allowlists,
original HTTP PDF bytes (never a browser-generated `page.pdf()`), immutable-name
local snapshots, SHA-256, optional JS-rendered *link discovery* with Playwright,
explicit human-supplied document metadata and optional ADD to the WB-131 Git
workspace. Fetching does not COMMIT, PUSH, classify legal effect, or poll a feed.
The original byte stream of a browser landing response may differ from the
JS-rendered DOM used to discover links; both are clearly distinguished.

The fetcher fails closed on DNS failure, challenge pages, ambiguous PDF links,
redirects off allowlisted hosts, oversized responses and malformed payloads.
It does **not** attempt CAPTCHA/Turnstile evasion or import browser credentials.
A fetch receipt is a retrieval record, not independent proof of legal effect.

## Install

```bash
cd "$HOME/gaar_wb132_workspace/ge_repo"
source .venv/bin/activate
python -m pytest -q tests/test_wb132_regulator_fetch.py
# Optional, ONLY for JS-rendered landing-page discovery:
python -m pip install playwright
python -m playwright install chromium
```

## One official MAS notice (on-demand)

```bash
python tools/regulator_fetch.py --regulator MAS \
  --url 'https://www.mas.gov.sg/-/media/mas-media-library/regulation/notices/trpd/psn05/psn05-technology-risk-management-notice---6-feb-2024.pdf' \
  --output "$HOME/gaar_regulator_intake"
```

## One official FCA policy statement (on-demand)

```bash
python tools/regulator_fetch.py --regulator FCA \
  --landing 'https://www.fca.org.uk/publications/policy-statements/ps24-4-rules-relating-securitisation' \
  --pdf-match 'ps24-4.pdf' --output "$HOME/gaar_regulator_intake"
```

Add `--browser` only if JS rendering is required for link discovery; PDF content
is still downloaded via ordinary HTTP response bytes. For exact PDF documents
prefer `--url` and skip the browser altogether.

## Optional stage (not commit/push)

Review the official document, issuer, applicable population, date and class first.
Use `config/regulator_intake_sources.example.yaml` as a reviewed local source
registry (no automatic feed enabled). Add to the MAS notice command:

```bash
  --stage --config config/regulator_intake_sources.example.yaml \
  --stage-source-id mas-manual-official-intake \
  --stage-document-id MAS-PSN05 --stage-title 'MAS Notice PSN05 (revised 6 Feb 2024)' \
  --stage-published-at 2024-02-06 --stage-document-class binding_rule \
  --stage-lifecycle amended --stage-assessment ASM-YOUR-ASSESSMENT \
  --stage-framework MAS --stage-control YOUR-CONTROL-ID \
  --stage-actor 'Your name (local attribution only)' \
  --stage-reason 'Review proposed mapping before commit' \
  --stage-attestation 'I verified the official landing document and scope'
```

Note: date is a human-checked revision date; the document's original issue date
may differ. `binding_rule` is an operator proposal, not the fetcher's assertion.

Once staged, follow the existing `tools/watcher_git.py diff/commit/verify/push`
workflow and **independently verify applicability**. PUSH can queue an impact
review, not an approved control change or Governance Result. To avoid a false
positive impact trigger, do not stage historical unrelated documents against
live assessments.

## Evidence and limitations

- Network access to regulator domains failed with DNS resolution errors in the
  execution container; this build has **not** passed live MAS/FCA ingestion.
- No continuous scheduling, crawler, cursor, or production auth; global catalogue
  records on-demand-intake capability, NOT live monitoring.
- No claim that Playwright bypasses anti-bot controls. If challenged, report
  DEGRADED and use an approved manual-download route with origin attestation.
- Do not share the private signing key or include it in test ZIPs.
