# WB-119 — Regulatory Watcher Agent

Status: **LAB-GREEN / LIVE-SOURCE ACCEPTANCE PENDING**

Adds a persistent Regulatory Watcher Agent with governed source configuration, HTTP/JSON/RSS/static connectors, cursor persistence, content-hash deduplication, circuit breaker behavior, append-only emission/health/cursor stores, and a Streamlit Watcher surface.

Authority is never inferred from document prose. Only sources explicitly configured as governance-impact eligible may emit a governance-change trigger. Background sources are recorded as background-only and cannot trigger `REVIEW_REQUIRED`.

Validation: dedicated watcher/integration suite 14/14 green; included in the 125-test RC critical regression.
