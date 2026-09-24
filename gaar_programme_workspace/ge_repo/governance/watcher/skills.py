from __future__ import annotations
import hashlib, json, re
from dataclasses import asdict
from typing import Any
from .models import ApplicabilityAssessment, Classification, ExtractedRequirement, RawDocument, WatcherAuthority, WatcherConfig


def content_hash(text:str)->str: return hashlib.sha256(text.strip().encode()).hexdigest()

class WatcherSkill:
    """Bounded deterministic watcher skills. Source authority is configuration, never prose inference."""
    def classify(self,doc:RawDocument,config:WatcherConfig)->Classification:
        keywords=[str(x).lower() for x in config.filters.get("keywords",[]) if str(x).strip()]
        hay=(doc.title+"\n"+doc.content).lower()
        hits=sum(1 for k in keywords if k in hay)
        relevance=1.0 if not keywords else min(1.0,hits/max(1,min(3,len(keywords))))
        configured_materiality=float(doc.metadata.get("materiality",relevance))
        confidence=float(doc.metadata.get("classification_confidence",1.0 if relevance>0 else 0.5))
        return Classification(config.authority,config.jurisdiction,max(0.0,min(1.0,configured_materiality)),max(0.0,min(1.0,confidence)),(
            "authority comes from governed source configuration",f"keyword_hits={hits}",))

    def extract_requirements(self,doc:RawDocument,classification:Classification,config:WatcherConfig)->tuple[ExtractedRequirement,...]:
        explicit=doc.metadata.get("requirements") or []
        out=[]
        for row in explicit:
            if not isinstance(row,dict) or not row.get("control_id"): continue
            out.append(ExtractedRequirement(str(row["control_id"]),str(row.get("requirement_text") or row.get("text") or ""),row.get("section"),str(row.get("change_type","CHANGED")).upper()))
        if out: return tuple(out)
        mappings=config.filters.get("control_mappings") or {}
        hay=(doc.title+"\n"+doc.content).lower()
        for control_id,terms in mappings.items():
            terms=terms if isinstance(terms,list) else [terms]
            if any(str(t).lower() in hay for t in terms):
                out.append(ExtractedRequirement(str(control_id),doc.content[:4000],None,"CHANGED"))
        return tuple(out)

    def assess_applicability(self,reqs:tuple[ExtractedRequirement,...],config:WatcherConfig)->ApplicabilityAssessment:
        controls=tuple(sorted({r.control_id for r in reqs}))
        framework=config.filters.get("framework")
        return ApplicabilityAssessment(bool(controls),controls,str(framework) if framework else None,
            ("mapped to configured in-scope controls" if controls else "no configured control mapping",))
