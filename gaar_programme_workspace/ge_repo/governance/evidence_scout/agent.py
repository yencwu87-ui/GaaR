from __future__ import annotations
import hashlib,re,uuid
from pathlib import Path
from typing import Iterable
from .models import EvidenceCandidate,EvidenceSource,ScoutRequest,ScoutResult
from .store import ScoutStore

STOP={"the","and","for","with","that","this","from","into","shall","must","should","are","was","were","will","control","evidence","requirement"}

def _terms(text:str)->set[str]:
    return {x for x in re.findall(r"[a-zA-Z0-9_-]{3,}",text.lower()) if x not in STOP}

def _hash(text:str)->str: return hashlib.sha256(text.encode()).hexdigest()

class EvidenceScoutAgent:
    """Iterative retrieval agent over explicitly approved evidence roots.

    It discovers and ranks candidate evidence only. It cannot bind evidence to a cycle,
    set sufficiency/maturity, or make a governance decision.
    """
    def __init__(self,sources:Iterable[EvidenceSource],*,store:ScoutStore|None=None):
        self.sources=tuple(sources); self.store=store or ScoutStore()

    def _files(self,source:EvidenceSource):
        root=Path(source.root).expanduser().resolve()
        if not root.exists() or not root.is_dir(): return
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in source.allowed_extensions: continue
            try:
                if p.stat().st_size>source.max_file_bytes: continue
            except OSError: continue
            yield root,p

    def run(self,request:ScoutRequest)->ScoutResult:
        query_terms=_terms(" ".join([request.requirement,*request.element_texts]))
        candidates=[]
        for source in self.sources:
            for root,p in self._files(source) or ():
                try: text=p.read_text(encoding="utf-8",errors="ignore")
                except Exception: continue
                doc_terms=_terms(text)
                matched=sorted(query_terms & doc_terms)
                if not query_terms: score=0.0
                else: score=len(matched)/len(query_terms)
                if score < request.min_score: continue
                # trusted source affects ordering only slightly; it never changes governance verdicts.
                rank_score=min(1.0,score + (0.02 if source.trusted else 0.0))
                excerpt=" ".join(text.split())[:800]
                rel=str(p.relative_to(root))
                ch=_hash(text)
                candidates.append(EvidenceCandidate("EC-"+_hash(source.source_id+":"+rel+":"+ch)[:24],source.source_id,rel,"file://"+str(p),ch,rank_score,tuple(matched),excerpt,p.stat().st_mtime,source.source_class,source.trusted))
        candidates.sort(key=lambda x:(-x.score,-x.mtime,x.source_id,x.path))
        # Deduplicate identical content while retaining the strongest source representation.
        unique=[]; seen=set()
        for c in candidates:
            if c.content_hash in seen: continue
            seen.add(c.content_hash); unique.append(c)
            if len(unique)>=request.max_candidates: break
        source_count=len({c.source_id for c in unique})
        covered=set(t for c in unique for t in c.matched_terms)
        gaps=[]
        for idx,element in enumerate(request.element_texts,1):
            et=_terms(element)
            if et and len(et & covered)/len(et) < 0.25: gaps.append(f"element_{idx}: no strong candidate evidence")
        action="REVIEW_CANDIDATES" if unique else "COLLECT_MORE"
        run=ScoutResult("ES-"+uuid.uuid4().hex[:24],request.control_id,request.framework,tuple(unique),source_count,tuple(gaps),action)
        self.store.append(run.to_dict())
        return run
