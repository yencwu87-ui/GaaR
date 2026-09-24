# WB-121 — RaaS API + Governance Passport

Status: **LAB-GREEN / PRODUCTION AUTHN-AUTHZ PENDING**

Adds a localhost-first read-oriented RaaS HTTP service and a portable Governance Passport.

Key endpoints:
- `GET /health`
- `GET /v1/results`
- `GET /v1/results/{id}`
- `GET /v1/results/{id}/quality`
- `GET /v1/results/{id}/passport`
- `GET /v1/living`
- `GET /v1/living/{control_id}`
- `GET /v1/autopilot/status`
- `GET /v1/watcher/status`
- `POST /v1/passports/verify`

The Governance Passport packages result state, quality gate, hashes, Merkle root, Ed25519 signature, evidence/result lineage, and human decision provenance with a passport digest. It is a projection over the sealed result and does not mutate governance state.

Validation: 4/4 dedicated tests green.
