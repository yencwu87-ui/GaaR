"""WB-120R governed local-evidence refresh; proposals only, never writes a review cycle."""
from __future__ import annotations
import hashlib
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from governance.watcher.store import HashChainStore
from governance.ai_auditor.schemas import EvidenceExaminerInput
from governance.ai_auditor.skills.evidence_examiner import run as examine
from .agent import EvidenceScoutAgent
from .models import EvidenceSource, ScoutRequest
from .store import ScoutStore


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalise_identity(value: str) -> str:
    return re.sub(r"[^A-Z0-9.]", "", str(value or "").upper())


def _document_identity(relative_path: str, body: str) -> tuple[str, str]:
    """Return declared framework/control metadata without inferring a verdict.

    Synthetic and governed evidence packs declare these fields in their header.  The
    filename fallback makes the priority guard useful for plain local evidence while
    keeping unlabelled documents available as supplements.
    """
    framework_match = re.search(r"(?im)^\s*framework\s*:\s*([^\n#]+)", body[:4000])
    control_match = re.search(r"(?im)^\s*control\s+id\s*:\s*([^\s#]+)", body[:4000])
    name_match = re.match(r"(?i)^([A-Z]+\d+(?:[.]\d+)*)[_\s-]", Path(relative_path).name)
    framework = str(framework_match.group(1)).strip() if framework_match else ""
    control_id = str(control_match.group(1)).strip() if control_match else (name_match.group(1) if name_match else "")
    return framework, control_id


def _identity_priority(query_framework: str, query_control_id: str,
                       detected_framework: str, detected_control_id: str) -> tuple[int, str]:
    qf = _normalise_identity(query_framework)
    qc = _normalise_identity(query_control_id)
    df = _normalise_identity(detected_framework)
    dc = _normalise_identity(detected_control_id)
    if dc == qc and (not df or not qf or df == qf):
        return 0, "EXACT_CONTROL"
    if df and qf and df == qf:
        return 1, "SAME_FRAMEWORK_SUPPLEMENT"
    if not df and not dc:
        return 2, "UNCLASSIFIED_SUPPLEMENT"
    return 3, "CROSS_CONTROL_SUPPLEMENT"


@dataclass(frozen=True)
class RefreshPolicy:
    max_age_days: int = 90
    min_sources: int = 1
    max_files_scanned: int = 300
    max_bytes_scanned: int = 8_000_000
    max_candidates: int = 12
    min_score: float = 0.05
    def __post_init__(self):
        if self.max_age_days < 1 or self.min_sources < 1 or self.max_files_scanned < 1 or self.max_bytes_scanned < 1 or self.max_candidates < 1:
            raise ValueError('refresh policy requires positive limits')
        if not 0 <= self.min_score <= 1:
            raise ValueError('min_score out of range')


class AcquisitionStore:
    """Append-only receipts; registration means proposal, NOT evidence binding."""
    def __init__(self, path: str | Path | None = None):
        path = path or os.environ.get('WB_GAAR_SCOUT_ACQUISITION_STORE') or Path(__file__).resolve().parents[1] / 'evidence_acquisitions.jsonl'
        self.store = HashChainStore(path, 'gaar.scout-acquisition.v1')
    def read(self):
        return self.store.read()
    def register(self, payload):
        return self.store.append('EvidenceAcquisitionCandidate', payload)


class RefreshAgent:
    """Approved local-root refresh with immutable snapshot receipts and honest preflight.

    No network connectors, review-cycle mutations, quality verdicts or human actions.
    """
    def __init__(self, sources: Iterable[EvidenceSource], *, policy: RefreshPolicy | None = None,
                 acquisition_store: AcquisitionStore | None = None, scout_store: ScoutStore | None = None):
        self.sources = tuple(sources)
        self.policy = policy or RefreshPolicy()
        self.acquisitions = acquisition_store or AcquisitionStore()
        self.scout_store = scout_store or ScoutStore()

    def run(self, control_id: str, framework: str, requirement: str, elements: tuple[str, ...], *,
            now: datetime | None = None, requirement_version_id: str = '') -> dict:
        if not isinstance(elements, tuple) or not all(isinstance(e, str) for e in elements):
            raise TypeError('elements must be a tuple of strings')
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('now must be timezone-aware')
        # Rebuild approved-root source trees as a bounded snapshot. Reject symlink escapes.
        remaining_files = self.policy.max_files_scanned
        remaining_bytes = self.policy.max_bytes_scanned
        roots = []
        freshness_excluded = []
        quota_hit = False
        snapshots = []
        for source in self.sources:
            root = Path(source.root).expanduser().resolve()
            if not root.is_dir():
                continue
            roots.append(source)
            for path in sorted(root.rglob('*')):
                if not path.is_file() or path.is_symlink() or path.suffix.lower() not in source.allowed_extensions:
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                if remaining_files <= 0:
                    quota_hit = True
                    break
                try:
                    stat = path.stat()
                    if stat.st_size > source.max_file_bytes:
                        continue
                    if stat.st_size > remaining_bytes:
                        quota_hit = True
                        break
                    data = path.read_bytes()
                except (OSError, UnicodeError):
                    continue
                remaining_files -= 1
                remaining_bytes -= len(data)
                age = max(0.0, (now.timestamp() - stat.st_mtime) / 86400)
                receipt = {'source_id': source.source_id, 'relative_path': str(path.relative_to(root)),
                           'content_sha256': _sha(data), 'byte_length': len(data),
                           'mtime_utc': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                           'age_days': round(age, 3), 'fresh': age <= self.policy.max_age_days}
                snapshots.append(receipt)
                if not receipt['fresh']:
                    freshness_excluded.append(receipt)
            if quota_hit:
                break
        # Scout uses only current approved, in-quota content. Disable direct rglob scan of
        # stale/unscanned files by building candidates from exact snapshotted path set.
        from .agent import _terms, _hash
        from .models import EvidenceCandidate
        terms = _terms(' '.join((requirement, *elements)))
        source_map = {s.source_id: s for s in roots}
        fresh = [r for r in snapshots if r['fresh']]
        candidates = []
        for receipt in fresh:
            source = source_map[receipt['source_id']]
            path = Path(source.root).expanduser().resolve() / receipt['relative_path']
            try:
                data = path.read_bytes()
                if _sha(data) != receipt['content_sha256']:
                    continue  # file changed during scan; fail closed
                body = data.decode('utf-8')
            except (OSError, UnicodeError):
                continue
            hits = tuple(sorted(terms & _terms(body)))
            overlap = len(hits) / len(terms) if terms else 0.
            if overlap < self.policy.min_score:
                continue
            detected_framework, detected_control = _document_identity(receipt['relative_path'], body)
            priority, match_kind = _identity_priority(
                framework, control_id, detected_framework, detected_control
            )
            candidate = EvidenceCandidate(
                candidate_id='EC-'+_hash(source.source_id+':'+receipt['relative_path']+':'+receipt['content_sha256'])[:24],
                source_id=source.source_id,
                path=receipt['relative_path'],
                locator=path.as_uri(),
                content_hash=receipt['content_sha256'],
                score=min(1., overlap + (.02 if source.trusted else 0)),
                matched_terms=hits,
                excerpt=' '.join(body.split())[:800],
                mtime=path.stat().st_mtime,
                source_class=source.source_class,
                trusted=source.trusted,
                detected_framework=detected_framework,
                detected_control_id=detected_control,
                control_match=match_kind,
            )
            candidates.append((priority, candidate))
        candidates.sort(key=lambda item: (item[0], -item[1].score, -item[1].mtime,
                                          item[1].source_id, item[1].path))
        unique = []
        seen = set()
        for _, item in candidates:
            if item.content_hash not in seen:
                unique.append(item)
                seen.add(item.content_hash)
            if len(unique) >= self.policy.max_candidates:
                break
        body = '\n'.join(c.excerpt for c in unique)
        # Examiner's deterministic score is a triage measure, not a sufficiency verdict.
        inp = EvidenceExaminerInput.model_validate({'control_id': control_id, 'framework': framework,
            'requirement_version_id': requirement_version_id or 'UNVERSIONED_PROPOSAL',
            'evidence_set_id': 'UNBOUND_CANDIDATE_SET', 'evidence_text': body,
            'requirement_context': [{'element_id': f'e{i}', 'text': e} for i,e in enumerate(elements,1)]})
        preflight = examine(inp, max_age_days=self.policy.max_age_days)
        source_count = len({c.source_id for c in unique})
        gaps = list(preflight.open_evidence_gaps)
        if source_count < self.policy.min_sources:
            gaps.append(f'source_diversity: {source_count} < {self.policy.min_sources}')
        if freshness_excluded:
            gaps.append(f'stale_items: {len(freshness_excluded)} excluded')
        if quota_hit:
            gaps.append('scan_quota_reached: results incomplete')
        action = ('REVIEW_CANDIDATES'
                  if unique and source_count >= self.policy.min_sources and not quota_hit
                  and preflight.evaluation_status == 'EVALUATED' and not gaps
                  else 'COLLECT_MORE')
        match_counts = {}
        for item in unique:
            match_counts[item.control_match] = match_counts.get(item.control_match, 0) + 1
        payload = {'acquisition_id': 'EA-'+uuid.uuid4().hex, 'control_id': control_id,
            'framework': framework, 'requirement_version_id': requirement_version_id,
            'observed_at': now.isoformat(), 'candidates': [c.to_dict() for c in unique],
            'snapshots': snapshots, 'stale_excluded': freshness_excluded,
            'source_count': source_count, 'gaps': gaps,
            'preflight': preflight.model_dump(), 'recommended_action': action,
            'evidence_binding_status': 'PROPOSED_ONLY', 'quota_hit': quota_hit,
            'retrieval_policy': {'name': 'exact-control-first-v1', 'match_counts': match_counts,
                                 'exact_control_first': True}}
        self.acquisitions.register(payload)
        return payload
