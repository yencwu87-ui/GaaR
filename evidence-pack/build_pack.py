#!/usr/bin/env python3
"""Build a CONSTRUCTED change-management evidence pack with planted scenarios.

Everything here is invented test data. It is marked `"synthetic": true` inside
the change export (a field the reconciliation already reports back), and every
source id starts with CONSTRUCTED-. It exists to measure the pipeline against a
known answer, not to evidence any real control.

The answer key is written to a separate folder. Do not put it anywhere the
provisioner can read: the model sees admitted evidence, and a leaked key would
make every result meaningless.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
EVIDENCE = OUT / "evidence"
KEY = OUT / "answer_key_DO_NOT_PROVISION"

SYSTEM = "CONSTRUCTED-payments-api"
AS_OF = "2026-09-15T00:00:00+08:00"
START = "2026-09-01T00:00:00+08:00"

API, DB = "payments-api-prod", "payments-db-prod"
CI = "deploy-key-ci"
DEPLOY = ["deploy_release"]
MIGRATE = ["apply_migration"]


def ticket(tid, approver, approved_at, start, end, targets, actions, implementers, creds, spec, status="approved"):
    return {"ticket_id": tid, "status": status, "approved_by": approver, "approved_at": approved_at,
            "window_start": start, "window_end": end, "allowed_targets": targets, "allowed_actions": actions,
            "allowed_implementers": implementers, "allowed_credentials": creds, "approved_spec_hash": spec}


def change(cid, tid, at, asset, actor, cred, actions, spec, outcome="succeeded"):
    return {"event_id": cid, "ticket_id": tid, "occurred_at": at, "asset_id": asset, "actor_id": actor,
            "credential_id": cred, "actions": actions, "actual_spec_hash": spec, "outcome": outcome}


def h(label):  # readable stand-in for a commit or artefact hash
    import hashlib
    return hashlib.sha256(label.encode()).hexdigest()[:40]


tickets = [
    ticket("CR-101", "dave.lim", "2026-09-02T09:00:00+08:00", "2026-09-02T20:00:00+08:00", "2026-09-02T23:00:00+08:00",
           [API], DEPLOY, ["alice.tan"], [CI], h("release-4.2.0")),
    ticket("CR-102", "erin.ng", "2026-09-03T10:00:00+08:00", "2026-09-03T20:00:00+08:00", "2026-09-03T23:00:00+08:00",
           [API], DEPLOY, ["bob.koh"], [CI], h("release-4.2.1")),
    # self-approved: approver is the implementer. The reconciliation does not test this.
    ticket("CR-103", "alice.tan", "2026-09-04T11:00:00+08:00", "2026-09-04T20:00:00+08:00", "2026-09-04T23:00:00+08:00",
           [API], DEPLOY, ["alice.tan"], [CI], h("release-4.2.2")),
    ticket("CR-104", "dave.lim", "2026-09-05T09:30:00+08:00", "2026-09-05T20:00:00+08:00", "2026-09-05T23:00:00+08:00",
           [API], DEPLOY, ["bob.koh"], [CI], h("release-4.3.0")),
    # approved after the change ran
    ticket("CR-105", "erin.ng", "2026-09-05T22:40:00+08:00", "2026-09-05T20:00:00+08:00", "2026-09-05T23:00:00+08:00",
           [API], DEPLOY, ["alice.tan"], [CI], h("hotfix-4.3.1")),
    # window written in UTC; the change is at 10:00 SGT = 02:00 UTC, before the window opens
    ticket("CR-106", "dave.lim", "2026-09-05T08:00:00Z", "2026-09-06T09:00:00Z", "2026-09-06T18:00:00Z",
           [API], DEPLOY, ["bob.koh"], [CI], h("release-4.3.2")),
    ticket("CR-108", "erin.ng", "2026-09-07T09:00:00+08:00", "2026-09-07T20:00:00+08:00", "2026-09-07T23:00:00+08:00",
           [API], DEPLOY, ["bob.koh"], [CI], h("release-4.4.0")),
    ticket("CR-109", "dave.lim", "2026-09-08T09:00:00+08:00", "2026-09-10T20:00:00+08:00", "2026-09-10T23:00:00+08:00",
           [API], DEPLOY, ["alice.tan"], [CI], h("release-4.4.1")),
    ticket("CR-110", "dave.lim", "2026-09-08T09:00:00+08:00", "2026-09-10T21:00:00+08:00", "2026-09-10T23:00:00+08:00",
           [API], DEPLOY, ["bob.koh"], [CI], h("release-4.4.2")),
    ticket("CR-111", "erin.ng", "2026-09-11T09:00:00+08:00", "2026-09-11T20:00:00+08:00", "2026-09-11T23:00:00+08:00",
           [DB], MIGRATE, ["carol.wee"], [CI], h("migration-0042")),
    ticket("CR-112", "erin.ng", "2026-09-12T09:00:00+08:00", "2026-09-12T20:00:00+08:00", "2026-09-12T23:00:00+08:00",
           [DB], MIGRATE, ["carol.wee"], [CI], h("migration-0043")),
    # emergency change raised and approved during an incident, before execution
    ticket("ECR-113", "dave.lim", "2026-09-13T03:05:00+08:00", "2026-09-13T03:00:00+08:00", "2026-09-13T06:00:00+08:00",
           [DB], ["restart_service", "apply_config"], ["carol.wee"], ["cred-carol-admin"], h("emergency-pool-config")),
    ticket("CR-114", "dave.lim", "2026-09-14T09:00:00+08:00", "2026-09-14T20:00:00+08:00", "2026-09-14T23:00:00+08:00",
           [DB], MIGRATE, ["carol.wee"], [CI], h("migration-0044")),
    # a ticket that was raised but never approved
    ticket("CR-116", "", "", "2026-09-14T20:00:00+08:00", "2026-09-14T23:00:00+08:00",
           [API], DEPLOY, ["alice.tan"], [CI], h("release-4.5.0"), status="pending"),
]

changes = [
    change("CHG-01", "CR-101", "2026-09-02T21:05:00+08:00", API, "alice.tan", CI, DEPLOY, h("release-4.2.0")),
    change("CHG-02", "CR-102", "2026-09-03T21:10:00+08:00", API, "bob.koh", CI, DEPLOY, h("release-4.2.1")),
    change("CHG-03", "CR-103", "2026-09-04T21:00:00+08:00", API, "alice.tan", CI, DEPLOY, h("release-4.2.2")),
    change("CHG-04", "CR-104", "2026-09-05T20:30:00+08:00", API, "bob.koh", CI, DEPLOY, h("release-4.3.0-rc2")),
    change("CHG-05", "CR-105", "2026-09-05T22:15:00+08:00", API, "alice.tan", CI, DEPLOY, h("hotfix-4.3.1")),
    change("CHG-06", "CR-106", "2026-09-06T10:00:00+08:00", API, "bob.koh", CI, DEPLOY, h("release-4.3.2")),
    change("CHG-07", "CR-107", "2026-09-06T23:40:00+08:00", API, "alice.tan", CI, DEPLOY, h("unticketed-build")),
    change("CHG-08", "CR-108", "2026-09-07T21:00:00+08:00", API, "bob.koh", "cred-bob-personal", DEPLOY, h("release-4.4.0")),
    change("CHG-09", "CR-109", "2026-09-10T21:30:00+08:00", API, "alice.tan", CI, DEPLOY, h("release-4.4.1")),
    change("CHG-10", "CR-110", "2026-09-10T21:45:00+08:00", API, "bob.koh", CI, DEPLOY, h("release-4.4.2")),
    change("CHG-11", "CR-111", "2026-09-11T21:00:00+08:00", DB, "carol.wee", CI, MIGRATE, h("migration-0042"), "failed"),
    change("CHG-12", "CR-112", "2026-09-12T21:00:00+08:00", DB, "carol.wee", CI, MIGRATE, h("migration-0043"), "failed"),
    change("CHG-13", "ECR-113", "2026-09-13T03:20:00+08:00", DB, "carol.wee", "cred-carol-admin",
           ["restart_service", "apply_config"], h("emergency-pool-config")),
    change("CHG-14", "CR-114", "2026-09-14T21:00:00+08:00", DB, "carol.wee", CI, MIGRATE + ["drop_index"], h("migration-0044")),
    change("CHG-16", "CR-116", "2026-09-14T21:30:00+08:00", API, "alice.tan", CI, DEPLOY, h("release-4.5.0")),
]

grants = [
    {"grant_id": "PG-1", "actor_id": "alice.tan", "credential_id": CI, "approved_by": "sec.admin",
     "approved_at": "2026-08-25T09:00:00+08:00", "valid_from": "2026-09-01T00:00:00+08:00",
     "valid_until": "2026-10-01T00:00:00+08:00", "allowed_targets": [API], "allowed_actions": DEPLOY},
    {"grant_id": "PG-2", "actor_id": "bob.koh", "credential_id": CI, "approved_by": "sec.admin",
     "approved_at": "2026-08-25T09:00:00+08:00", "valid_from": "2026-09-01T00:00:00+08:00",
     "valid_until": "2026-10-01T00:00:00+08:00", "allowed_targets": [API], "allowed_actions": DEPLOY},
    {"grant_id": "PG-3", "actor_id": "carol.wee", "credential_id": CI, "approved_by": "sec.admin",
     "approved_at": "2026-08-25T09:00:00+08:00", "valid_from": "2026-09-01T00:00:00+08:00",
     "valid_until": "2026-10-01T00:00:00+08:00", "allowed_targets": [DB], "allowed_actions": MIGRATE},
    # break-glass credential, granted for the incident window only
    {"grant_id": "PG-4", "actor_id": "carol.wee", "credential_id": "cred-carol-admin", "approved_by": "sec.admin",
     "approved_at": "2026-09-13T03:02:00+08:00", "valid_from": "2026-09-13T03:00:00+08:00",
     "valid_until": "2026-09-13T07:00:00+08:00", "allowed_targets": [DB],
     "allowed_actions": ["restart_service", "apply_config"]},
]

change_export = {
    "synthetic": True,
    "data_classification": "CONSTRUCTED_TEST_DATA",
    "scope": SYSTEM, "as_of": AS_OF,
    "policy": {"incident_lookback_hours": 24, "failed_change_requires_recovery": True},
    "collection": {"complete": True, "source_ids": ["CONSTRUCTED-ci-deploy-log", "CONSTRUCTED-change-register"],
                   "period_start": START, "period_end": AS_OF},
    "changes": changes,
    "tickets": tickets,
    "privilege_grants": grants,
    "freezes": [{"freeze_id": "FRZ-MONTH-CLOSE", "start": "2026-09-10T00:00:00+08:00",
                 "end": "2026-09-11T00:00:00+08:00", "targets": [API]}],
    "freeze_exceptions": [{"freeze_id": "FRZ-MONTH-CLOSE", "event_id": "CHG-10", "approved_by": "cfo.office",
                           "approved_at": "2026-09-09T17:00:00+08:00",
                           "reason": "Regulatory reporting fix required before month close"}],
    "incidents": [{"incident_id": "INC-7781", "started_at": "2026-09-13T02:40:00+08:00", "assets": [DB]}],
    "recoveries": [{"event_id": "CHG-12", "method": "rollback", "approved_by": "erin.ng", "status": "succeeded",
                    "completed_at": "2026-09-12T21:25:00+08:00"}],
}

observed = [c["event_id"] for c in changes]
population = {
    "scope": SYSTEM, "as_of": AS_OF,
    "primary": {"scope": SYSTEM, "as_of": AS_OF, "complete": True, "source_id": "CONSTRUCTED-ci-deploy-log",
                "event_ids": observed},
    # the host audit trail saw one more production change than CI did
    "independent": {"scope": SYSTEM, "as_of": AS_OF, "complete": True, "source_id": "CONSTRUCTED-host-audit",
                    "event_ids": observed + ["CHG-15"]},
}

policy = """# Production change management standard (CONSTRUCTED TEST POLICY)

Version v1. Applies to production systems in scope for this assessment.

1. Every change to a production system is recorded against a change request before it is executed.
2. A change request is approved before execution by an authorised approver who is not the person who implements it.
3. A change is executed only within its approved implementation window, against its approved targets, using only its approved actions, implementer and credentials.
4. The artefact deployed is the version that was approved.
5. Implementers act only under a privilege grant that is approved in advance and valid at the time of the change.
6. No change is made to a system inside a declared freeze unless an exception for that change was approved before it ran.
7. A failed change is recovered by an approved rollback or approved fix-forward, and the recovery is recorded.
8. Emergency changes follow the same rules, with approval obtained before execution through the emergency route.
9. The record of changes is complete: every production change observed on the system appears in the change record.
"""

EVIDENCE.mkdir(parents=True, exist_ok=True)
KEY.mkdir(parents=True, exist_ok=True)
(EVIDENCE / "changes.json").write_text(json.dumps(change_export, indent=2) + "\n")
(EVIDENCE / "population.json").write_text(json.dumps(population, indent=2) + "\n")
(EVIDENCE / "change_policy.md").write_text(policy)
print("wrote", *sorted(p.name for p in EVIDENCE.iterdir()))
