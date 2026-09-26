# Real-records pilot: labelling protocol

Version 2 (kit v32: adds the linked-commit controls, the rubric review and the git coverage check). Written before
any collection. The pilot plan pins this file's SHA-256, and collection refuses to run if the file has changed since, so labels are always made under the protocol that existed before the results did.

## What is being labelled

The pilot runs four change controls over one public repository's changes to its default branch in a closed window:

| Rule | The change passes when |
|---|---|
| RC1 | It reached the default branch through a merged pull request |
| RC2 | Its pull request was approved by someone other than its author (compared by numeric GitHub account ID) |
| RC3 | An approval was made on the final commit, so the approval covers the code that was merged |
| RC4 | Automated checks on the final commit had all passed, and none were still running |

The rules only report what the records show. A project that does not require reviews is not "wrong"; the question
the label answers is whether the rule described the record correctly.

## Before labelling: review this rubric

An independent reviewer starts here, not with the items. The rules and this rubric were written by GaaR's builder and
are self-approved until someone else reads them; a blind spot here would invalidate every label made under it.
Record ACCEPTED, or CHANGES_NEEDED with a note naming what is missing, before labelling anything. The score states
whether the rubric has been reviewed independently.

## The sample

- Every exception the rules raised, up to 40. Above 40, a random 40.
- 20 changes the rules passed, chosen at random, to look for exceptions the rules missed.
- Up to 20 linked commits: commits the pilot counted as arriving through a pull request because GitHub's lookup said
  so, rather than because they are that pull request's own merge commit (rebase merges, commits without a "(#N)" in
  their message). This is where a direct change could be passed as reviewed, so the link itself is labelled.
- The random choice uses the seed fixed in the approved plan, so anyone can redraw the same sample.

## How to label one item

1. Open the item's link on github.com.
2. For an exception, check the fact the rule states, using the pull request's Conversation, Commits and Checks tabs
   (or the commit page for RC1):
   - **TRUE_EXCEPTION**: the fact is true as stated.
   - **FALSE_POSITIVE**: the fact is false, for example there is an approval by another person on the final commit,
     or the commit did arrive through a pull request. Say what you saw in the note.
   - **CANNOT_TELL**: the page does not show enough to decide, for example a check run that was deleted. Say why.
3. For a linked commit, open the commit and the pull request it names:
   - **CORRECTLY_LINKED**: the commit is one of that pull request's commits, and the pull request was merged into
     the default branch.
   - **WRONGLY_LINKED**: it is not, or the pull request was merged elsewhere. Say what you saw.
   - **CANNOT_TELL**: as above.
4. For a change the rules passed:
   - **CORRECTLY_PASSED**: none of RC1 to RC4 is broken.
   - **MISSED_EXCEPTION**: one is broken. Name the rule and what you saw.
   - **CANNOT_TELL**: as above.
5. Record the label with your own name and your provenance:
   - **self**: you built GaaR, or you work on it.
   - **independent**: you did not build GaaR and have not seen these results discussed.

Decide each item from GitHub's own pages, not from GaaR's claim. Do not change a label because of another person's.
A later label by the same person replaces their earlier one, and both stay on the ledger.

## How the result is reported

- Precision = TRUE_EXCEPTION ÷ (TRUE_EXCEPTION + FALSE_POSITIVE). CANNOT_TELL is reported as its own count and never
  folded into either side.
- Missed exceptions are reported as a count out of the passed sample, not as a rate for the whole population.
- Wrong links are reported as a count out of the linked sample.
- Each labeller is reported separately. Self and independent labels are never merged into one figure.
- Until an independent labeller has labelled the sample, every figure reads "self-labelled by a builder of GaaR,
  not independent".
- Where both exist, agreement is reported as items labelled by both and items where they agreed.

## Coverage

Before any rule runs, the API collection is compared with git's own first-parent history of the default branch for
the same window, fetched when the plan is made and pinned in it. If git shows a commit the API collection lacks,
nothing is evaluated. Commits within an hour of a window edge are reported rather than refused, because the two
sources may place an edge commit differently.

## Identity (limit L1)

Pull-request rules use GitHub's numeric account IDs, which are unique and stable, so a namesake cannot pass on
another person's approval. Commit identity is weaker, and is reported as its own numbers, never as detections:
commits whose author email is linked to no account, accounts committing under several emails, and emails appearing
under several accounts. An RC1 exception by an unlinked author is marked identity-unresolved.

## What this pilot does not claim

- It says nothing about a bank's controls or data. The records are an open-source project's.
- A clean result on four rules is not an assessment of the project.
- Emails are kept only as hashes, for counting; the pilot does not profile contributors.
