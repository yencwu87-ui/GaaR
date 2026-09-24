# WB-122 — Release Readiness + Deterministic Demo

Status: **LAB-GREEN**

Adds `tools/release_probe.py` for append-only ledger/config/safe-bind validation and `tools/demo_offline_story.py` for a deterministic offline product story from authoritative source -> Watcher -> change trigger -> Autopilot queue.

The API is localhost-only by default. A non-local bind fails release readiness unless `WB_GAAR_API_KEY` is set.

Validation: 2/2 dedicated tests green. Combined RC critical suite: 125/125 green; compileall green.
