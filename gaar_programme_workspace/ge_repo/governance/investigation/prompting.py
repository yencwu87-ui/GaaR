"""Prompt rendering for model stages.

Top-level order matters to a model even though it does not matter to JSON.
Alphabetical order put the admitted evidence first and the task last, so any
truncation removed the instructions. The task, rules, answer format and
schema now lead; everything else follows in sorted order. Nested values are
rendered canonically so the text stays deterministic and hashable.
"""
import json

LEAD = ("task", "rules", "answer_format", "schema")


def _canonical(value):
    return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False))


def render(prompt: dict) -> str:
    ordered = {key: _canonical(prompt[key]) for key in LEAD if key in prompt}
    ordered.update({key: _canonical(prompt[key]) for key in sorted(prompt) if key not in ordered})
    return json.dumps(ordered, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
