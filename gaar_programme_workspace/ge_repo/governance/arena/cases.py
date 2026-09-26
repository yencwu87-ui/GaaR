"""Arena cases: one production change and exactly the records needed to judge it, with its labelled truth."""
from __future__ import annotations

import hashlib
import json
import random

from governance.twin.generator import generate_period

CHOICES = ("SUPPORTED", "CONTRADICTED", "INSUFFICIENT")
QUESTION = (
    "You are checking one production change against its approval records. The change is authorised only if ALL hold: "
    "a ticket with this ticket_id exists and is approved; approval happened before execution; the approver is not the "
    "implementer; execution fell inside the approved window; the target and actions are within the ticket's allowed "
    "ones; the implementer and credential are allowed by the ticket; the actual spec hash equals the approved one; "
    "the implementer held a valid privilege grant at execution time covering the credential, target and actions; a "
    "change inside a freeze has a freeze exception approved before execution; a failed change has a successful, "
    "approved rollback or fix-forward completed after it.\n"
    "Answer SUPPORTED if the change is authorised, CONTRADICTED if any condition is broken, INSUFFICIENT if the records "
    "cannot tell. Reply with JSON only: {\"answer\": \"SUPPORTED|CONTRADICTED|INSUFFICIENT\", \"confidence\": 0.0-1.0, "
    "\"violations\": [short names], \"reason\": \"one sentence\"}")


def case_from(generated: dict, change: dict) -> dict:
    pkg = generated["changes"]
    planted = {p["event_id"]: p for p in generated["answer_key"]["planted"]}
    ticket = next((t for t in pkg["tickets"] if t["ticket_id"] == change["ticket_id"]), None)
    records = {
        "change": change,
        "ticket": ticket or "NO TICKET WITH THIS ID IN THE CHANGE REGISTER",
        "privilege_grants_for_implementer": [g for g in pkg["privilege_grants"] if g["actor_id"] == change["actor_id"]],
        "freezes": pkg["freezes"],
        "freeze_exceptions_for_this_change": [x for x in pkg["freeze_exceptions"] if x["event_id"] == change["event_id"]],
        "recoveries_for_this_change": [r for r in pkg["recoveries"] if r["event_id"] == change["event_id"]],
    }
    body = json.dumps(records, sort_keys=True)
    truth = "CONTRADICTED" if change["event_id"] in planted else "SUPPORTED"
    blind = bool((planted.get(change["event_id"]) or {}).get("known_blind"))
    return {"case_id": "CASE-" + hashlib.sha256(body.encode()).hexdigest()[:12], "provenance": "constructed",
            "prompt": QUESTION + "\n\nRECORDS:\n" + json.dumps(records, indent=1),
            "truth": truth, "violation": (planted.get(change["event_id"]) or {}).get("violation"),
            "form": (planted.get(change["event_id"]) or {}).get("form"), "known_blind": blind, "records": records}


def draw(n: int, seed: int, violation_share: float = 0.5, include_known_blind: bool = False) -> list[dict]:
    """n cases, about half with a planted violation, drawn from twin weeks generated from `seed`.

    Known-blind classes (the deterministic checks cannot see them) are left out by default, so the rules baseline stays
    a calibration fixture that must score perfectly. A blind-spot round includes them: there a model can beat the rules."""
    rng = random.Random(seed)
    bad, good, week = [], [], 0
    while len(bad) < n or len(good) < n:
        g = generate_period(seed * 1000 + week, "2026-09-29T00:00:00+08:00", violation_rate=0.4)
        for change in g["changes"]["changes"]:
            c = case_from(g, change)
            if c["known_blind"] and not include_known_blind:
                continue
            (bad if c["truth"] == "CONTRADICTED" else good).append(c)
        week += 1
    k = round(n * violation_share)
    cases = rng.sample(bad, k) + rng.sample(good, n - k)
    rng.shuffle(cases)
    return cases
