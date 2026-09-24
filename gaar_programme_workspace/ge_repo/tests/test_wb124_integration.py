"""End-to-end binding, package truthfulness and result identity, isolated event ledger."""
from __future__ import annotations
import pytest
from datetime import datetime,timezone
from governance.audit_package import prepare_package,ReviewContext
from governance.admission import AdmissionError
from test_wb124_admission import setup,call,NOW
import events


def test_admitted_dossier_is_cycle_evidence_but_not_decided(tmp_path,monkeypatch):
    service,dossier,cid,_=setup(tmp_path,monkeypatch)
    baseline=prepare_package(cycle_id=cid,dossier=dossier,context=ReviewContext())
    assert baseline['binding_status']=='PROPOSED_ONLY'
    assert 'proposed_scout_dossier_requires_governed_evidence_admission' in baseline['blockers']
    admitted=call(service,dossier,cid,dry_run=False)
    # Admission proof must be discovered through configured WB124 admission ledger.
    monkeypatch.setenv('WB_GAAR_ADMISSION_STORE',str(service.admissions.store.path))
    package=prepare_package(cycle_id=cid,dossier=dossier,context=ReviewContext())
    assert package['binding_status']=='ADMITTED_IN_CYCLE'
    assert 'proposed_scout_dossier_requires_governed_evidence_admission' not in package['blockers']
    assert package['requires_human_decision']
    assert package['status']=='CHECKPOINT_REQUIRED'  # blind-read/assessment remains
    assert not events.state(cid).get('decision')
    assert events.state(cid)['evidence']['evidence_set_id']==admitted['evidence_set_id']
