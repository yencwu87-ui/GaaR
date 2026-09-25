# Real-records pilot (kit v31)

## Why

Every result so far is on records we constructed: the twin, the arena cases, the constructed bank for the field
agents. A constructed record can only contain the mistakes its author thought of. This pilot runs change controls on
records nobody here made, so the rules meet real record shapes: bots, rebase merges, reviews that were later
withdrawn, checks still running at merge, commits whose author is linked to no account.

## Decisions taken before the build

| Question | Decision | Why |
|---|---|---|
| Planted violations on real history, or fully real detections? | Fully real. Nothing is planted | A planted run proves detection on real shapes, but the twin already measures detection. What is unknown is precision on records we did not write |
| How is ground truth made? | A labelling protocol written before collection (docs/pilot/labeling_protocol.md). The plan pins its hash; collection refuses a changed protocol | The same rule as the twin's adjudications: the key exists before the results |
| Who labels? | Anyone, each with a stated provenance: self or independent. Figures are never merged across provenance; until an independent person labels, every figure reads "self-labelled" | The sample, about 60 items, is also a first piece of named work for an independent reviewer: a few hours, clear instructions |
| Identity (L1)? | In scope as its own numbers, not as detections | Pull-request rules compare numeric account IDs, so namesakes cannot pass on another's approval. Commit identity is weaker, and open-source history is dense with it: unlinked emails, several emails per person, bots. It is counted and shown, never hidden inside a pass rate |
| Hosted models? | Not used. Rules are deterministic | The rule that hosted models see constructed cases only stays in force. Public data might justify an exception, but that is the owner's decision |
| Which repository? | Recommended: python-poetry/poetry, 1 March to 1 September 2026 | About 70-80 changes in six months, most through pull requests, a few whose messages carry no pull-request reference, so the linking rules meet real ambiguity. Small enough to label by hand |

## The rules (realrecords-controls/1)

| Rule | The change passes when | Evidence read |
|---|---|---|
| RC1 | It reached the default branch through a merged pull request | Commits on the default branch in the window; for any commit not a pull request's own merge commit, GitHub's list of pull requests containing it |
| RC2 | Its pull request was approved by someone other than its author | Each reviewer's latest non-comment review, compared by numeric account ID |
| RC3 | An approval was made on the final commit | The approving review's commit against the pull request's head at merge |
| RC4 | Checks on the final commit passed, none still running | Check runs and the combined commit status of the head. No checks at all is NOT_EVIDENCED, not a pass |

## Collection

- Read-only GETs to api.github.com only, no redirects, a 20 MB cap per response, and a request budget set in the plan.
- The user agent names GaaR truthfully (`GaaR-realrecords/1`), as the watcher's identification rule requires.
- The token is read from the variable the plan names (GAAR_GITHUB_TOKEN). A test checks that it is never written to
  any file.
- Every response is kept byte for byte, with a receipt (URL, status, SHA-256, time) in a hash-chained ledger. A rerun
  reads the kept copy, so a rate-limit stop resumes where it stopped.
- A stopped collection is INCOMPLETE and cannot be evaluated. It is never scored as if it were the whole population.
- Emails are kept only as truncated hashes, enough to count identities.

## What the result will and will not say

It will say how often the rules described one project's records correctly, as judged by named people under a fixed
protocol, and how much of the history had unresolved identity. It will not say anything about a bank, and a clean
result on four rules is not an assessment of the project.
