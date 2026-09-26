# Field agents: GaaR Part 2 (kit v24)

## The change

Part 1 waits for evidence: each tower exports files by hand into the series inbox, and the pilot assesses what
arrives. Part 2 sends agents into the environment to gather the evidence themselves, from the systems that hold it:
the deployment history, the change tickets, the privilege grants, an independent audit log. The tower's job moves from
"send the files every week" to "approve once what the agents may read, and fix access when a read fails".

Nothing downstream changes. The agents deliver the same two exports into the same inbox. The series, reconciliation,
journal, inbox, attestation, gate status and frozen packs run exactly as they do on hand-delivered evidence.

## How it works

```
 tower systems (read-only)          field agents (inside the bank)                    GaaR core (unchanged)
 ────────────────────────           ───────────────────────────────                   ─────────────────────
 git deploy repo     ─┐             mandate gate ── approved, hash-pinned?            series inbox
 ITSM exports        ─┤  connector  ─► read ─► map to contract ─► build ─► deliver ─► reconciliation
 IAM grant report    ─┤  receipts            (rows not mapped = gap)   (nothing       journal ─► inbox
 host / cloud audit  ─┘                                                  partial)     reviewer signs
                                    gaps ─────────────────────────────────────────►  tower owner's inbox item
```

- **Collection mandate** (`<series root>/field/mandate.yaml`). Names the series, the owning tower, and each
  source: its connector, its role in the evidence, how its columns map to the evidence contract, and, for a credential,
  the name of the environment variable that holds it. A named person approves it (`tools/gaar_field.py approve`),
  which pins its SHA-256. One changed byte stops the agents until it is approved again. It lives outside the signed
  series configuration, so approving it is never configuration drift.
- **Connectors** (`governance/field/connectors.py`), all read-only:
  - `git`: `git log` on a deploy repository clone;
  - `table`: a CSV or JSON export a system writes on schedule;
  - `http_json`: one bounded HTTPS GET to an approved host, with no redirects, a 20 MB cap, and a token from a named
    variable.

  Each read returns a receipt: what was asked, when, by which connector version, and the hash of exactly what came back.
- **Builder** (`governance/field/builder.py`). Maps rows declaratively, filters to the period, and assembles
  `changes.json` and `population.json`. The primary population comes from the change source and the independent
  population from a different system. It delivers atomically, writes `collection_receipts.json` beside the exports,
  and records the delivery in a hash chain (`field/collections.jsonl`).
- **Scheduler job `field`**. Runs before `series`, so a period collected in a tick is assessed in the same tick.

## Rules (each one is tested)

| Rule | Why |
|---|---|
| Agents read only the sources an approved, unchanged mandate names | A model or a script cannot choose where to look |
| No connector writes; no redirects are followed; credentials only by variable name | Least privilege; a mandate file never holds a secret |
| Nothing is collected before the period has ended plus settle time | A complete export before then asserts what cannot yet be true (D14) |
| A source that cannot be read, or a row that cannot be mapped, is a gap; nothing partial is delivered | "Could not read" must never look like "nothing happened" |
| Gaps go to the tower owner's inbox; the agents retry every tick | Humans handle exceptions, not routine uploads |
| Delivered evidence is never replaced | Evidence is immutable once assessed |
| The independent population must be read from a different system | Otherwise it corroborates nothing |
| Models never produce evidence content | Every delivered record is a mapped row of a source read, with a receipt |

## Demonstrated

`tools/gaar_field.py demo-env` writes a constructed bank environment from the digital twin: a real git deploy
repository (one dated commit per change, with trailers), ITSM and IAM CSV exports, and a host audit log. Then:

- the mandate is approved and the scheduler ticks;
- the agents collect, build and deliver every ended period, and the series assesses them;
- the sealed answer keys score the result.

Sandbox (6 weeks): 13 of 13 planted violations found, 0 false positives. The 2 identity collisions went undetected
(limit L1), which is exactly why Phase B requires unique actor IDs from real sources.

## Plan

| Phase | Scope | Exit criterion |
|---|---|---|
| **A: built (v24)** | Mandate, three read-only connectors, builder, scheduler job, gaps to owner, constructed environment, twin scoring | A constructed series is collected and scored end to end with no hand-delivered file |
| **B: real sources, one tower** | Adapters for the payments tower's actual systems, e.g. a GitHub/GitLab deployments API (changes), ServiceNow change API (tickets), Okta/Entra grant report (privilege), CloudTrail/Azure Activity log (independent). Unique actor IDs end to end (L1). Mandates signed with owner and governance keys, like the standing authorisation | Four real weekly periods collected with zero hand-delivered files and every gap resolved by the owner through the inbox |
| **C: run inside the bank** | The runner packaged for the bank's environment (container or a managed host), credentials from its vault through environment variables, egress allowlist per mandate, one mandate per tower | A second tower onboarded without code changes, only a mandate |
| **D: more controls, agent help** | Connectors and contracts for access reviews, backup and restore evidence, model validation logs. An evidence-planner model that drafts a mandate and field maps from a sample export, for a person to approve; it never collects | Three controls collected continuously; every mandate drafted by the planner approved by a named person |

The model's place stays the same throughout: it may propose, and it is measured in the arena before it advises. The
deterministic connectors read, a person approves, and the signed record decides.
