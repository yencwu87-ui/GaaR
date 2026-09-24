# Governance Results as a Service (GaaR/RaaS) API

The API is a transport over existing governed stores. It does not gain governance authority by being an API.

## Product primitive: Governance Passport
A Governance Passport is the externally portable proof object for one sealed result. It includes:
- result and version identifiers
- current validity state
- human control decision
- quality-gate status
- requirement/evidence/assessment/challenge/human-decision lineage
- SHA-256 content hash
- Merkle root
- Ed25519 signature/public key
- parent/superseded lineage
- passport digest

This allows a customer, auditor, board member, or regulator to inspect the proof package without accessing the internal reviewer workspace.
