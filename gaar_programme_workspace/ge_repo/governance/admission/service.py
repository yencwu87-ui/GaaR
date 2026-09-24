"""WB-124: signed, fail-closed evidence admission into the *existing* review cycle.

An admission proves byte integrity, permitted provenance, preflight lexical coverage and
an explicit actor policy, NOT source authenticity or control effectiveness. A final
GovernanceResult still requires the legacy human read/compare/decision and Quality Gate.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from governance.evidence_scout.dossier import DossierStore, ImmutableBlobStore, canonical, sha256
from governance.evidence_scout.refresh import AcquisitionStore
from governance.watcher.store import HashChainStore
from governance.ai_auditor.schemas import EvidenceExaminerInput
from governance.ai_auditor.skills import evidence_examiner

ROOT = Path(__file__).resolve().parents[1]

class AdmissionError(ValueError):
    """Denied admission; no authoritative binding may be inferred."""

@dataclass(frozen=True)
class AdmissionPolicy:
    version: str = 'wb124.v1'
    min_preflight: float = 0.70
    max_age_days: int = 90
    max_blob_bytes: int = 8_000_000
    max_anchors: int = 12
    allow_service: bool = False

    def __post_init__(self):
        if not self.version or not 0 <= self.min_preflight <= 1 or self.max_age_days < 1 or self.max_blob_bytes < 1 or self.max_anchors < 1:
            raise ValueError('invalid admission policy')

class AdmissionStore:
    def __init__(self, path: str | Path | None = None):
        self.store = HashChainStore(path or os.environ.get('WB_GAAR_ADMISSION_STORE') or ROOT/'evidence_admissions.jsonl', 'gaar.evidence-admission.v1')

    def read(self) -> list[dict]:
        return self.store.read()

    def append(self, kind: str, payload: dict) -> dict:
        return self.store.append(kind, payload)

    def completed(self, dossier_id: str, cycle_id: str) -> dict | None:
        for row in reversed(self.read()):
            p = row['payload']
            if row['record_type'] == 'EvidenceCycleBound' and p.get('dossier_id') == dossier_id and p.get('cycle_id') == cycle_id:
                return p
        return None

class GovernedAdmissionService:
    @staticmethod
    def admit_investigation_source(**kwargs):
        """WB140 integrity-only admission; negative/incomplete evidence is retained.

        The legacy dossier adapter below remains a migration path. New investigation
        stages use typed source slices and do not invoke its lexical completeness gate.
        """
        from governance.investigation import admit_segments
        return admit_segments(**kwargs)

    def __init__(self, *, dossiers: DossierStore | None = None,
                 acquisitions: AcquisitionStore | None = None,
                 blobs: ImmutableBlobStore | None = None,
                 admissions: AdmissionStore | None = None,
                 policy: AdmissionPolicy | None = None):
        self.dossiers = dossiers or DossierStore()
        self.acquisitions = acquisitions or AcquisitionStore()
        self.blobs = blobs or ImmutableBlobStore(ROOT/'evidence_blobs')
        self.admissions = admissions or AdmissionStore()
        self.policy = policy or AdmissionPolicy()

    def _load(self, dossier_id: str) -> dict:
        rows = [r['payload'] for r in self.dossiers.read() if r['payload'].get('dossier_id') == dossier_id]
        if len(rows) != 1:
            raise AdmissionError('dossier must have exactly one ledger-backed version')
        dossier = rows[0]
        payload = dict(dossier)
        content_hash = payload.pop('content_hash', '')
        if content_hash != sha256(canonical(payload)):
            raise AdmissionError('dossier content hash mismatch')
        if dossier.get('binding_status') != 'PROPOSED_ONLY':
            raise AdmissionError('expected PROPOSED_ONLY dossier')
        receipts = [r['payload'] for r in self.acquisitions.read()
                    if r['payload'].get('acquisition_id') == dossier.get('acquisition_id')]
        if len(receipts) != 1:
            raise AdmissionError('dossier has no unique source acquisition receipt')
        receipt = receipts[0]
        for key in ('control_id','framework','requirement_version_id'):
            if receipt.get(key) != dossier.get(key):
                raise AdmissionError(f'acquisition/dossier {key} mismatch')
        candidates = {(c['candidate_id'], c['source_id'], c['path'], c['content_hash'])
                      for c in receipt.get('candidates') or []}
        snapshots = {(s['source_id'],s['relative_path'],s['content_sha256'])
                     for s in receipt.get('snapshots') or [] if s.get('fresh')}
        for a in dossier.get('anchors') or []:
            ref = (a.get('candidate_id'),a.get('source_id'),a.get('relative_path'),a.get('content_hash'))
            if ref not in candidates or (ref[1],ref[2],ref[3]) not in snapshots:
                raise AdmissionError('anchor is not in fresh hash-chained acquisition receipt')
        return dossier

    def _check(self, dossier: dict, *, cycle_id: str, actor_id: str, actor_type: str,
               required_elements: tuple[str, ...], now: datetime) -> tuple[dict, dict]:
        from core import cycle
        import events
        if not cycle_id or not actor_id or not actor_id.strip() or actor_id.lower() in ('system','ai','anonymous'):
            raise AdmissionError('named authorised requester and cycle required')
        if actor_type not in ('human','service'):
            raise AdmissionError('actor_type must be human or service')
        if actor_type == 'service' and not self.policy.allow_service:
            raise AdmissionError('service admission is disabled by policy')
        if now.tzinfo is None:
            raise AdmissionError('timezone-aware clock required')
        if not required_elements or not all(isinstance(x,str) and x.strip() for x in required_elements):
            raise AdmissionError('explicit governed requirement elements required')
        state = events.state(cycle_id)
        if not state:
            raise AdmissionError('no such governed review cycle')
        if state.get('control_id') != dossier['control_id'] or state.get('framework') != dossier['framework']:
            raise AdmissionError('dossier/cycle control or framework mismatch')
        req_version = (state.get('governance_context') or {}).get('requirement_version_id')
        if req_version and req_version != dossier.get('requirement_version_id'):
            raise AdmissionError('requirement version mismatch')
        if any(state.get(k) for k in ('evidence','read','proposal','decision')):
            raise AdmissionError('cycle already has evidence or advanced review state; open a fresh cycle')
        anchors = dossier.get('anchors') or []
        if not anchors or len(anchors) > self.policy.max_anchors:
            raise AdmissionError('empty or over-quota anchor set')
        listed = {r['element']:r for r in dossier.get('required_elements') or []}
        if set(listed) != set(required_elements) or any(not listed[e].get('candidate_anchors') for e in required_elements):
            raise AdmissionError('required element lacks candidate anchors')
        if dossier.get('gaps'):
            raise AdmissionError('dossier has unresolved acquisition or element gaps')
        contents = []
        seen = set()
        ages = []
        total = 0
        for anchor in anchors:
            digest = anchor.get('content_hash','')
            if digest in seen:
                raise AdmissionError('duplicate source content does not create independent anchors')
            seen.add(digest)
            if anchor.get('blob_ref') != f'sha256:{digest}':
                raise AdmissionError('blob reference/hash mismatch')
            try:
                raw = self.blobs.read(digest)
                body = raw.decode('utf-8')
            except Exception as exc:
                raise AdmissionError('CAS source re-verification failed') from exc
            if len(raw) != anchor.get('byte_length') or not anchor.get('excerpt') or ' '.join(anchor['excerpt'].split()) not in ' '.join(body.split()):
                raise AdmissionError('source byte length or verbatim quote mismatch')
            try:
                mtime = (datetime.fromtimestamp(anchor['mtime'],timezone.utc) if isinstance(anchor['mtime'],(int,float)) else datetime.fromisoformat(str(anchor['mtime']).replace('Z','+00:00')))
                if mtime.tzinfo is None: raise ValueError('naive timestamp')
                age = (now-mtime).total_seconds()/86400
                if age < -1 or age > self.policy.max_age_days: raise ValueError('stale or future evidence')
            except (ValueError,TypeError,KeyError) as exc:
                raise AdmissionError('invalid/stale evidence timestamp') from exc
            ages.append(max(0,int(age)))
            total += len(raw)
            if total > self.policy.max_blob_bytes:
                raise AdmissionError('admission byte quota exceeded')
            contents.append((anchor,body))
        # Existing Evidence Examiner is a lexical preflight, not a semantic sufficiency verdict.
        inp = EvidenceExaminerInput.model_validate({
            'control_id': dossier['control_id'], 'framework': dossier['framework'],
            'requirement_version_id': dossier['requirement_version_id'],
            'evidence_set_id':'ADMISSION_PREFLIGHT_ONLY',
            'requirement_context':[{'element_id':f'REQ-{i:02d}','text':e} for i,e in enumerate(required_elements,1)],
            'evidence_text':'\n'.join(body for _,body in contents),
            'evidence_age_days':max(ages)})
        exam = evidence_examiner.run(inp, threshold=self.policy.min_preflight, max_age_days=self.policy.max_age_days)
        if exam.recommended_action != 'NONE' or exam.open_evidence_gaps:
            raise AdmissionError('Evidence Examiner preflight blocked: '+ '; '.join(exam.open_evidence_gaps or [exam.rationale]))
        evidence_set_id = 'EVID-'+sha256(canonical({'dossier':dossier['content_hash'],
            'anchors':[a['content_hash'] for a,_ in contents], 'policy':self.policy.version}))[:32]
        chunks = [{'path':a['source_id']+'/'+a['relative_path'],'text':body} for a,body in contents]
        bundle = {'text':'\n\n'.join(f'--- Source: {c["path"]} ---\n{c["text"]}' for c in chunks),
            'chunks':chunks, 'evidence_set_id':evidence_set_id,
            'admission_dossier_id':dossier['dossier_id'], 'admission_policy_version':self.policy.version,
            'admitted_anchors':[{'anchor_id':a['anchor_id'],'sha256':a['content_hash'],
                'blob_ref':a['blob_ref'],'locator':a['source_locator']} for a,_ in contents],
            'source_integrity_verified_at':now.isoformat(),
            'fresh_until':(min((datetime.fromtimestamp(a['mtime'],timezone.utc) if isinstance(a['mtime'],(int,float)) else datetime.fromisoformat(str(a['mtime']).replace('Z','+00:00'))) for a,_ in contents)
                           +timedelta(days=self.policy.max_age_days)).isoformat()}
        return bundle,exam.model_dump(mode='json')

    def admit(self, *, dossier_id: str, cycle_id: str, actor_id: str, actor_type: str = 'human',
              required_elements: tuple[str,...], now: datetime | None = None, dry_run: bool = True) -> dict:
        """Dry-run by default. Apply requires authenticated operator boundary outside this CLI.

        Recovery: append EvidenceAdmissionPrepared, bind through core cycle, then append
        EvidenceCycleBound. Only EvidenceCycleBound represents a completed admission.
        """
        now = now or datetime.now(timezone.utc)
        existing = self.admissions.completed(dossier_id,cycle_id)
        if existing:
            raise AdmissionError('dossier already admitted to cycle; no duplicate binding')
        dossier = self._load(dossier_id)
        bundle,exam = self._check(dossier,cycle_id=cycle_id,actor_id=actor_id,
            actor_type=actor_type,required_elements=required_elements,now=now)
        result = {'status':'PREFLIGHT_PASSED' if dry_run else 'ADMITTED_AND_BOUND',
            'dossier_id':dossier_id,'cycle_id':cycle_id,'evidence_set_id':bundle['evidence_set_id'],
            'anchors':len(bundle['admitted_anchors']),'examiner_preflight':exam,
            'actor_id':actor_id,'actor_type':actor_type,'policy_version':self.policy.version,
            'note':'CAS integrity and lexical preflight do not establish control effectiveness'}
        if dry_run:
            return result
        from governance.result_integration import signer_from_env
        from core import cycle
        signer = signer_from_env()  # must fail before writes if key unavailable
        base = {**result,'bundle_hash':sha256(canonical(bundle)),
                'dossier_content_hash':dossier['content_hash'],'admitted_at':now.isoformat(),
                'evidence_items':bundle['admitted_anchors']}
        signature = signer.sign(canonical(base))
        signed = {**base,'seal':{'algorithm':'Ed25519','key_id':signer.key_id,
                    'public_key_b64':signer.public_key_b64,'signature':signature}}
        self.admissions.append('EvidenceAdmissionPrepared',signed)
        cycle.bind_admitted_evidence(cycle_id,bundle,admission_event=signed,admission_store=self.admissions,
                                    actor=actor_id)
        self.admissions.append('EvidenceCycleBound',{
            'dossier_id':dossier_id,'cycle_id':cycle_id,'evidence_set_id':bundle['evidence_set_id'],
            'admission_signature':signature,'cycle_evidence_bound':True,
            'bound_at':datetime.now(timezone.utc).isoformat()})
        return result
