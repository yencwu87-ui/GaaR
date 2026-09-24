"""WB-122: scrutinizable evidence dossier from WB-120R PROPOSED_ONLY receipts.

The dossier is a source-verified proposal, not an evidence admission, assessment,
control finding or GovernanceResult. No LLM and no governance state writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from governance.watcher.store import HashChainStore


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


class EvidenceChanged(ValueError):
    """Discovery receipt no longer describes the exact source bytes."""


class ImmutableBlobStore:
    """Local content-addressed immutable snapshots. No claim of a signed origin."""
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def put(self, data: bytes) -> dict:
        digest = sha256(data)
        path = self.root / digest[:2] / digest[2:]
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if self.read(digest) != data:
                raise EvidenceChanged('content-addressed blob collision or mutation')
        else:
            # Exclusive creation: never overwrite an existing blob.
            try:
                with path.open('xb') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except FileExistsError:
                if self.read(digest) != data:
                    raise EvidenceChanged('content-addressed blob was modified')
        return {'sha256': digest, 'byte_length': len(data), 'blob_ref': f'sha256:{digest}'}

    def read(self, digest: str) -> bytes:
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('invalid content digest')
        data = (self.root / digest[:2] / digest[2:]).read_bytes()
        if sha256(data) != digest:
            raise EvidenceChanged('immutable blob verification failed')
        return data


class DossierStore:
    def __init__(self, path: str | Path | None = None):
        self.store = HashChainStore(path or os.environ.get('WB_GAAR_DOSSIER_STORE') or
            Path(__file__).resolve().parents[1] / 'evidence_dossiers.jsonl', 'gaar.evidence-dossier.v1')

    def read(self) -> list[dict]:
        return self.store.read()

    def append(self, payload: dict) -> dict:
        return self.store.append('EvidenceDossierProposed', payload)


class EvidenceAssemblyAgent:
    """Evolve Scout: acquire exact verified sources, compose bounded, challenge-ready proposal."""
    def __init__(self, approved_sources: Mapping[str, str | Path], *, blobs: ImmutableBlobStore,
                 dossiers: DossierStore):
        if not approved_sources:
            raise ValueError('explicit approved sources required')
        self.sources = {k: Path(v).expanduser().resolve(strict=True) for k, v in approved_sources.items()}
        for root in self.sources.values():
            if not root.is_dir():
                raise ValueError('approved source must be a directory')
        self.blobs = blobs
        self.dossiers = dossiers

    def assemble(self, acquisition: dict, *, assertion: str, required_elements: tuple[str, ...],
                 template: str = 'threshold_approval', now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('timezone-aware now required')
        if not isinstance(required_elements, tuple) or not all(isinstance(x, str) and x.strip() for x in required_elements):
            raise ValueError('required_elements must be a tuple of nonempty strings')
        if acquisition.get('evidence_binding_status') != 'PROPOSED_ONLY':
            raise ValueError('only proposed WB-120R acquisitions can be assembled')
        if not assertion.strip() or not acquisition.get('acquisition_id'):
            raise ValueError('assertion and acquisition receipt ID are required')
        candidates = acquisition.get('candidates') or []
        snapshots = {(r.get('source_id'), r.get('relative_path'), r.get('content_sha256'))
                     for r in acquisition.get('snapshots') or [] if r.get('fresh')}
        anchors = []
        # Validate the WHOLE candidate set before writing any dossier or blobs.
        verified = []
        for item in candidates:
            source_id = item.get('source_id')
            if (source_id, item.get('path'), item.get('content_hash')) not in snapshots:
                raise EvidenceChanged('candidate has no matching fresh snapshot receipt')
            if source_id not in self.sources:
                raise EvidenceChanged(f'unapproved source: {source_id}')
            root = self.sources[source_id]
            relative = Path(item.get('path', ''))
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                raise EvidenceChanged('invalid relative evidence path')
            path = root / relative
            if path.is_symlink():
                raise EvidenceChanged('symlink source rejected at assembly')
            target = path.resolve(strict=True)
            if not target.is_relative_to(root) or not target.is_file():
                raise EvidenceChanged('evidence escaped approved source')
            data = target.read_bytes()
            digest = sha256(data)
            if digest != item.get('content_hash'):
                raise EvidenceChanged(f'TOCTOU source hash mismatch: {source_id}/{relative}')
            try:
                body = data.decode('utf-8')
            except UnicodeError as exc:
                raise EvidenceChanged('source changed into undecodable content') from exc
            excerpt = item.get('excerpt', '')
            if not excerpt or ' '.join(excerpt.split()) not in ' '.join(body.split()):
                raise EvidenceChanged('candidate quote not present in verified source')
            verified.append((item, data, digest, str(relative), body))

        for index, (item, data, digest, relative, body) in enumerate(verified, 1):
            blob = self.blobs.put(data)
            anchors.append({'anchor_id': f'E{index:02d}', 'candidate_id': item['candidate_id'],
                'source_id': item['source_id'], 'source_class': item.get('source_class', 'unknown'),
                'relative_path': relative, 'source_locator': item.get('locator', ''),
                'content_hash': digest, 'blob_ref': blob['blob_ref'], 'byte_length': len(data),
                'excerpt': item['excerpt'], 'mtime': item.get('mtime'),
                'matched_terms': list(item.get('matched_terms', []))})
        gaps = list(acquisition.get('gaps') or [])
        elements = []
        # Use the same normalized significant-term vocabulary as Scout. Comparing
        # Scout's stop-word-filtered matches against every raw word made longer
        # elements (for example fairness/stakeholder-impact) mathematically harder
        # to anchor even when the evidence visibly covered them.
        from .agent import _terms
        for element in required_elements:
            terms = _terms(element)
            # Lexical linkage is for investigation, NOT proof of control satisfaction.
            linked = [a['anchor_id'] for a in anchors if terms and
                      len(terms & set(a['matched_terms'])) >= max(1, len(terms)//2)]
            elements.append({'element': element, 'candidate_anchors': linked,
                             'claim_status': 'CANDIDATE_SUPPORT_ONLY' if linked else 'UNSUPPORTED'})
            if not linked:
                gaps.append(f'unsupported_element: {element}')
        challenge = []
        def point(category, question, refs, investigation, unresolved):
            challenge.append({'point_id': f'CP{len(challenge)+1:02d}', 'category': category,
                'question': question, 'anchor_ids': refs, 'suggested_investigation': investigation,
                'gap_if_unresolved': unresolved, 'status': 'OPEN_FOR_SCRUTINY'})
        point('temporal', 'Do the anchored approval and deployment timestamps prove approval preceded deployment?',
              [a['anchor_id'] for a in anchors], 'Compare original approval and deployment event timestamps, actors and clocks.',
              'Temporal precedence not established by dossier alone.')
        point('origin', 'Are these records truly independent sources rather than duplicated content or a shared origin?',
              [a['anchor_id'] for a in anchors], 'Compare source IDs, origin metadata and exact content hashes.',
              'Independent corroboration not established.')
        for elt in elements:
            if not elt['candidate_anchors']:
                point('completeness', f'Where is primary evidence for: {elt["element"]}?', [],
                      'Collect a source record with an exact locator and verify its receipt.',
                      f'Unproven required element: {elt["element"]}')
        point('interpretation', 'Does each excerpt support the control assertion, rather than merely mention its vocabulary?',
              [a['anchor_id'] for a in anchors], 'Read the entire immutable source blob and test alternative explanations.',
              'Lexical relevance is not demonstrated operating effectiveness.')
        if len({a['content_hash'] for a in anchors}) < len(anchors):
            point('origin', 'Does duplicate content overstate source diversity?', [a['anchor_id'] for a in anchors],
                  'Review exact duplicate blobs and source origin.', 'Source independence may be overstated.')
        limitations = [
            'The dossier is PROPOSED_ONLY; no candidate is admitted into an authoritative evidence set.',
            'Candidate keyword matches do not prove control design or operating effectiveness.',
            'Approval-before-deployment chronology is not established until primary event timestamps are independently checked.',
            'Source authenticity is not proven solely by a SHA-256 integrity receipt.',
        ]
        if acquisition.get('quota_hit'):
            limitations.append('The source scan reached its quota; candidate coverage is incomplete.')
        if gaps:
            limitations.append('Open evidence gaps remain; see the explicit gaps list.')
        base = {'schema_version': 'gaar.evidence-dossier.v1',
                'dossier_id': 'ED-'+uuid.uuid5(uuid.NAMESPACE_URL,
                    acquisition['acquisition_id']+':'+template+':'+assertion).hex,
                'acquisition_id': acquisition['acquisition_id'], 'control_id': acquisition['control_id'],
                'framework': acquisition.get('framework',''), 'requirement_version_id': acquisition.get('requirement_version_id',''),
                'evidence_set_id': 'UNBOUND_CANDIDATE_SET', 'binding_status': 'PROPOSED_ONLY',
                'template': template, 'control_assertion': assertion,
                'reconstruction': [
                    {'anchor_id': a['anchor_id'], 'observation': 'Source candidate preserved for scrutiny; operational sequence not inferred.',
                     'source_id': a['source_id']} for a in anchors],
                'anchors': anchors, 'required_elements': elements,
                'demonstrated': ['Source snapshot and exact excerpt verified for '+a['anchor_id'] for a in anchors],
                'limitations': limitations, 'gaps': list(dict.fromkeys(gaps)),
                'challenge_surface': challenge, 'assembled_at': now.isoformat(),
                'assembled_by': 'evidence-scout-assembly-agent'}
        base['content_hash'] = sha256(canonical(base))
        self.dossiers.append(base)
        return base


def render_markdown(dossier: dict) -> str:
    lines = [f'# Evidence Dossier — {dossier["framework"]} {dossier["control_id"]}',
             f'**Binding:** {dossier["binding_status"]} · **Acquisition:** `{dossier["acquisition_id"]}`',
             f'**Dossier hash:** `{dossier["content_hash"]}`', '',
             '## Control assertion (to be scrutinised)', dossier['control_assertion'], '',
             '## Source-verified anchors']
    for a in dossier['anchors']:
        lines.extend([f'### {a["anchor_id"]} — {a["source_id"]}/{a["relative_path"]}',
                      f'Blob: `{a["blob_ref"]}` · SHA-256: `{a["content_hash"]}`',
                      f'> {a["excerpt"]}', ''])
    lines.extend(['## Reconstructed operation (evidence inventory, not verified chronology)'])
    lines.extend([f'- {r["anchor_id"]}: {r["observation"]}' for r in dossier['reconstruction']])
    lines.extend(['', '## Candidate element coverage'])
    lines.extend([f'- {r["element"]}: {r["claim_status"]} ({", ".join(r["candidate_anchors"]) or "no anchor"})'
                  for r in dossier['required_elements']])
    lines.extend(['', '## What is demonstrated (integrity only)'])
    lines.extend([f'- {v}' for v in dossier['demonstrated']])
    lines.extend(['', '## What is NOT demonstrated'])
    lines.extend([f'- {v}' for v in dossier['limitations']])
    lines.extend(['', '## Scrutinise this evidence'])
    for p in dossier['challenge_surface']:
        lines.extend([f'### {p["point_id"]} · {p["category"]}',p['question'],
                      f'Anchors: {", ".join(p["anchor_ids"]) or "none — missing evidence"}',
                      f'Investigation: {p["suggested_investigation"]}',
                      f'If unresolved: {p["gap_if_unresolved"]}', ''])
    return '\n'.join(lines)+'\n'
