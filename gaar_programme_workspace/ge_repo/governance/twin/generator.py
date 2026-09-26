"""The digital twin: a constructed bank that produces a fresh week of change evidence on demand (kit v22).

What it is for, and what it is not:

- It exercises the pipeline end to end with realistic volume, and it measures detection: every week plants a random
  number of subtle violations, in random changes, in random forms, from a seed. Which change carries which violation
  is not known in advance by anyone reading the code, so a detection rate over many seeds is a robustness measure, not
  a replay of known cases (property-based testing).
- The answer key is sealed from the code: it is written outside the evidence inbox with a hash commitment, and no
  procedure reads it. It is not sealed from the author: the violations were designed by the same authorship chain as
  the tests. So a twin detection rate is a regression measure, never independent ground truth.
- Exit criterion (docs/design/twin_and_arena.md): the twin runs until real exports flow, and is never a reason to
  defer them.

Every export is marked CONSTRUCTED_TEST_DATA and synthetic.
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

BANK = "Meranti Bank (constructed)"
SYSTEMS = {
    "payments-api-prod": ["deploy_release"],
    "payments-db-prod": ["apply_migration"],
    "credit-scoring-model-prod": ["deploy_model", "update_threshold"],
    "fraud-rules-prod": ["deploy_rules"],
}
IMPLEMENTERS = ["alice.tan", "bob.koh", "carol.wee", "farid.rahman", "grace.lee"]
APPROVERS = ["dave.lim", "erin.ng", "hui.min"]
CREDENTIAL = "deploy-key-ci"

# Each violation: the codes the deterministic checks must raise on that change (expected), and the codes the same
# condition may legitimately also raise (permitted). Anything else on that change is a false positive.
VIOLATIONS = {
    "SELF_APPROVAL": (["SELF_APPROVAL"], []),
    "APPROVAL_AFTER_EXECUTION": (["APPROVAL_AFTER_EXECUTION"], []),
    "OUTSIDE_APPROVED_WINDOW": (["OUTSIDE_APPROVED_WINDOW"], []),
    "NO_MATCHING_APPROVED_TICKET": (["NO_MATCHING_APPROVED_TICKET"], []),
    "DEVIATES_FROM_APPROVED_SCOPE": (["DEVIATES_FROM_APPROVED_SCOPE"], ["PRIVILEGE_NOT_ESTABLISHED"]),
    "IMPLEMENTER_NOT_APPROVED": (["IMPLEMENTER_NOT_APPROVED"], []),
    "CREDENTIAL_NOT_APPROVED_FOR_CHANGE": (["CREDENTIAL_NOT_APPROVED_FOR_CHANGE"], ["PRIVILEGE_NOT_ESTABLISHED"]),
    "IMPLEMENTATION_CONTENT_MISMATCH": (["IMPLEMENTATION_CONTENT_MISMATCH"], []),
    "FREEZE_WITHOUT_PRIOR_EXCEPTION": (["FREEZE_WITHOUT_PRIOR_EXCEPTION"], []),
    "RECOVERY_NOT_ESTABLISHED": (["RECOVERY_NOT_ESTABLISHED"], []),
    "PRIVILEGE_NOT_ESTABLISHED": (["PRIVILEGE_NOT_ESTABLISHED"], []),
    "UNLOGGED_CHANGE": (["COLLECTION_POPULATION_DISAGREEMENT"], []),
    "IDENTITY_COLLISION": (["PRIVILEGE_NOT_ESTABLISHED"], []),
}
# Violation classes the checks are known to be blind to, planted on purpose so the blind spot is measured, not hidden.
# They are scored apart from the headline and never counted in it (docs/design/twin_and_arena.md, adjudication A-002).
KNOWN_BLIND = {
    "IDENTITY_COLLISION": "The checks resolve identity by actor name. Two people who share a name are one actor to them, "
                          "so a person without a grant passes on a namesake's grant. Real exports with names-only "
                          "identity carry the same limit; a collector must supply unique actor IDs to remove it.",
}


def _iso(t: datetime) -> str:
    return t.isoformat()


def _hash(rng: random.Random) -> str:
    return hashlib.sha1(str(rng.random()).encode()).hexdigest()


def generate_period(seed: int, period_end: str, *, scope: str = "CONSTRUCTED-payments-api", cadence_days: int = 7,
                    changes: tuple[int, int] = (6, 14), violation_rate: float = 0.25) -> dict:
    """One period's exports (changes.json, population.json) and its sealed answer key."""
    rng = random.Random(f"{seed}|{period_end}")
    end = datetime.fromisoformat(period_end)
    start = end - timedelta(days=cadence_days)
    n = rng.randint(*changes)
    events, tickets, grants, recoveries = [], [], [], []
    freeze_day = start + timedelta(days=rng.randint(1, cadence_days - 2))
    freeze = {"freeze_id": f"FRZ-{freeze_day:%m%d}", "start": _iso(freeze_day), "end": _iso(freeze_day + timedelta(days=1)),
              "targets": ["payments-api-prod", "payments-db-prod"]}
    exceptions, key = [], []
    for actor in IMPLEMENTERS:                                       # standing privilege for every implementer
        grants.append({"grant_id": f"PG-{actor}", "actor_id": actor, "credential_id": CREDENTIAL, "approved_by": "sec.admin",
                       "approved_at": _iso(start - timedelta(days=30)), "valid_from": _iso(start - timedelta(days=20)),
                       "valid_until": _iso(end + timedelta(days=60)), "allowed_targets": list(SYSTEMS),
                       "allowed_actions": sorted({a for acts in SYSTEMS.values() for a in acts})})
    planted_kinds = [k for k in VIOLATIONS if k != "UNLOGGED_CHANGE"]
    for i in range(n):
        eid, tid = f"CHG-{seed % 1000:03d}-{end:%m%d}-{i + 1:02d}", f"CR-{seed % 1000:03d}-{end:%m%d}-{i + 1:02d}"
        asset = rng.choice(list(SYSTEMS))
        actor, approver = rng.choice(IMPLEMENTERS), rng.choice(APPROVERS)
        day = start + timedelta(days=rng.randint(0, cadence_days - 2))    # clear of the period's last evening
        if day.date() == freeze_day.date() and asset in freeze["targets"]:
            day += timedelta(days=1)                                 # clean changes avoid the freeze
            if day >= end - timedelta(days=1):
                day -= timedelta(days=2)
        window_start = day.replace(hour=20, minute=0, second=0, microsecond=0)
        occurred = window_start + timedelta(minutes=rng.randint(5, 150))
        spec = _hash(rng)
        change = {"event_id": eid, "ticket_id": tid, "occurred_at": _iso(occurred), "asset_id": asset, "actor_id": actor,
                  "credential_id": CREDENTIAL, "actions": [rng.choice(SYSTEMS[asset])], "actual_spec_hash": spec,
                  "outcome": "succeeded"}
        ticket = {"ticket_id": tid, "status": "approved", "approved_by": approver,
                  "approved_at": _iso(window_start - timedelta(hours=rng.randint(4, 30))),
                  "window_start": _iso(window_start), "window_end": _iso(window_start + timedelta(hours=3)),
                  "allowed_targets": [asset], "allowed_actions": list(change["actions"]),
                  "allowed_implementers": [actor], "allowed_credentials": [CREDENTIAL], "approved_spec_hash": spec}
        clean_failure = rng.random() < 0.12                          # some clean failures, properly recovered
        kind = rng.choice(planted_kinds) if rng.random() < violation_rate else None
        form = None
        if kind == "SELF_APPROVAL":
            ticket["approved_by"] = actor
        elif kind == "APPROVAL_AFTER_EXECUTION":
            minutes = rng.choice([3, 7, 19, 55])
            ticket["approved_at"] = _iso(occurred + timedelta(minutes=minutes)); form = f"approved {minutes} min after"
        elif kind == "OUTSIDE_APPROVED_WINDOW":
            minutes = rng.choice([1, 20, 95])
            change["occurred_at"] = _iso(window_start + timedelta(hours=3, minutes=minutes)); form = f"{minutes} min late"
        elif kind == "NO_MATCHING_APPROVED_TICKET":
            change["ticket_id"] = tid + "-X"; form = "ticket id mistyped"
        elif kind == "DEVIATES_FROM_APPROVED_SCOPE":
            change["actions"] = change["actions"] + ["disable_audit_logging"]; form = "extra action"
        elif kind == "IMPLEMENTER_NOT_APPROVED":
            change["actor_id"] = next(a for a in IMPLEMENTERS if a != actor); form = "colleague implemented"
        elif kind == "CREDENTIAL_NOT_APPROVED_FOR_CHANGE":
            change["credential_id"] = f"{actor}-personal-admin"; form = "personal admin credential"
        elif kind == "IMPLEMENTATION_CONTENT_MISMATCH":
            change["actual_spec_hash"] = spec[:-1] + ("0" if spec[-1] != "0" else "1"); form = "one character differs"
        elif kind == "FREEZE_WITHOUT_PRIOR_EXCEPTION":
            asset = change["asset_id"] = ticket["allowed_targets"][0] = rng.choice(freeze["targets"])
            change["actions"] = ticket["allowed_actions"] = [SYSTEMS[asset][0]]
            window_start = freeze_day.replace(hour=20, minute=0)
            occurred = window_start + timedelta(minutes=30)
            change["occurred_at"] = _iso(occurred)
            ticket.update(window_start=_iso(window_start), window_end=_iso(window_start + timedelta(hours=3)),
                          approved_at=_iso(window_start - timedelta(hours=6)))
            if rng.random() < 0.5:
                exceptions.append({"freeze_id": freeze["freeze_id"], "event_id": eid, "approved_by": "cfo.office",
                                   "approved_at": _iso(occurred + timedelta(hours=1)), "reason": "retroactive"})
                form = "exception approved after the change"
            else:
                form = "no exception"
        elif kind == "RECOVERY_NOT_ESTABLISHED":
            change["outcome"] = "failed"
            if rng.random() < 0.5:
                recoveries.append({"event_id": eid, "method": "rollback", "approved_by": approver, "status": "failed",
                                   "completed_at": _iso(occurred + timedelta(minutes=40))})
                form = "rollback failed"
            else:
                form = "no recovery record"
        elif kind == "IDENTITY_COLLISION":
            shared = f"ext.contractor.{i + 1:02d}"                   # two different people, one name
            change["actor_id"], change["actor_uid"] = shared, f"EXT-B-{eid}"
            ticket["allowed_implementers"] = [shared]
            grants.append({"grant_id": f"PG-{eid}", "actor_id": shared, "actor_uid": f"EXT-A-{eid}",
                           "credential_id": CREDENTIAL, "approved_by": "sec.admin",
                           "approved_at": _iso(start - timedelta(days=40)), "valid_from": _iso(start - timedelta(days=40)),
                           "valid_until": _iso(end + timedelta(days=60)), "allowed_targets": [asset],
                           "allowed_actions": list(change["actions"])})
            form = "namesake holds the grant"
        elif kind == "PRIVILEGE_NOT_ESTABLISHED":
            actor2 = f"temp.contractor.{i + 1:02d}"                 # one contractor per plant: no shared grants
            change["actor_id"] = actor2
            ticket["allowed_implementers"] = [actor2]
            grants.append({"grant_id": f"PG-{eid}", "actor_id": actor2, "credential_id": CREDENTIAL, "approved_by": "sec.admin",
                           "approved_at": _iso(start - timedelta(days=40)), "valid_from": _iso(start - timedelta(days=40)),
                           "valid_until": _iso(occurred - timedelta(hours=2)), "allowed_targets": [asset],
                           "allowed_actions": list(change["actions"])})
            form = "grant expired 2 h before"
        if clean_failure and kind != "RECOVERY_NOT_ESTABLISHED":
            # written after every adjustment above, so the recovery always follows the change's final time
            change["outcome"] = "failed"
            recoveries.append({"event_id": eid, "method": "rollback", "approved_by": approver, "status": "succeeded",
                               "completed_at": _iso(datetime.fromisoformat(change["occurred_at"]) + timedelta(minutes=25))})
        if kind:
            expected, permitted = list(VIOLATIONS[kind][0]), list(VIOLATIONS[kind][1])
            incidental = []
            final = datetime.fromisoformat(change["occurred_at"])
            if (kind != "FREEZE_WITHOUT_PRIOR_EXCEPTION" and change["asset_id"] in freeze["targets"]
                    and datetime.fromisoformat(freeze["start"]) <= final < datetime.fromisoformat(freeze["end"])):
                # A late change can slide into the freeze. That is a real second violation, so the key requires it
                # (adjudication A-001): it is recorded, counted and must be detected, never merely tolerated.
                incidental.append("FREEZE_WITHOUT_PRIOR_EXCEPTION")
            key.append({"event_id": eid, "violation": kind, "form": form, "expected": expected + incidental,
                        "permitted": permitted, "incidental": incidental, "known_blind": kind in KNOWN_BLIND})
        events.append(change)
        tickets.append(ticket)
    primary = [e["event_id"] for e in events]
    independent = list(primary)
    if rng.random() < violation_rate / 2:                           # a change the deploy log never saw
        ghost = f"CHG-{seed % 1000:03d}-{end:%m%d}-99"
        independent.append(ghost)
        key.append({"event_id": ghost, "violation": "UNLOGGED_CHANGE", "form": "only the host audit saw it",
                    "expected": ["COLLECTION_POPULATION_DISAGREEMENT"], "permitted": [], "incidental": [],
                    "known_blind": False})
    as_of = period_end
    package = {"synthetic": True, "data_classification": "CONSTRUCTED_TEST_DATA", "bank": BANK, "scope": scope,
               "as_of": as_of, "policy": {"incident_lookback_hours": 24, "failed_change_requires_recovery": True},
               "collection": {"complete": True, "source_ids": ["CONSTRUCTED-ci-deploy-log", "CONSTRUCTED-change-register"],
                              "period_start": _iso(start), "period_end": _iso(end)},
               "changes": sorted(events, key=lambda e: e["occurred_at"]), "tickets": tickets, "privilege_grants": grants,
               "freezes": [freeze], "freeze_exceptions": exceptions, "incidents": [], "recoveries": recoveries}
    population = {"scope": scope, "as_of": as_of,
                  "primary": {"scope": scope, "as_of": as_of, "complete": True, "source_id": "CONSTRUCTED-ci-deploy-log",
                              "event_ids": primary},
                  "independent": {"scope": scope, "as_of": as_of, "complete": True, "source_id": "CONSTRUCTED-host-audit",
                                  "event_ids": independent}}
    answer_key = {"bank": BANK, "seed": seed, "period_end": period_end, "changes": len(events), "planted": key,
                  "provenance": "constructed; violations designed by the project's own authors (not independent truth)"}
    return {"changes": package, "population": population, "answer_key": answer_key}


def seal(answer_key: dict, key_dir: Path) -> dict:
    """Write the key outside the evidence, with a hash commitment the scorer checks before it trusts the key."""
    key_dir = Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(answer_key, sort_keys=True, indent=2)
    name = f"key-{answer_key['period_end'][:10]}-seed{answer_key['seed']}.json"
    (key_dir / name).write_text(body + "\n")
    commitment = hashlib.sha256(body.encode()).hexdigest()
    ledger = key_dir / "commitments.jsonl"
    with ledger.open("a") as fh:
        fh.write(json.dumps({"key": name, "sha256": commitment, "sealed_at": datetime.now().astimezone().isoformat()}) + "\n")
    return {"key": str(key_dir / name), "sha256": commitment}


def load_key(path: Path) -> dict:
    """A key is trusted only if it matches the commitment written when it was sealed."""
    path = Path(path)
    body = path.read_text().rstrip("\n")
    commitments = [json.loads(line) for line in (path.parent / "commitments.jsonl").read_text().splitlines() if line.strip()]
    mine = [c for c in commitments if c["key"] == path.name]
    if not mine or mine[-1]["sha256"] != hashlib.sha256(body.encode()).hexdigest():
        raise ValueError("answer key does not match its sealed commitment; it was changed after sealing")
    return json.loads(body)


def score(found: dict[str, set[str]], answer_key: dict, all_events: list[str]) -> dict:
    """Compare the codes the checks raised per change with the planted violations.

    `found` maps event_id -> codes raised on it (population-level codes are attached to the missing event).
    Known-blind classes are scored apart: they measure a documented blind spot and never enter the headline."""
    planted = {p["event_id"]: p for p in answer_key["planted"]}
    detected, missed, false_positive = [], [], []
    blind = {"planted": 0, "detected": 0}
    for eid, p in planted.items():
        codes = found.get(eid, set())
        caught = set(p["expected"]) <= codes
        if p.get("known_blind"):
            blind["planted"] += 1
            blind["detected"] += caught
            continue
        (detected if caught else missed).append({"event_id": eid, "violation": p["violation"],
                                                 "form": p["form"], "raised": sorted(codes)})
    for eid in set(all_events) | set(found):
        allowed = set(planted[eid]["expected"] + planted[eid]["permitted"]) if eid in planted else set()
        extra = found.get(eid, set()) - allowed
        if extra:
            false_positive.append({"event_id": eid, "codes": sorted(extra)})
    total = len(detected) + len(missed)
    headline = [p for p in planted.values() if not p.get("known_blind")]
    return {"planted": total, "detected": len(detected), "missed": missed, "false_positives": false_positive,
            "planted_codes": sum(len(p["expected"]) for p in headline),
            "incidental_codes": sum(len(p.get("incidental", [])) for p in headline),
            "detection_rate": round(len(detected) / total, 3) if total else None, "known_blind": blind,
            "provenance": answer_key["provenance"]}


def run_checks(generated: dict) -> dict[str, set[str]]:
    """Run the pilot's own deterministic procedures on a generated period and collect codes per change."""
    from governance.production.procedures import change_authorization, change_population, change_segregation
    found: dict[str, set[str]] = {}
    auth = change_authorization(generated["changes"])
    for f in auth.get("findings", []) + auth.get("assurance_gaps", []):
        found.setdefault(f["event_id"], set()).add(f["code"])
    for f in change_segregation(generated["changes"])["findings"]:
        found.setdefault(f["event_id"], set()).add(f["code"])
    pop = change_population(generated["population"])
    for gap in pop.get("assurance_gaps", []):
        for eid in gap.get("missing_primary", []) + gap.get("missing_independent", []):
            found.setdefault(eid, set()).add(gap["code"])
    return found
