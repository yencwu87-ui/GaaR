# WB-133: Regulator intake → versioned instrument TXT

## What changed

WB-132 fetches original PDF/HTML into quarantine. WB-133 adds `--convert-txt` and a separate `tools/instrument_convert.py` for extracting searchable, page-marked TXT into `instruments/regulatory/<REGULATOR>/<INSTRUMENT-ID>/<original-sha256>.txt` plus `<sha256>.conversion.json`. The PDF/HTML stays in its original content-addressed intake location. This operation **does not** approve, commit, push, bind to a review, classify a document's legal status, or modify an existing instrument manifest.

## Important: live retrieval cannot be guaranteed from a simulated Mac

Our execution environment is Linux x86_64, not macOS/Apple Silicon, and direct connections to MAS/FCA still return `Temporary failure in name resolution`. Unit tests and a bundled real-document PDF conversion can prove parser/integrity behavior but **cannot validate DNS, TLS, proxy, CAPTCHA handling, regulator uptime, Mac permissions or your network**. The Mac script below is the live acceptance run; it must run on your Mac and report actual outcome. On blocked sources, do not disguise an operator-supplied download as live fetch.

**Document lifecycle warning:** MAS Notice PSN05's February 2024 historical text must not be marked currently binding: MAS issued a cancellation notice dated 9 May 2024 effective 10 May 2024. Verify current instruments and applicability before COMMIT/PUSH. A successful download or TXT conversion proves neither legal currency nor scope.

## Install alongside your existing workspace

```bash
mkdir -p "$HOME/gaar_wb133_workspace"
unzip -q "$HOME/Downloads/ge_reviewer_copilot_v1_GAAR_WB133_intake_to_instrument_txt.zip" -d "$HOME/gaar_wb133_workspace"
cd "$HOME/gaar_wb133_workspace/ge_repo"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_wb133_instrument_conversion.py tests/test_wb132_regulator_fetch.py
```

## A. Mac-live MAS PSN05: exact original PDF → TXT

```bash
cd "$HOME/gaar_wb133_workspace/ge_repo"
source .venv/bin/activate
python tools/regulator_fetch.py \
  --regulator MAS \
  --url 'https://www.mas.gov.sg/-/media/mas-media-library/regulation/notices/trpd/psn05/psn05-technology-risk-management-notice---6-feb-2024.pdf' \
  --output "$HOME/gaar_regulator_intake" \
  --convert-txt --instrument-id MAS-PSN05 \
  --instrument-title 'PSN05 Technology Risk Management — HISTORICAL, review cancellation'
```

Success produces `state=QUARANTINED_FOR_HUMAN_REVIEW` with `text_derivative.status=EXTRACTED_FOR_REVIEW`, and a path under `instruments/regulatory/MAS/MAS-PSN05/<original-hash>.txt`. Original PDFs stay under `$HOME/gaar_regulator_intake/<original-hash>.pdf`. If you want all generated TXT under a separate private instruments directory, add `--instruments "$HOME/gaar_instruments"`.

## B. Mac-live FCA PS24/4

```bash
python tools/regulator_fetch.py --regulator FCA \
 --url 'https://www.fca.org.uk/publication/policy/ps24-4.pdf' \
 --output "$HOME/gaar_regulator_intake" \
 --convert-txt --instrument-id FCA-PS24-4 \
 --instrument-title 'Policy Statement PS24/4: Rules relating to Securitisation'
```

Note: this historical FCA securitisation document is not automatically applicable to an AI governance assessment.

## C. Offline existing PDF fallback (NOT live-retrieval acceptance)

If the regulator blocks automatic access and you have a legitimately obtained PDF, use the operator-supplied intake. This creates a separate `*.offline.receipt.json` with `live_retrieval_verified=false`:

```bash
python tools/instrument_convert.py \
 --local-pdf '/absolute/path/to/document.pdf' \
 --regulator MAS \
 --official-url 'https://www.mas.gov.sg/-/media/mas-media-library/regulation/notices/trpd/psn05/psn05-technology-risk-management-notice---6-feb-2024.pdf' \
 --id MAS-PSN05 --title 'Historical PSN05 — verify scope and cancellation' \
 --intake "$HOME/gaar_regulator_intake" \
 --instruments "$HOME/gaar_instruments"
```

**Do not supply an invented source URL or claim this proves official retrieval.** Independently verify the operator-supplied PDF came from the named official publication. An operator-supplied URL is an attestation, not cryptographic evidence of where the bytes came from.

To convert a previously fetched receipt:

```bash
python tools/instrument_convert.py \
 --receipt "$HOME/gaar_regulator_intake/<ACTUAL_SHA256>.receipt.json" \
 --id MAS-PSN05 --title 'Historical PSN05 — verify cancellation'
```

## Verify your artifacts

```bash
find "$HOME/gaar_regulator_intake" -maxdepth 1 -name '*.receipt.json' -print
find instruments/regulatory -name '*.txt' -print
# Compare the source_sha256 in <hash>.conversion.json to shasum -a 256 on the corresponding original PDF.
```

Read the TXT page headings `===== SOURCE PAGE N =====`. They are searchable derivatives, not legally authoritative facsimiles. PDF images, tables and scanned pages can need visual review. Fully image-only PDFs fail closed with `TEXT_EXTRACTION_INCOMPLETE`; OCR is not silently applied. Original document + receipt remain necessary for citation and signing.

## No Git COMMIT/PUSH from conversion

After independently reviewing source, status, metadata and classification, use WB-131's existing ADD/DIFF/COMMIT/PUSH workflow. If the document is a historical cancelled notice or consultation, it must not become a current binding obligation by default. No private signing key is included in this package.
