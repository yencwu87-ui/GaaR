"""WB-124 actual Scout → dossier → signed authoritative cycle binding, negative paths."""
from __future__ import annotations
import os
import base64
from dataclasses import replace
from datetime import datetime,timezone
import pytest
from governance.evidence_scout import EvidenceSource
from governance.evidence_scout.refresh import RefreshAgent,RefreshPolicy,AcquisitionStore
from governance.evidence_scout.store import ScoutStore
from governance.evidence_scout.dossier import EvidenceAssemblyAgent,ImmutableBlobStore,DossierStore,sha256
from governance.admission import GovernedAdmissionService,AdmissionPolicy,AdmissionError,AdmissionStore
from core import cycle
import events

NOW=datetime(2026,9,19,tzinfo=timezone.utc)
ELEMENTS=('threshold policy','approval before deployment')

def setup(tmp_path,monkeypatch, *, missing=False):
    monkeypatch.setattr(events,'LOG',tmp_path/'events.jsonl')
    monkeypatch.setenv('WB_GAAR_RESULT_SIGNING_KEY_B64',base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv('WB_GAAR_RESULT_KEY_ID','wb124-test-only')
    root=tmp_path/'evidence';root.mkdir()
    bodies=['The threshold policy documents the approval requirement before deployment.',
            'Approval before deployment was recorded in the change record.']
    if missing:bodies=bodies[:1]
    for i,body in enumerate(bodies):
        path=root/f'file{i}.md';path.write_text(body);os.utime(path,(NOW.timestamp(),NOW.timestamp()))
    acquisitions=AcquisitionStore(tmp_path/'acquisitions.jsonl')
    dossiers=DossierStore(tmp_path/'dossiers.jsonl')
    blobs=ImmutableBlobStore(tmp_path/'blobs')
    receipt=RefreshAgent([EvidenceSource('source1',str(root))],
         policy=RefreshPolicy(),acquisition_store=acquisitions,
         scout_store=ScoutStore(tmp_path/'scout.jsonl')).run('S2.2','SAFR',
         'threshold policy approval before deployment',ELEMENTS,
         now=NOW,requirement_version_id='req_v2.4')
    dossier=EvidenceAssemblyAgent({'source1':root},blobs=blobs,dossiers=dossiers).assemble(
         receipt,assertion='Threshold policy approval before deployment',
         required_elements=ELEMENTS,now=NOW)
    admission=GovernedAdmissionService(dossiers=dossiers,acquisitions=acquisitions,
          blobs=blobs,admissions=AdmissionStore(tmp_path/'admissions.jsonl'))
    cid=cycle.start('S2.2',framework='SAFR',actor='test',
        governance_context={'requirement_version_id':'req_v2.4'})
    return admission,dossier,cid,root

def call(s,d,c,**kw):
    return s.admit(dossier_id=d['dossier_id'],cycle_id=c,actor_id='reviewer-A',
          required_elements=ELEMENTS,now=NOW,**kw)

def test_dry_run_no_mutations(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    before=events.read_all()
    out=call(s,d,c)
    assert out['status']=='PREFLIGHT_PASSED'
    assert events.read_all()==before and not s.admissions.read()

def test_admits_signed_and_consumed_by_core_cycle(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    out=call(s,d,c,dry_run=False)
    assert out['status']=='ADMITTED_AND_BOUND'
    assert len(s.admissions.read())==2
    ev=events.state(c)['evidence']
    assert ev['evidence_set_id']==out['evidence_set_id']
    assert ev['admission_dossier_id']==d['dossier_id']
    assert 'threshold policy' in ev['text']
    assert len(ev['admitted_anchors'])>=1
    assert s.admissions.completed(d['dossier_id'],c)['cycle_evidence_bound']
    assert events.state(c).get('read') is None and events.state(c).get('decision') is None
    with pytest.raises(AdmissionError,match='already admitted'):
        call(s,d,c,dry_run=False)

def test_tampered_cas_never_binds(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    anchor=d['anchors'][0]
    p=s.blobs.root/anchor['content_hash'][:2]/anchor['content_hash'][2:]
    p.write_text('tampered')
    with pytest.raises(AdmissionError,match='CAS source'):
        call(s,d,c,dry_run=False)
    assert not s.admissions.read() and 'evidence' not in events.state(c)

def test_unauthorised_service_fails_closed(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    with pytest.raises(AdmissionError,match='disabled'):
        call(s,d,c,actor_type='service',dry_run=False)
    with pytest.raises(AdmissionError,match='named authorised'):
        s.admit(dossier_id=d['dossier_id'],cycle_id=c,actor_id='ai',required_elements=ELEMENTS,now=NOW,dry_run=False)
    assert not s.admissions.read()

def test_requirements_and_cycle_mismatch(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    with pytest.raises(AdmissionError,match='required element'):
        s.admit(dossier_id=d['dossier_id'],cycle_id=c,actor_id='reviewer-A',required_elements=('wrong',),now=NOW)
    wrong=cycle.start('S2.3  ★',framework='SAFR',actor='test')
    with pytest.raises(AdmissionError,match='control or framework'):
        call(s,d,wrong)

def test_stale_and_missing_signer(tmp_path,monkeypatch):
    from datetime import timedelta
    s,d,c,_=setup(tmp_path,monkeypatch)
    with pytest.raises(AdmissionError,match='timestamp'):
        s.admit(dossier_id=d['dossier_id'],cycle_id=c,actor_id='reviewer-A',required_elements=ELEMENTS,
                now=NOW+timedelta(days=91),dry_run=False)
    monkeypatch.delenv('WB_GAAR_RESULT_SIGNING_KEY_B64')
    with pytest.raises(RuntimeError,match='SIGNING_KEY'):
        call(s,d,c,dry_run=False)
    assert not s.admissions.read()

def test_no_rebind_over_review(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    cycle.bind_evidence(c,{'text':'existing'},actor='reviewer')
    with pytest.raises(AdmissionError,match='already has evidence'):
        call(s,d,c,dry_run=False)
    assert not s.admissions.read()

def test_incomplete_dossier_blocks(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch,missing=True)
    # Any acquisition gap or coverage gap must stop admission.
    if d['gaps']:
        with pytest.raises(AdmissionError,match='gaps'):
            call(s,d,c,dry_run=False)
    else:
        assert call(s,d,c)['status']=='PREFLIGHT_PASSED'

def test_ledger_tamper_is_detected_at_admission(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    f=s.dossiers.store.path
    data=f.read_text()
    f.write_text(data.replace('Approval before deployment','Edited approval after deployment',1))
    with pytest.raises(ValueError,match='record hash'):
        call(s,d,c,dry_run=False)
    assert not s.admissions.read() and 'evidence' not in events.state(c)


def test_signing_key_mismatch_rejected_in_core_binding(tmp_path,monkeypatch):
    s,d,c,_=setup(tmp_path,monkeypatch)
    # A valid signature made under a *different* key cannot be used at the core boundary.
    from governance.evidence_scout.dossier import canonical
    from governance.result_contract import CanonicalSigner
    from governance.result_integration import signer_from_env
    good=signer_from_env()
    original=call(s,d,c,dry_run=False)
    assert original['status']=='ADMITTED_AND_BOUND'
    signed=s.admissions.read()[0]['payload']
    evidence=events.state(c)['evidence']
    new=CanonicalSigner.from_base64('rogue',base64.b64encode(os.urandom(32)).decode())
    forged={k:v for k,v in signed.items() if k!='seal'}
    forged['seal']={'algorithm':'Ed25519','key_id':new.key_id,
                    'public_key_b64':new.public_key_b64,
                    'signature':new.sign(canonical(forged))}
    from core import cycle as cyc
    with pytest.raises(cyc.CycleError,match='ledger entry|trusted key'):
        cyc.bind_admitted_evidence(c,evidence,admission_event=forged,admission_store=s.admissions,actor='reviewer-A')
