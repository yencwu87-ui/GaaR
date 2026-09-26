# Releasing a kit

A kit is released only if it is the exact zip that was rehearsed. v22 shipped register text changed after its
rehearsal, and v31 shipped install-path code changed after its rehearsal. Each change was small and disclosed, but the
next one will not announce itself as small, so the rule is mechanical.

## Order

1. Finish every change. Run the full suite and the refusal trace on the final code.
2. Build the kit once: `python tools/build_kit.py --version vNN --out <zip>`. The manifest records the expected test
   count, trace modules and trace target from this tree.
3. Rehearse with that zip, as an ordinary (non-root) user on Singapore time, over a state like the Mac's:
   - the previous kit installed, with a practice series built by `python tools/rehearsal_series.py` (signed mapping
     and independent review, so the gate table matches the Mac's);
   - at least one signed week and one awaiting week;
   - a twin adjudication confirmed under a name;
   - the leftovers the Mac is known to carry, such as the v28 environment-stop record and a scheduler outage;
   - what a Mac writes into any install and the sandbox never does (D32): Finder's `.DS_Store` files in several
     folders, the retriever's `.cache/embeddings.jsonl`, and a draft of the owner's own in `requirements/drafts/`;
   - then `python tools/gaar_round.py --kit <zip>`.
4. `python tools/release_check.py --kit <zip> --round <the rehearsal's round folder>`. It refuses unless the rehearsal
   installed this exact file, with its SHA-256 recorded by the installer, no ledger changed, the expected counts were
   met, and the milestone ended ALL GATES AS EXPECTED or WAITING ON YOU with nothing reported as DIFFERS.
5. Send that zip. After step 3, the only permitted action is sending it. Any change, however small, means a new
   build and a new rehearsal from step 2.

## When the installer that ran is older than the release rule

A round installs with the code already on the machine, then continues on the new code. The first v32 rehearsal was
installed by v31's installer, which records no zip hash, so the check refused it though nothing had changed. The new
code now records the SHA-256 of the manifest it installed, and the check accepts the zip only if its manifest has that
hash, every file in the zip matches the manifest, and the rehearsal's doctor found the install to be exactly the
manifest's files.

## What a rehearsal cannot show

The sandbox cannot reach some of what the Mac reaches (the GitHub API, regulators' sites, Ollama, the Keychain).
State in the release note which paths the rehearsal exercised and which the Mac will exercise for the first time.
