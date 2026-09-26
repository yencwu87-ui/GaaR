"""A named person means a real name (kit v23). Defect D22: two confirmations were recorded as "Your Name"."""
from __future__ import annotations

import re

PLACEHOLDERS = {"your name", "your full name", "name", "full name", "test", "tbd", "n/a", "na", "none", "someone",
                "me", "user", "reviewer", "approver", "owner", "xxx", "abc"}


def is_placeholder(name: str) -> bool:
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    return not n or n in PLACEHOLDERS or "<" in n or ">" in n


def require_person(name: str, refusal: str) -> str:
    """Return the name, stripped; refuse an empty name with `refusal`, and a template placeholder by name."""
    if not (name or "").strip():
        raise ValueError(refusal)
    if is_placeholder(name):
        raise ValueError(f"'{name.strip()}' is a placeholder, not a name: record the person's own name")
    return name.strip()
