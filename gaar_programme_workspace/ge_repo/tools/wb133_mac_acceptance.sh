#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"
echo "SYSTEM: $(uname -srm)"
if [ "$(uname -s)" != Darwin ]; then
  echo 'NOTE: This is not Mac-live validation (macOS required); running portable tests only.'
fi
"$PYTHON" -m pytest -q tests/test_wb133_instrument_conversion.py tests/test_wb132_regulator_fetch.py
"$PYTHON" -m compileall -q governance/watcher tools/regulator_fetch.py tools/instrument_convert.py
if [ "${WB133_RUN_LIVE_FETCH:-0}" != 1 ]; then
 echo 'LIVE_FETCH: NOT RUN; set WB133_RUN_LIVE_FETCH=1 explicitly to test official MAS/FCA.'
 exit 0
fi
"$PYTHON" tools/regulator_fetch.py --regulator MAS \
 --url 'https://www.mas.gov.sg/-/media/mas-media-library/regulation/notices/trpd/psn05/psn05-technology-risk-management-notice---6-feb-2024.pdf' \
 --output "$HOME/gaar_regulator_intake" --convert-txt \
 --instrument-id MAS-PSN05 --instrument-title 'Historical PSN05 — cancelled 2024; review scope'
"$PYTHON" tools/regulator_fetch.py --regulator FCA \
 --url 'https://www.fca.org.uk/publication/policy/ps24-4.pdf' \
 --output "$HOME/gaar_regulator_intake" --convert-txt \
 --instrument-id FCA-PS24-4 --instrument-title 'FCA PS24/4 Securitisation'
echo 'LIVE_FETCH: both official URLs fetched and TXT derivatives created; review receipts and classification.'
