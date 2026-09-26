# Workbench, regulatory watch and control impact (kit v21)

## The workbench: five places, not sixteen tabs

| Place | Sections | Was |
|---|---|---|
| **Today** | the one next step (with a button that goes there), four work queues | Home |
| **Review** | 1 · Add evidence, 2 · Review controls, 3 · Decisions ready | Scan, Review, the sidebar decision queue |
| **Results** | Current results, Impact & root cause, Outcomes, History, Lifecycle | Living Results, Outcomes, History, Lifecycle |
| **Regulatory watch** | Intel feed, Change reviews, Watcher internals | Watcher, Change |
| **Reports** | Readiness report, Audit trail, Measurement | Report, Audit, Measurement |
| **Settings** | General (library, scope, models, reset), AI Auditor, Autopilot, Engine, Operations | the sidebar, AI Auditor, Autopilot, Engine, Operations |

Only the open section runs. The classic tab bodies were moved, not rewritten: each is byte-identical in its syntax
tree to the code it was (checked when the restructure was made), and `tests/test_workbench_navigation.py` pins that
every classic tab has exactly one home. Two slow paths underneath were fixed: the event ledger was re-read once per
cycle (now once per page), and the decision queue re-parsed the Excel playbook once per cycle (now cached on the
workbook's path, time and size; callers get their own copy). A page that took 87 s to render all sixteen tabs now
renders its one section in 0.4–5 s.

## Regulatory watch

A subscribed intel service (`governance/watcher/intel.py`, `tools/gaar_watch.py`). Sources: official publication
indexes and CISA's known-exploited-vulnerabilities feed. Each subscribed source is checked every 8 hours by the
scheduler; a failed check retries after an hour. The first check sets a baseline; only later additions become intel.
Every new item gets a kind (instrument, consultation, threat), a priority, the controls it most likely touches (BM25
over the 195 control contracts), and for consultations an outlook window from a planning assumption the governance
owner sets. Untriaged P1/P2 items are inbox work; new threats arrive as one digest per source. A blocked, empty or
unparseable fetch is UNABLE_TO_CHECK and a system item, never "no updates". State lives in `~/gaar-watch`
(`GAAR_WATCH_HOME`), never in the software folder.

## Control impact and root cause

`governance/impact.py`, the Results › Impact & root cause section, the pilot record's "What these findings imply"
panel, and `tools/gaar_impact.py`. A lapse flags dependent controls (reliance reduced; reliance impaired only through
an approved edge declaring complete reliance, which no catalogue edge is yet), weakening one level per step; peers in
another framework that share a crosswalk capability go on watch. Root cause walks up the dependencies: a lapsed
ancestor with no lapsed ancestor of its own is the likely root cause, an unassessed one is "test next", an effective
one is ruled out on that path, and an ancestor shared by several lapses is a likely common cause. Deterministic
finding codes are evidence: SELF_APPROVAL points at change approval, FREEZE_WITHOUT_PRIOR_EXCEPTION at the freeze
process. Nothing changes a control's recorded status; every flag names the corroboration it needs.

## Defect D19

Kits up to v20 shipped the workbench's runtime stores, including `governance/events.jsonl`, the append-only decision
ledger; `unzip -o` overwrote the reviewer's ledger, watch history and dossiers with the builder's copies.
`tools/build_kit.py` builds kits without runtime state, and `tests/test_kit_hygiene.py` fails if any comes back.

## Local OCR

Scanned (image-only) PDF pages used to extract as nothing, silently. `governance/ocr.py` reads the text layer as
before (so verbatim anchors still match) and sends only image-only pages to a local engine: macOS Vision (`ocrmac`),
PaddleOCR (Baidu's open-source engine, run locally) or Tesseract. With none installed, the page is marked "image-only,
not extracted". Hosted OCR, including Baidu's cloud API, is not wired in: evidence would leave the institution, and its
free tier is quota-limited rather than unlimited.
