from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
import pytest
from governance.evidence_scout import EvidenceSource
from governance.evidence_scout.refresh import RefreshAgent, RefreshPolicy, AcquisitionStore
from governance.evidence_scout.store import ScoutStore

NOW=datetime(2026,9,19,tzinfo=timezone.utc)

def agent(tmp_path,roots,**kwargs):
    return RefreshAgent(roots,policy=RefreshPolicy(**kwargs),acquisition_store=AcquisitionStore(tmp_path/'receipts.jsonl'),scout_store=ScoutStore(tmp_path/'scout.jsonl'))

def test_refresh_approved_root_receipt_is_append_only(tmp_path):
    root=tmp_path/'approved'; root.mkdir()
    file=root/'policy.md'; file.write_text('governance thresholds documented and approved before deployment')
    os.utime(file,(NOW.timestamp(),NOW.timestamp()))
    a=agent(tmp_path,[EvidenceSource('repo',str(root))])
    r=a.run('2.1','SAFR','governance thresholds approved before deployment',('governance thresholds approved',),now=NOW)
    assert r['recommended_action']=='REVIEW_CANDIDATES'
    assert r['evidence_binding_status']=='PROPOSED_ONLY'
    assert len(r['candidates'])==1
    assert len(r['snapshots'][0]['content_sha256'])==64
    a.run('2.1','SAFR','governance thresholds approved before deployment',(),now=NOW)
    assert len(a.acquisitions.read())==2

def test_refresh_stale_fails_closed(tmp_path):
    root=tmp_path/'approved'; root.mkdir()
    file=root/'stale.md'; file.write_text('governance thresholds approved')
    os.utime(file,(NOW.timestamp()-91*86400,NOW.timestamp()-91*86400))
    r=agent(tmp_path,[EvidenceSource('repo',str(root))]).run('c','MAS','governance thresholds',('approved thresholds',),now=NOW)
    assert not r['candidates'] and len(r['stale_excluded'])==1
    assert r['recommended_action']=='COLLECT_MORE'

def test_refresh_requires_independent_source_diversity(tmp_path):
    root=tmp_path/'approved'; root.mkdir()
    p=root/'one.md';p.write_text('governance approval deployment');os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    r=agent(tmp_path,[EvidenceSource('repo',str(root))],min_sources=2).run('c','MAS','governance approval',(),now=NOW)
    assert 'source_diversity: 1 < 2' in r['gaps']
    assert r['recommended_action']=='COLLECT_MORE'

def test_refresh_quota_no_fabrication(tmp_path):
    root=tmp_path/'approved';root.mkdir()
    for i in range(3):
        p=root/f'{i}.md';p.write_text('governance approval deployment'+str(i));os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    r=agent(tmp_path,[EvidenceSource('repo',str(root))],max_files_scanned=1).run('c','MAS','governance approval',(),now=NOW)
    assert r['quota_hit'] and len(r['snapshots'])==1
    assert r['recommended_action']=='COLLECT_MORE'

def test_refresh_symlink_escape_and_binary_filtered(tmp_path):
    root=tmp_path/'approved';root.mkdir()
    outside=tmp_path/'outside.md';outside.write_text('governance approval deployment')
    (root/'escape.md').symlink_to(outside)
    (root/'other.bin').write_bytes(b'governance approval deployment')
    r=agent(tmp_path,[EvidenceSource('repo',str(root))]).run('c','MAS','governance approval',(),now=NOW)
    assert not r['snapshots'] and not r['candidates']

def test_refresh_input_contract_rejects_malformed_elements(tmp_path):
    a=agent(tmp_path,[])
    with pytest.raises(TypeError):
        a.run('c','MAS','requirement','not tuple',now=NOW)

def test_refresh_score_is_preflight_not_quality_verdict(tmp_path):
    root=tmp_path/'approved';root.mkdir()
    p=root/'one.md';p.write_text('governance approval deployment');os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    r=agent(tmp_path,[EvidenceSource('repo',str(root))]).run('c','MAS','governance approval',('approval deployment',),now=NOW)
    assert 'preflight' in r
    assert 'sufficiency_score' in r['preflight']
    assert 'maturity' not in str(r).lower()
    assert 'validity_state' not in str(r).lower()


def test_refresh_exact_control_is_ranked_before_more_similar_cross_control(tmp_path):
    root=tmp_path/'approved';root.mkdir()
    exact=root/'M3.6_Evaluation.md'
    exact.write_text('Framework: MAS\nControl ID: M3.6\nindependent validation scope threshold')
    cross=root/'M2.4_Risk.md'
    cross.write_text('Framework: MAS\nControl ID: M2.4\nindependent validation scope threshold methods governance approval evidence')
    for p in (exact,cross):os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    r=agent(tmp_path,[EvidenceSource('repo',str(root))]).run(
        'M3.6','MAS','independent validation scope threshold methods',
        ('independent validation scope',),now=NOW)
    assert r['candidates'][0]['path']=='M3.6_Evaluation.md'
    assert r['candidates'][0]['control_match']=='EXACT_CONTROL'
    assert r['retrieval_policy']['name']=='exact-control-first-v1'


def test_refresh_without_governed_elements_fails_closed(tmp_path):
    root=tmp_path/'approved';root.mkdir()
    p=root/'M3.6_Evaluation.md';p.write_text('Framework: MAS\nControl ID: M3.6\nvalidation evidence')
    os.utime(p,(NOW.timestamp(),NOW.timestamp()))
    r=agent(tmp_path,[EvidenceSource('repo',str(root))]).run(
        'M3.6','MAS','validation evidence',(),now=NOW)
    assert r['preflight']['evaluation_status']=='NOT_EVALUATED'
    assert r['preflight']['sufficiency_score'] is None
    assert r['recommended_action']=='COLLECT_MORE'
