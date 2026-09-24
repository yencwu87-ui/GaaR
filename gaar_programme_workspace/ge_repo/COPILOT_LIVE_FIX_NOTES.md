# Copilot live-response verification fix

Confirmed from a real Ollama reference request that the model returned a JSON object of the form:

`{"response": { ...copilot fields... }}`

The Copilot parser now normalizes only this exact single-key `response` wrapper before applying the frozen Copilot schema. Sibling/unknown envelope fields remain rejected, and prohibited judgement fields inside the wrapper remain rejected.

Confirmed harness defect: the blocked Scenario D path previously returned process exit code 0. The probe now returns exit code 1 for a blocked/rejected failure and 2 for an unexpected fallback success.

Focused verification after these changes: 31 passed.

Live verification still required on the Mac:
- rerun Scenario D and confirm nonzero exit;
- rerun Scenario A and confirm the response reaches `copilot_presented`;
- only then proceed to Scenario B.
