# WB-136 — HKMA / NFRA Asia Watcher + Bilingual Review

## Purpose
Extend the existing WB-135 official-index monitor to Hong Kong and mainland China without changing the existing governance basis or allowing machine translation to become authoritative regulatory text.

## New capabilities

- HKMA Banking Regulatory Document Repository (BRDR) opt-in index configuration.
- NFRA opt-in Rules/Regulations index configuration and conservative Chinese-policy parser.
- Publication metadata suggestions: authority, jurisdiction, category, language, lifecycle and governance-domain suggestions.
- Regulator fetch allowlist extended to HKMA and NFRA official hosts.
- WB-133 TXT conversion supports HKMA/NFRA quarantined originals.
- Chinese TXT -> bilingual review derivative using an explicit local Ollama or Colibri call.
- Original Chinese TXT is never modified. Translation output is versioned under the source TXT SHA-256.
- Translation output declares `translation_authoritative=false`, `human_verification_required=true`, and `auto_add/auto_commit/auto_push=false`.

## Important boundaries

1. HKMA/NFRA monitors are disabled by default until validated on the operator network.
2. An index scan is bounded to the configured listing page; it is not regulator-wide completeness proof.
3. Publication category/domain tags are review suggestions. They are not legal opinions or signed classifications.
4. NFRA Chinese originals remain primary. English machine translation is a review aid only.
5. No discovery or translation operation writes to assessments, controls, Governance Results, COMMIT or PUSH state.

## Live read-only probes

```bash
python tools/asia_source_probe.py --authority HKMA
python tools/asia_source_probe.py --authority NFRA
```

A failed network request returns `UNABLE_TO_CHECK`; it must never be displayed as `UP_TO_DATE`.

## Enable an index after live validation

Edit `config/official_publication_indexes.yaml` and set the desired source `enabled: true`, then:

```bash
export WB_GAAR_OFFICIAL_INDEX_ENABLED=1
python tools/watcher_official_indexes.py scan --force
```

Use `python tools/watcher_official_indexes.py --help` if your checkpoint CLI syntax differs; do not invent flags.

## Fetch an exact official document

```bash
python tools/regulator_fetch.py \
  --regulator HKMA \
  --url 'https://brdr.hkma.gov.hk/...' \
  --output "$HOME/gaar_regulator_intake/HKMA"
```

For NFRA use an exact HTTPS URL under `www.nfra.gov.cn`, `nfra.gov.cn` or `big5.nfra.gov.cn`.

## Chinese translation

After the original has been quarantined and converted with WB-133 to TXT:

```bash
python tools/bilingual_translate.py \
  --source 'instruments/regulatory/NFRA/<instrument>/<sha>.txt' \
  --authority NFRA \
  --id '<instrument-id>' \
  --provider colibri
```

or:

```bash
python tools/bilingual_translate.py \
  --source 'instruments/regulatory/NFRA/<instrument>/<sha>.txt' \
  --authority NFRA \
  --id '<instrument-id>' \
  --provider ollama
```

The output is placed under:

```text
instruments/bilingual/NFRA/<instrument-id>/<source-text-sha256>/
  instrument.bilingual.json
  instrument.bilingual.md
```

The JSON stores each Chinese segment and its English review translation plus source-page anchors where WB-133 page markers are present.

## Lab validation performed

- `tests/test_wb136_asia_bilingual.py`: 8 passed.
- WB-135 + WB-136: 18 passed.
- WB-131/132/133/134/136 focused: 59 passed.
- `python -m compileall -q .`: PASS.
- Direct HKMA/NFRA HTTP probes in this execution environment: DNS resolution failure, therefore live retrieval NOT accepted here.

## Mac acceptance

A source becomes Mac-live only when the read-only probe returns `OK`, an index scan establishes a baseline, a second unchanged scan reports `UP_TO_DATE`, and an exact document can be quarantined with its source hash. For NFRA, translation acceptance additionally requires a local translation run whose bilingual output can be traced to the unchanged Chinese TXT hash.
