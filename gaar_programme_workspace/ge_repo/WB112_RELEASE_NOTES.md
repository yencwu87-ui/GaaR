# WB-112 — MGF alias hardening + assessor rating explainability

## Fixed

1. **MGF shorthand resolution in the live cycle**
   - `MGF`, `MGF_Agentic`, and `MGF Agentic` now resolve to the canonical workbook library `MGF Agentic`.
   - Prevents disagreement challenge failures such as `control D1.1 not found in MGF` when a live/legacy cycle carries the shorthand framework name.
   - The same alias is recognized by the governed control-contract and procedural knowledge lookup paths.

2. **Assessor sufficiency/maturity explainability**
   - The assessor prompt now asks for separate `sufficiencyReason` and `maturityReason` fields.
   - The deterministic validator emits a final `sufficiency_basis` and `maturity_basis` after all downgrade/cap rules, so the UI explains the rating that actually survived validation rather than only the raw model choice.
   - If the model proposes `partial` while every applicable canonical element is `met` and no canonical gap survives, the proposal is marked `rating_consistency=review_required` and the UI displays an explicit warning. The downgrade-only validator does not silently manufacture an upgrade to `full`.
   - Maturity explanations distinguish the operating-maturity dimension from requirement sufficiency; e.g. all elements can be evidenced while the process is still only maturity 2 (`documented`) if implementation/measurement evidence is not established.

3. **Streamlit assessment panel**
   - Displays `Why this sufficiency rating` and `Why maturity N/5`.
   - In inconsistent cases, displays a reviewer warning explaining exactly why the proposal needs human confirmation.

## Validation

- WB-112 direct tests: 4/4 passed.
- Core assessor/cycle/D/UI focused regression: 86/86 passed.
- Challenge/Copilot/Colibri/UI focused regression: 79/79 passed.
- `python -m compileall -q .` passed.

## Design boundary preserved

- The assessor still proposes; it does not decide.
- Deterministic validation remains downgrade-only.
- Human review remains the authority for the final sufficiency/maturity decision.
