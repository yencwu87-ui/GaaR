"""WB-122: source integrity, scrutiny, and no authority escalation."""
from __future__ import annotations
import os
from datetime import datetime,timezone
from pathlib import Path
import pytest
from governance.evidence_scout import EvidenceSource
from governance.evidence_scout.refresh import RefreshAgent,RefreshPolicy,AcquisitionStore
from governance.evidence_scout.store import ScoutStore
from governance.evidence_scout.dossier import EvidenceAssemblyAgent,ImmutableBlobStore,DossierStore,EvidenceChanged,canonical,sha256,render_markdown

NOW=datetime(2026,9,19,tzinfo=timezone.utc)

def fixture(tmp_path,*,policy=None):
    root=tmp_path/'approved';root.mkdir()
    records={
        'policy.md':'Governance threshold policy requires approval before deployment. The threshold policy is documented.',
        'pull_request.md':'Pull request 142 describes threshold configuration review and approval before deployment.',
        'deployment.md':'Deployment log lists threshold configuration and deployment record 142.',
    }
    for filename,body in records.items():
        file=root/filename;file.write_text(body);os.utime(file,(NOW.timestamp(),NOW.timestamp()))
    acq=AcquisitionStore(tmp_path/'acquisitions.jsonl')
    agent=RefreshAgent([EvidenceSource('approved_repo',str(root))],policy=policy or RefreshPolicy(),
                       acquisition_store=acq,scout_store=ScoutStore(tmp_path/'scout.jsonl'))
    result=agent.run('2.1','SAFR','threshold approval deployment',('threshold policy','approval before deployment'),
                     requirement_version_id='req_v2.4',now=NOW)
    assembly=EvidenceAssemblyAgent({'approved_repo':root},
                                   blobs=ImmutableBlobStore(tmp_path/'blobs'),
                                   dossiers=DossierStore(tmp_path/'dossiers.jsonl'))
    return root,result,assembly,acq

def assemble(a,result,**kwargs):
    return a.assemble(result,assertion='Threshold approval before deployment',
                      required_elements=('threshold policy','approval before deployment'),now=NOW,**kwargs)

def test_dossier_proposed_only_and_scrutinizable(tmp_path):
    root,result,a,acq=fixture(tmp_path)
    d=assemble(a,result)
    assert d['binding_status']=='PROPOSED_ONLY'
    assert len(d['anchors'])>=2
    assert len(d['challenge_surface'])>=3
    assert {'temporal','origin','interpretation'}.issubset({p['category'] for p in d['challenge_surface']})
    assert d['limitations'] and all(x['content_hash']==sha256(a.blobs.read(x['content_hash'])) for x in d['anchors'])
    assert d['content_hash']==sha256(canonical({k:v for k,v in d.items() if k!='content_hash'}))
    assert len(a.dossiers.read())==1
    assert len(acq.read())==1  # no acquisition history rewrite
    assert 'Scrutinise this evidence' in render_markdown(d)
    assert 'CURRENT' not in d and 'maturity' not in d

def test_modified_since_scout_receipt_fails_closed_without_dossier_or_blobs(tmp_path):
    root,result,a,_=fixture(tmp_path)
    (root/result['candidates'][0]['path']).write_text('edited after receipt')
    with pytest.raises(EvidenceChanged,match='TOCTOU'):
        assemble(a,result)
    assert a.dossiers.read()==[]
    assert not (tmp_path/'blobs').exists()

def test_symlink_replaced_after_discovery_rejected(tmp_path):
    root,result,a,_=fixture(tmp_path)
    path=root/result['candidates'][0]['path'];path.unlink()
    outside=tmp_path/'outside.md';outside.write_text('fake evidence')
    path.symlink_to(outside)
    with pytest.raises(EvidenceChanged):assemble(a,result)
    assert not a.dossiers.read()

def test_traversal_and_unapproved_source_rejected(tmp_path):
    _,result,a,_=fixture(tmp_path)
    result['candidates'][0]['path']='../outside.md'
    with pytest.raises(EvidenceChanged):assemble(a,result)
    result['candidates'][0]['source_id']='invented'
    with pytest.raises(EvidenceChanged):assemble(a,result)

def test_quote_must_be_verbatim(tmp_path):
    _,result,a,_=fixture(tmp_path)
    result['candidates'][0]['excerpt']='fabricated approved by regulator'
    with pytest.raises(EvidenceChanged,match='quote'):
        assemble(a,result)

def test_no_candidate_is_not_a_successful_control(tmp_path):
    root,result,a,_=fixture(tmp_path)
    result['candidates']=[]
    d=assemble(a,result)
    assert not d['anchors']
    assert all(r['claim_status']=='UNSUPPORTED' for r in d['required_elements'])
    assert any(p['category']=='completeness' for p in d['challenge_surface'])
    assert d['binding_status']=='PROPOSED_ONLY'

def test_integrity_receipt_not_fake_signature(tmp_path):
    _,result,a,_=fixture(tmp_path)
    d=assemble(a,result)
    assert 'signed' not in str(d).lower() and 'signature' not in d
    assert 'authenticity is not proven' in ' '.join(d['limitations']).lower()

def test_blob_is_immutable_and_corruption_detected(tmp_path):
    _,result,a,_=fixture(tmp_path)
    d=assemble(a,result)
    digest=d['anchors'][0]['content_hash'];path=a.blobs.root/digest[:2]/digest[2:]
    path.write_text('corrupted')
    with pytest.raises(EvidenceChanged,match='verification'):
        a.blobs.read(digest)
    with pytest.raises(EvidenceChanged):assemble(a,result)

def test_deterministic_output_except_assembly_timestamp(tmp_path):
    _,result,a,_=fixture(tmp_path)
    d1=assemble(a,result)
    d2=assemble(a,result)
    assert d1==d2
    assert len(a.dossiers.read())==2  # append-only, repeat run is inspectable

def test_no_governance_transitions_generated(tmp_path):
    _,result,a,_=fixture(tmp_path)
    d=assemble(a,result)
    assert not (tmp_path/'governance_events.jsonl').exists()
    assert not (tmp_path/'quality_gate.jsonl').exists()
    assert d['evidence_set_id']=='UNBOUND_CANDIDATE_SET'

def test_scanned_quota_gap_is_retained(tmp_path):
    _,result,a,_=fixture(tmp_path,policy=RefreshPolicy(max_files_scanned=1))
    d=assemble(a,result)
    assert d['binding_status']=='PROPOSED_ONLY'
    assert any('quota' in x for x in d['limitations'])

def test_receipt_binding_and_contract_rejected(tmp_path):
    _,result,a,_=fixture(tmp_path)
    result['evidence_binding_status']='ADMITTED'
    with pytest.raises(ValueError):assemble(a,result)
    result['evidence_binding_status']='PROPOSED_ONLY'
    with pytest.raises(ValueError):a.assemble(result,assertion='',required_elements=tuple())
    with pytest.raises(ValueError):a.assemble(result,assertion='something',required_elements=['list not tuple'])
