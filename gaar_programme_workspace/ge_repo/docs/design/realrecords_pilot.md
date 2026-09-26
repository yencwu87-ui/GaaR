# Real-records pilot (kit v31, revised in v32)

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
| Which repository? | Recommended: python-poetry/poetry, 1 March to 1 September 2026 | Git's own history (read in the sandbox for v32) shows 126 first-parent commits in that window, 5 of them with no pull-request reference in the message, two being release version bumps. The v31 estimate of 70-80 was low. About 520 API reads, well inside the plan's budget of 2,000 |
| How is a skipped page caught? | Git's first-parent history of the window is read when the plan is made and pinned in it (v32). Evaluation refuses if a commit git shows is missing from the API collection | The likeliest silent failure of an API collector is a skipped page, which makes a history look cleaner than it is. Git is a second, independent channel to the same population |
| Where does the token live? | On a Mac, in the Keychain, read at the moment of use (v32). An environment variable only as the fallback elsewhere, set for one command | An exported token sits in every shell's environment, including shells an agent runs commands in |

## The rules (realrecords-controls/1)

| Rule | The change passes when | Evidence read |
|---|---|---|
| RC1 | It reached the default branch through a merged pull request | Commits on the default branch in the window; for any commit not a pull request's own merge commit, GitHub's list of pull requests containing it |
| RC2 | Its pull request was approved by someone other than its author | Each reviewer's latest non-comment review, compared by numeric account ID |
| RC3 | An approval was made on the final commit | The approving review's commit against the pull request's head at merge |
| RC4 | Checks on the final commit passed, none still running | Check runs and the combined commit status of the head. No checks at all is NOT_EVIDENCED, not a pass |

## What is sampled (protocol version 2)

Up to 40 exceptions, 20 changes the rules passed, and up to 20 linked commits: commits counted as arriving through a
pull request because GitHub's lookup said so rather than because they are its merge commit. The link is a rule output
too, and the place a direct change could pass as reviewed. The reviewer's packet (`packet`) opens with the rubric, and
the rubric review (`review-rubric`) is recorded; the score says whether anyone independent has reviewed the rubric.

## Collection

- Read-only GETs to api.github.com only, no redirects, a 20 MB cap per response, and a request budget set in the plan.
- The user agent names GaaR truthfully (`GaaR-realrecords/1`), as the watcher's identification rule requires.
- The token comes from the Keychain entry the plan names, or the variable it names; the receipt records which, never
  the token. A test checks that it is never written to any file. A 401 says fine-grained tokens expire.
- A response in a shape the collector does not know is a recorded stop naming the last URL read, never an unrecorded
  crash (the D27 class: every refusal leaves a record its readers can take).
- Every response is kept byte for byte, with a receipt (URL, status, SHA-256, time) in a hash-chained ledger. A rerun
  reads the kept copy, so a rate-limit stop resumes where it stopped.
- A stopped collection is INCOMPLETE and cannot be evaluated. It is never scored as if it were the whole population.
- Emails are kept only as truncated hashes, enough to count identities.

## What the result will and will not say

It will say how often the rules described one project's records correctly, as judged by named people under a fixed
protocol, and how much of the history had unresolved identity. It will not say anything about a bank, and a clean
result on four rules is not an assessment of the project.
