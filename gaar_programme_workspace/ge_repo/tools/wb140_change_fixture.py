"""Synthetic change records: actual events are the population, not tickets."""
def package():
    return {
        "synthetic": True, "scope": "credit-platform-v2.3", "as_of": "2026-09-20T00:00:00Z",
        "policy": {"incident_lookback_hours": 24, "failed_change_requires_recovery": True},
        "collection": {"complete": True, "source_ids": ["SYNTHETIC-audit-events"],
                       "period_start": "2026-09-19T00:00:00Z", "period_end": "2026-09-20T00:00:00Z"},
        "changes": [{"event_id": "CHG-OBS-1", "ticket_id": "CR-1", "occurred_at": "2026-09-19T10:30:00Z",
            "asset_id": "db-prod", "actor_id": "operator-A", "credential_id": "shared-admin",
            "actions": ["disable_audit_logging"], "actual_spec_hash": "actual-different-version", "outcome": "failed"}],
        "tickets": [{"ticket_id": "CR-1", "status": "approved", "approved_by": "reviewer-B",
            "approved_at": "2026-09-19T11:00:00Z", "window_start": "2026-09-19T10:00:00Z",
            "window_end": "2026-09-19T12:00:00Z", "allowed_targets": ["db-prod"],
            "allowed_actions": ["apply_security_patch"], "allowed_implementers": ["operator-A"],
            "allowed_credentials": ["jit-approved-credential"], "approved_spec_hash": "approved-version"}],
        "privilege_grants": [],
        "freezes": [{"freeze_id": "FREEZE-1", "start": "2026-09-19T18:00:00+08:00",
                     "end": "2026-09-19T20:00:00+08:00", "targets": ["db-prod"]}],
        "freeze_exceptions": [],
        "incidents": [{"incident_id": "INC-1", "started_at": "2026-09-19T09:00:00Z", "assets": ["db-prod"]}],
        "recoveries": []
    }
