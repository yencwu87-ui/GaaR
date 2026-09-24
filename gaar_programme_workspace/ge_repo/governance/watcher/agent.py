from __future__ import annotations
import hashlib, json, time, uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from governance.autopilot.monitor import ChangeMonitor, TriggerType
from .connectors import connector_for
from .models import EmissionReceipt, GovernanceChangeEvent, RawDocument, WatcherAuthority, WatcherConfig, utcnow
from .skills import WatcherSkill, content_hash
from .store import CursorStore, EmissionStore, HealthStore
from .gitflow import WatcherSourceSnapshots, ImmutableWatcherBlobs

@dataclass(frozen=True)
class WatcherRunResult:
    run_id:str; source_id:str; fetched:int; classified:int; emitted:int; background:int; skipped:int; cursor_before:str|None; cursor_after:str|None; circuit_open:bool; errors:tuple[str,...]

class RegulatoryWatcherAgent:
    def __init__(self,*,skill:WatcherSkill|None=None,cursor_store:CursorStore|None=None,emission_store:EmissionStore|None=None,health_store:HealthStore|None=None,change_monitor:ChangeMonitor|None=None, source_snapshots:WatcherSourceSnapshots|None=None):
        self.skill=skill or WatcherSkill(); self.cursor_store=cursor_store or CursorStore(); self.emission_store=emission_store or EmissionStore(); self.health_store=health_store or HealthStore(); self.change_monitor=change_monitor or ChangeMonitor(); self.source_snapshots=source_snapshots or WatcherSourceSnapshots(
            blobs=ImmutableWatcherBlobs(self.emission_store.store.path.parent / "watcher_blobs"),
            path=self.emission_store.store.path.parent / "watcher_snapshots.jsonl")

    @staticmethod
    def _event(config:WatcherConfig,doc:RawDocument,classification,reqs,app)->GovernanceChangeEvent:
        ch=content_hash(doc.content); identity=f"{config.source_id}:{ch}"
        change_id="WG-"+hashlib.sha256(identity.encode()).hexdigest()[:32]
        return GovernanceChangeEvent(change_id,config.source_id,config.source_type.value,classification.authority.value,classification.jurisdiction,doc.title,doc.url,doc.published_at,doc.effective_at,ch,None,
            tuple(sorted({r.section for r in reqs if r.section})),tuple(asdict(r) for r in reqs),asdict(app),classification.materiality,classification.confidence,
            f"watcher://{config.source_id}/{doc.document_id}",utcnow())

    def run_source(self,config:WatcherConfig)->WatcherRunResult:
        config.validate(); run_id="WR-"+uuid.uuid4().hex[:24]; before=self.cursor_store.get(config.source_id)
        health=self.health_store.latest(config.source_id) or {}; failures=int(health.get("consecutive_failures",0))
        if failures >= config.max_consecutive_failures:
            return WatcherRunResult(run_id,config.source_id,0,0,0,0,0,before,before,True,("circuit breaker open",))
        try:
            docs=connector_for(config).fetch(config,before)[:config.max_items_per_run]
            emitted=background=skipped=classified=invalid=0; max_cursor=before
            for i,doc in enumerate(docs):
                # Explicit opt-in validation for live source registries: incomplete
                # documents remain visible as invalid, never trusted as change events.
                # Do NOT advance past invalid items; source remains DEGRADED.
                if config.filters.get("require_source_validation"):
                    from urllib.parse import urlparse
                    from datetime import datetime
                    candidate_url = urlparse(str(doc.url or ""))
                    errors=[]
                    if not doc.title.strip() or doc.title.strip().lower()=="untitled": errors.append("title_missing")
                    if candidate_url.scheme != "https" or not candidate_url.netloc: errors.append("canonical_https_url_missing")
                    if not str(doc.content or "").strip(): errors.append("content_missing")
                    if not str(doc.published_at or "").strip(): errors.append("publication_date_missing")
                    else:
                        try: datetime.fromisoformat(str(doc.published_at).replace("Z","+00:00"))
                        except ValueError: errors.append("publication_date_invalid")
                    if errors:
                        invalid+=1;skipped+=1
                        # Preserve even malformed records when content exists, but
                        # never let them become stageable candidates. Empty content
                        # cannot be snapshotted into CAS and must not crash the scan.
                        invalid_snapshot=(self.source_snapshots.capture(config.source_id,doc,
                            run_id=run_id,connector_type=str(config.connector.get("type")))
                            if str(doc.content or "").strip() else None)
                        self.emission_store.append({"source_id":config.source_id,"document_id":doc.document_id,
                            "document_title":doc.title,"document_url":doc.url,
                            "content_hash":content_hash(doc.content),"emission_status":"INVALID_DOCUMENT",
                            "validation_errors":errors,"run_id":run_id,
                            "source_snapshot_id":invalid_snapshot["snapshot_id"] if invalid_snapshot else None})
                        continue
                # Keep exact connector-extracted bytes for governed staging. A
                # feed excerpt is not misrepresented as the full official PDF.
                snapshot=self.source_snapshots.capture(config.source_id,doc,run_id=run_id,
                    connector_type=str(config.connector.get("type")))
                classification=self.skill.classify(doc,config); classified+=1
                reqs=self.skill.extract_requirements(doc,classification,config); app=self.skill.assess_applicability(reqs,config)
                event=self._event(config,doc,classification,reqs,app)
                marker=str(doc.metadata.get(config.cursor_field) or doc.metadata.get("last_modified") or doc.published_at or doc.document_id)
                if max_cursor is None or marker>str(max_cursor): max_cursor=marker
                if self.emission_store.has_content(config.source_id,event.content_hash): skipped+=1; continue
                if config.authority == WatcherAuthority.BACKGROUND or not config.authority.governance_impact_eligible:
                    background+=1
                    self.emission_store.append({**event.to_dict(),"emission_status":"BACKGROUND_ONLY","run_id":run_id,"source_snapshot_id":snapshot["snapshot_id"]})
                    continue
                if classification.confidence < config.min_confidence or classification.materiality < config.materiality_threshold or not app.applicable:
                    skipped+=1
                    self.emission_store.append({**event.to_dict(),"emission_status":"BELOW_POLICY_THRESHOLD","run_id":run_id,"source_snapshot_id":snapshot["snapshot_id"]})
                    continue
                # WB-131: Discovery does not authorize regulatory change. The former
                # automatic GOVERNANCE_CHANGE emission was unsafe for mixed publication
                # classes on an authoritative regulator domain. A human now classifies,
                # stages and signs a specific document version, then PUSH sends a typed
                # impact-review request for eligible law/rule/guidance only.
                self.emission_store.append({**event.to_dict(),"emission_status":"REVIEW_CANDIDATE",
                    "run_id":run_id,"source_snapshot_id":snapshot["snapshot_id"],
                    "governance_trigger_emitted":False})
                skipped+=1
            # Cursor advances only after the source run completed and all emissions were persisted.
            if docs and max_cursor is not None and not invalid: self.cursor_store.update(config.source_id,str(max_cursor),run_id=run_id)
            status="DEGRADED" if invalid else "OK"
            self.health_store.record({"source_id":config.source_id,"run_id":run_id,"status":status,"consecutive_failures":0,
                                      "invalid_documents":invalid,"fetched":len(docs),"emitted":emitted,"review_candidates":sum(1 for r in self.emission_store.read() if (r.get("payload") or {}).get("run_id")==run_id and (r.get("payload") or {}).get("emission_status")=="REVIEW_CANDIDATE"),"at":utcnow()})
            return WatcherRunResult(run_id,config.source_id,len(docs),classified,emitted,background,skipped,before,str(max_cursor) if max_cursor is not None else before,False,())
        except Exception as exc:
            failures+=1
            # HTTP 429/503, unsupported response format and bot/maintenance HTML
            # are degraded source coverage, NOT evidence of no change.
            degraded = type(exc).__name__ in {"HTTPError", "JSONDecodeError", "ParseError"}
            self.health_store.record({"source_id":config.source_id,"run_id":run_id,
                                      "status":"DEGRADED" if degraded else "ERROR",
                                      "consecutive_failures":failures,"error":str(exc),"at":utcnow()})
            return WatcherRunResult(run_id,config.source_id,0,0,0,0,0,before,before,failures>=config.max_consecutive_failures,(str(exc),))
