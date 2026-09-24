# Digital twin, model arena, requirement basis and wider watch (kit v22)

## Why a twin

There is no real change population to test against. Instead of hand-writing examples, the twin is a **parameterised
generator** (`governance/twin/generator.py`). A constructed bank ("Meranti Bank (constructed)", four systems, named
implementers and approvers) emits a period of changes, tickets, approvals, privilege grants, freezes and incidents,
with violations planted at a chosen rate. Every planted violation goes into an **answer key**, which is sealed (its
sha256 is appended to `commitments.jsonl`) before any check runs. Loading a key that no longer matches its commitment
is refused.

    python tools/gaar_twin.py bench --weeks 1000              detection and false positives over many seeded weeks
    python tools/gaar_twin.py inbox --config <series.yaml>    feed a constructed demo series through the real pilot
    python tools/gaar_twin.py score --config <series.yaml>    compare the journal's findings with the sealed keys
    python tools/gaar_twin.py adjudication                    key/check disagreements, how each was settled, by whom

**What the numbers mean.** 1,000-week bench (seeds 0–999): 2,440 of 2,440 planted violations detected, covering
2,450 required codes (10 of them incidental; see A-001), with 0 false positives, in about 0.6 s. That proves
**robustness across randomised placement, count and form of twelve self-authored violation classes.** It does not
show coverage of novel classes, which external packs own, and it is not independent ground truth. Any figure quoted
from the twin carries this scope. The known-blind class is reported beside it, never inside it: IDENTITY_COLLISION
was planted 218 times and detected 0 times (limit L1).

**Provenance of the truth.** The violations were designed by the same authors as the checks. The key is sealed from
the code, not from its authors, so the twin is a regression measure and a load test, never qualification.

**Exit criterion.** The twin stops being the main test bed when a public or partner-supplied change population with
independently labelled exceptions is available and at least 100 labelled cases have been scored. Until then every
report built on twin data says "constructed".

## Adjudication: who settles truth when the key and the checks disagree

`governance/twin/adjudications.yaml`, `governance/twin/adjudication.py`.

| Step | Requirement |
|---|---|
| Discrepancy found | The key and the checks disagree on a change |
| **Read the generated data** | The underlying week, never the check's rationale |
| Classify | Exactly one: key error, check error, or generator artifact |
| Fix on the correct side | Only that side; never both sides "to make it match" (enforced when the log loads) |
| Regression case | Every adjudication names a test that fails if the error returns (enforced by a test) |

If disagreements were settled by accepting the checks' verdict, the checks would define the truth and then score
perfectly against it. The benchmark is only non-circular because the week is read instead.

The first two entries come from the first 1,000-week run. With the bench's own seed layout the pre-fix generator gives
13 discrepancies of two kinds. An earlier layout gave 8 (7 plus 1), all of the same two kinds.

- **A-001, key error, fixed in the key.** 10 "95 min late" plants slid into a freeze day. The breach was real, and the
  key had not recorded it. The key now **requires** it as an incidental violation. The first attempt only tolerated it
  (listed it as permitted), which left real violations neither counted nor required; that attempt was replaced. The
  planted change count did not change, and the count of required codes grew by the incidentals.
- **A-002, generator artifact, fixed in the generator; the blind spot is promoted, not fixed away.** Three expired-grant
  plants shared the name `temp.contractor` with another plant whose grant was still valid, so the checks, which resolve
  identity by name, correctly found a valid grant. The expired-grant class now uses unique names, which makes that
  class easier. The collision became its own planted class, IDENTITY_COLLISION, which is known-blind and scored apart
  (limit L1 in docs/quality/defect_register.md, with the collector requirement for unique actor IDs).

Both were read by the build agent and are **awaiting a named person's confirmation**:
`python tools/gaar_twin.py adjudication --confirm A-001 --by "Your Name"`.

## Model arena

`governance/arena/`, `tools/gaar_arena.py`, parameters in `config/arena.yaml`. That file is a governance parameter
file: changing it is a recorded change, and every run stores the values it ran under and their hash.

- **Attempted receipts.** Every contestant answers the same constructed cases, blind, in its own shuffled order.
  Every attempt is a receipt in `~/gaar-arena/arena.jsonl` (a hash chain): the raw answer, parsed answer, timing and
  any error. Scores are computed from these receipts exactly as attempted. Nothing is validated or corrected first; a
  failed call is a HOLD with its error, and it is counted.
- **A missing confidence is a HOLD**, never a pass.
- **Named cost policy** in every leaderboard's machine-readable `cost_policy` block: false assurance 10, false alarm
  1, hold 0.5, ratio 10:1, and the parameter file's hash. Raw precision, recall, false assurances, false alarms and
  holds are always shown beside the weighted cost.
- **Baselines are instruments, not results.** In the standard round, `baseline:rules` is the **calibration
  fixture**: the checks scoring their own twin must be perfect, or the scorer is broken. Never quote it as a finding.
  `baseline:always-supported` is the **cost-function check** and must score worst. If either fixture misreads, the board
  reads SCORER_SUSPECT and seats nobody.
- **Blind-spot round** (`run --blind-spot`) adds the known-blind class. There the rules baseline has false assurances
  by design, and a model *can* beat the rules, for example by noticing two different actor IDs behind one name.
- **Model as judge** (`governance/arena/judge.py`). A judge's verdict never changes a score; the judge is measured
  instead.
  - Each pair is shown twice, in both orders. A judge that flips with the order is judging position: its verdict is
    **discarded and recorded as discarded**. A test proves this mechanism can fail.
  - **No self-judging**: a judge may not judge a battle it is in, or one involving its own model family.
  - A consistent verdict is compared with the truth-derived winner, giving each judge's agreement rate.
- **Egress.** A contestant or judge not on this machine refuses any case that is not constructed. Real evidence never
  leaves.
- **Blind human votes** record the voter and are labelled "governance owner (blind); not an independent labeller".
- **Advisory seat.** Only a non-baseline contestant that meets every numeric threshold over at least 100 cases, on a
  calibrated board, is named. Meeting them on twin cases is necessary, not sufficient.

Contestants:
- `ollama:<model>`
- `colibri` (OpenAI-compatible)
- `mlx:<model>` (`mlx_lm.server`, default `http://127.0.0.1:8080/v1`)
- `openai:<base>|<model>`
- `jev`, which needs `GAAR_JEV_URL`, `GAAR_JEV_MODEL` and `GAAR_JEV_KEY_ENV`. The last is the *name* of the
  variable holding the key, never the key.
- the three `baseline:*` fixtures.

### First run on the Mac (v22 round, 25 Sep 2026)

Standard round, 100 constructed cases, scorer calibrated (rules fixture cost 0; always-authorised cost 5.0, worst).

| Contestant | Cost per case | Precision | Recall | False assurances | Seconds per case (median) |
|---|---|---|---|---|---|
| ollama:qwen2.5:14b | 1.60 | 1.00 | 0.68 | 16 | 6.0 |
| ollama:mistral-nemo:12b | 4.21 | 1.00 | 0.14 | 42 | 8.8 |

No advisory seat. Both models raise no false alarms but say "authorised" about changes that broke the rules, which is
the error the cost policy weights ten times. mistral-nemo repeats its Phase 0 result as a false assurer. Judge test:
llama3.1:8b judged 20 qwen-versus-mistral battles; 17 flipped when the order was swapped and were discarded; the 3
consistent verdicts all picked mistral-nemo, and none matched the truth-derived winner (0 of 3). A small local model is not fit to
judge, and the order-swap rule caught it.

## Requirement basis

`governance/basis.py`, `tools/gaar_basis.py`, and the workbench page Results → Requirement basis. This is the response
to defect **D20**: no control cites the instrument it derives from.

- For each control, it proposes the instrument passages most likely to back it. Each is quoted verbatim with character
  offsets and the instrument's hash, and a proposal needs at least three distinctive shared terms.
- **Authority flags on every quote.** MAS: consultation draft, not in force. MGF Agentic: voluntary framework. SAFR:
  white paper. NIST AI RMF Playbook: voluntary guidance.
- **Tiered priority** (`config/basis_scope.yaml`). Tier 1 is the pilot's critical path, today MAS M3.12, and is
  confirmed first. Everything else stays visible as a proposal.
- **One control, one recorded decision.** Decisions are CONFIRMED, REJECTED or NO_BASIS_IN_INSTRUMENT, made by a named
  person on a quote that is re-verified against the instrument at that moment, and stored in a hash chain next to the
  workbench data (`GAAR_BASIS_LEDGER` overrides). **Bulk confirmation is refused**: machine-proposed and bulk-confirmed
  would be false assurance at the governance-basis layer.
- ISO/IEC 42001 reads **INSTRUMENT_UNAVAILABLE**, which is not the same as having no basis. Its 38 controls stay
  blocked until the standard is obtained.

## Wider watch

The catalogue now covers Singapore, US, UK, Hong Kong, China and global threat intel (18 sources). The new sources come
from public documentation and are `verified: false`; their first successful scan from your machine verifies them.
The milestone report lists every subscribed source with its state and whether it is verified, so the first live
check of all 18 is visible in the round report.

- **A dead source is one aging item**, not one per 8-hour check. The inbox item is per source and says how many
  attempts failed and since when.
- **Chinese-language items arrive labelled**, "Chinese: not translated", and are never silently translated. The
  bilingual review workflow is deferred, so the label is the interim truth.
- RSS and Atom are read safely: approved hosts only, a 5 MB cap, and documents declaring entities are refused.

      python tools/gaar_watch.py setup --regions sg,us,uk,hk,cn,global

## Regulators that refuse automated clients (kit v24)

The v22 Mac round found MAS answering every automated request with a challenge page and the FCA with HTTP 403, even
to an identified client. The watch does not get around either. Three sanctioned routes replace the blocked scans:

| Route | Source ids | What it is | What it proves |
|---|---|---|---|
| Official email alerts | `mas-email-alerts`, `fca-email-alerts` | The regulator's own alerts (MAS subscription services; FCA daily news and publications alert), read from a folder of .eml files or by IMAP (read-only; the password comes from an environment variable named in `mail.password_env`, never written) | Coverage of what the alert lists. Stale for longer than `stale_after_days` means UNABLE_TO_CHECK, never "no updates" |
| Browser capture | any index, e.g. `mas-circulars-index` | `gaar_watch.py capture --source … --file … --by "<name>"` reads a page you saved in your own browser | That page, on that day, as captured by a named person |
| Search leads | `mas-search-leads`, `fca-search-leads` | `ollama_search.py` (DuckDuckGo, no key) finding pages on the regulator's own site | Nothing about coverage: items are labelled leads and capped at P2 |

Links count only on the regulator's approved hosts and publication paths. A tracking redirect (GovDelivery) is decoded
locally, never followed. The sender check is recorded as it is: an allowlisted From domain, and DKIM only where the
mailbox recorded a pass. HKMA's BRDR "what's new" page builds its list with JavaScript; `hkma-circulars-index`
(www.hkma.gov.hk, the host whose press feed already scans) replaces it.

## One click from watch item to draft control

"Draft a new control from this" (in the workbench) or `gaar_watch.py propose --item <id> --by "<name>"` writes a
proposed MAS control to `~/gaar-watch/drafts/`. It is **not in the assessment suite** until a named person promotes
it with a change ticket (`promote_draft`). The one click saves the drafting; it never skips the approval.

## D19 root fix, and the hazard it creates

Workbench state was resolved relative to the working directory. `governance/paths.workbench_data()` now resolves one
absolute place: `GAAR_WORKBENCH_DATA` if set (the explicit override, used for test isolation and separate installs),
else the package's own `data/`. A test fails if any module resolves state relative to the working directory; the
two remaining uses are allowlisted with their reasons.

**The new hazard is two installed copies sharing one state folder.** The first copy to use a folder records itself
there (`data/.gaar_checkout`). If a different copy that still exists points at the same folder, the workbench shows a
warning. A copy that was replaced in place or removed hands the folder over silently, which is the normal upgrade.
