# Demo: Scrutinise this Evidence (WB-122)

**Buyer question:** "Can you show me exactly what your evidence proves, and what it doesn't?"

1. Show the SAFR 2.1 control assertion: threshold approval before deployment.
2. Run Scout against an explicitly approved *synthetic* demo folder. Note `PROPOSED_ONLY` and retain the actual acquisition ID.
3. Run Assembly with that exact ID. Open the generated Markdown dossier and show exact quotes, source IDs, immutable SHA-256 blob refs.
4. Open Living Results → Evidence Dossiers → Scrutinise proposed evidence. Explain why it is **not CURRENT** and not automatically admitted.
5. Read the challenge surface: temporal, independent-origin and interpretation checks. Show that a PR mentioning approval without a deployment record cannot establish approval-before-deployment.
6. Run the read-only integrity probe. Demonstrate that modifying an original source after discovery causes assembly to fail; mutating a stored blob causes the probe to fail.
7. Conclude: GaaR does not merely create a persuasive audit narrative; it makes each claim inexpensive to inspect and falsify.

Record actual UI and terminal output on the target Mac, not fabricated console output. The final end-to-end result demo is still gated on governed admission and Mac-live acceptance.
