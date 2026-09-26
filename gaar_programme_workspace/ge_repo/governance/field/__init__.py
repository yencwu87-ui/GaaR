"""Field agents (GaaR Part 2): evidence gathered from the systems themselves, under a signed collection mandate.

See docs/design/field_agents.md. The agents read; they never write to a source system, never choose an endpoint the
mandate does not name, and never produce evidence content: every record they deliver comes from a source read, with
a receipt. A model may help draft a mandate; a person approves it; deterministic connectors do the collecting.
"""
