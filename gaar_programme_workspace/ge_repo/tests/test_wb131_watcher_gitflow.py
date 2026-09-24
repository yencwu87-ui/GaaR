from __future__ import annotations

import base64
import dataclasses
import json
import os
from pathlib import Path

import pytest

from governance.result_contract import CanonicalSigner
from governance.watcher.agent import RegulatoryWatcherAgent
from governance.watcher.gitflow import (ImmutableWatcherBlobs, WatcherSourceSnapshots,
                                        WatcherGitflow, WatcherGitError)
from governance.watcher.models import RawDocument, WatcherAuthority, SourceType, WatcherConfig
from governance.watcher.store import CursorStore, EmissionStore, HealthStore
from governance.autopilot.monitor import ChangeMonitor, TriggerStore
from governance.autopilot.scheduler import AutopilotScheduler


def setup(tmp_path, authority=WatcherAuthority.BINDING, source_id="official"):
    signer = CanonicalSigner.from_base64("local-test", base64.b64encode(b"v" * 32).decode())
    cfg = WatcherConfig(source_id, SourceType.REGULATION, authority, "SG",
                        {"type": "static", "items": []},
                        filters={"framework": "MAS", "approved_domains": ["mas.gov.sg", "www.mas.gov.sg"]})
    blobs = ImmutableWatcherBlobs(tmp_path / "cas")
    snapshots = WatcherSourceSnapshots(blobs=blobs, path=tmp_path / "snap.jsonl")
    monitor = ChangeMonitor(TriggerStore(tmp_path / "triggers.jsonl"))
    repo = WatcherGitflow(registry=(cfg,), blobs=blobs, snapshots=snapshots,
                          path=tmp_path / "git.jsonl", monitor=monitor,
                          scheduler=AutopilotScheduler(path=tmp_path / "jobs.jsonl"), signer=signer)
    return repo, cfg, blobs, snapshots, monitor


def add(repo, tmp_path, doc_class="binding_rule", lifecycle="effective", **overrides):
    path = tmp_path / "official.txt"
    if not path.exists():
        path.write_text("Original governance requirement section 4.2", encoding="utf-8")
    fields = {"source_id": "official", "file": path, "document_id": "mas-1",
              "source_url": "https://www.mas.gov.sg/regulation/notices/mas-1",
              "landing_url": "https://www.mas.gov.sg/regulation/notices",
              "title": "Official notice", "issuer": "MAS", "published_at": "2026-09-17",
              "doc_class": doc_class, "lifecycle": lifecycle, "assessment_id": "ASM-1",
              "controls": ("M3.6",), "framework": "MAS", "actor": "local-analyst",
              "rationale": "Proposed document-to-control relationship",
              "origin_attestation": "I checked the official landing page and PDF manually"}
    fields.update(overrides)
    return repo.add_file(**fields)


def test_scan_does_not_emit_governance_trigger_until_push(tmp_path):
    repo, cfg, blobs, snaps, monitor = setup(tmp_path)
    from governance.watcher.models import RawDocument
    item={"id":"doc","title":"MAS notice", "url":"https://www.mas.gov.sg/rules/doc",
          "content":"model governance requirement", "published_at":"2026-09-19",
          "last_modified":"2026-09-19", "classification_confidence":.98,
          "materiality":.95,"requirements":[{"control_id":"M3.6","requirement_text":"req"}]}
    cfg=dataclasses.replace(cfg,connector={"type":"static","items":[item]})
    ag=RegulatoryWatcherAgent(cursor_store=CursorStore(tmp_path/"c.jsonl"),
       emission_store=EmissionStore(tmp_path/"e.jsonl"),health_store=HealthStore(tmp_path/"h.jsonl"),
       change_monitor=monitor,source_snapshots=snaps)
    result=ag.run_source(cfg)
    assert result.emitted == 0
    receipt=ag.emission_store.read()[0]["payload"]
    assert receipt["emission_status"]=="REVIEW_CANDIDATE"
    assert monitor.store.read()==[]
    assert snaps.find(receipt["source_snapshot_id"])["blob_hash"]
    stage=repo.add_from_snapshot(snapshot_id=receipt["source_snapshot_id"],
          issuer="MAS",doc_class="binding_rule",lifecycle="effective",
          landing_url="https://www.mas.gov.sg/regulation/notices",assessment_id="ASM-1",
          controls=("M3.6",),framework="MAS",actor="local-analyst",
          rationale="reviewed",origin_attestation="official landing page checked")
    assert not monitor.store.read()
    commit=repo.commit(stage["stage_id"],reviewer="local-analyst",decision_note="Version and target reviewed")
    assert not monitor.store.read()
    pushed=repo.push(commit["commit_id"])
    assert pushed["relationship_status"]=="IMPACT_REVIEW"
    assert len(monitor.store.read())==1
    assert len(repo.scheduler.queued())==1
    assert pushed["trigger_ids"]==[monitor.store.read()[0]["trigger"]["trigger_id"]]


def test_commit_is_signed_and_push_idempotent(tmp_path):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    commit=repo.commit(stage["stage_id"],reviewer="reviewer",decision_note="Approved for impact analysis")
    repo._verify_commit(repo._latest("COMMIT","commit_id",commit["commit_id"]))
    first=repo.push(commit["commit_id"])
    second=repo.push(commit["commit_id"])
    assert first["push_id"]==second["push_id"]
    assert len(repo.monitor.store.read())==1
    assert len(repo.scheduler.queued())==1
    assert len(repo.status()["pushed"])==1


def test_add_is_not_a_commit_or_assessment_binding(tmp_path):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    assert stage["binding_status"]=="PROPOSED_ONLY"
    assert repo.status()["committed"]==[]
    assert repo.status()["pushed"]==[]
    assert repo.monitor.store.read()==[]


@pytest.mark.parametrize("doc_class,lifecycle,treatment",[
    ("consultation","open_consultation","HORIZON_SCAN"),
    ("research","effective","BACKGROUND_LINK"),
    ("standard","effective","BENCHMARK_LINK"),
])
def test_nonbinding_pushed_as_link_never_regulatory_trigger(tmp_path,doc_class,lifecycle,treatment):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path,doc_class,lifecycle)
    commit=repo.commit(stage["stage_id"],reviewer="reviewer",decision_note="Research/planning only")
    pushed=repo.push(commit["commit_id"])
    assert pushed["relationship_status"]==treatment
    assert pushed["trigger_ids"]==[]
    assert repo.monitor.store.read()==[]
    assert repo.scheduler.queued()==[]


def test_background_source_cannot_claim_binding_rule(tmp_path):
    repo,cfg,*_=setup(tmp_path,WatcherAuthority.BACKGROUND)
    with pytest.raises(WatcherGitError,match="maximum authority"):
        add(repo,tmp_path)
    stage=add(repo,tmp_path,doc_class="research")
    assert stage["normative_status"]=="informational"


def test_threat_creates_exposure_link_not_rule(tmp_path):
    repo,cfg,*_=setup(tmp_path,WatcherAuthority.THREAT)
    stage=add(repo,tmp_path,doc_class="threat")
    commit=repo.commit(stage["stage_id"],reviewer="analyst",decision_note="Check inventory exposure")
    assert repo.push(commit["commit_id"])["relationship_status"]=="THREAT_EXPOSURE_REVIEW"
    assert repo.monitor.store.read()==[]


@pytest.mark.parametrize("override,match",[
    ({"title":"Untitled"},"Untitled"),
    ({"source_url":"https://evil.example/doc"},"approved source domain"),
    ({"landing_url":"https://www.mas.gov.sg.evil.example"},"approved source domain"),
    ({"published_at":"not a date"},"publication date"),
    ({"origin_attestation":""},"origin_attestation"),
    ({"controls":()},"affected control IDs"),
    ({"lifecycle":"draft"},"draft/superseded"),
])
def test_add_quarantines_bad_metadata(tmp_path,override,match):
    repo,*_=setup(tmp_path)
    with pytest.raises(WatcherGitError,match=match):
        add(repo,tmp_path,**override)
    assert repo.status()["staged"] == []


def test_tampered_blob_rejected_without_editing_live_store(tmp_path):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    commit=repo.commit(stage["stage_id"],reviewer="reviewer",decision_note="I checked")
    path=repo.blobs._path(commit["blob_hash"])
    path.write_bytes(b"changed in isolated tmp_path fixture")
    with pytest.raises(WatcherGitError,match="CAS blob hash mismatch"):
        repo.push(commit["commit_id"])
    assert repo.monitor.store.read()==[]


def test_diff_preserves_previous_version(tmp_path):
    repo,*_=setup(tmp_path)
    first=add(repo,tmp_path)
    repo.commit(first["stage_id"],reviewer="reviewer",decision_note="first")
    (tmp_path/"official.txt").write_text("Revised governance requirement section 5.2",encoding="utf-8")
    second=add(repo,tmp_path)
    difference=repo.diff(second["stage_id"])
    assert difference["previous_version_hash"]==first["blob_hash"]
    assert "-Original governance requirement" in "\n".join(difference["diff_lines"])
    assert "+Revised governance requirement" in "\n".join(difference["diff_lines"])
    assert repo.blobs.read(first["blob_hash"]).startswith(b"Original")


def test_changed_source_authority_prevents_push(tmp_path):
    repo,cfg,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    commit=repo.commit(stage["stage_id"],reviewer="reviewer",decision_note="I reviewed")
    repo.registry=(dataclasses.replace(cfg,authority=WatcherAuthority.BACKGROUND),)
    with pytest.raises(WatcherGitError,match="source authority changed"):
        repo.push(commit["commit_id"])
    assert repo.monitor.store.read()==[]


def test_missing_signing_key_fails_closed(tmp_path,monkeypatch):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    repo.signer=None
    monkeypatch.delenv("WB_GAAR_RESULT_SIGNING_KEY_B64",raising=False)
    monkeypatch.delenv("WB_GAAR_RESULT_KEY_ID",raising=False)
    with pytest.raises(RuntimeError,match="SIGNING_KEY_B64"):
        repo.commit(stage["stage_id"],reviewer="reviewer",decision_note="approve")
    assert repo.status()["committed"]==[]


def test_reject_not_applicable_is_terminal_and_never_triggers(tmp_path):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    row=repo.reject(stage["stage_id"],reviewer="human",reason="Outside our product scope")
    assert row["kind"]=="REJECT"
    assert repo.status()["staged"] == []
    assert repo.monitor.store.read()==[]
    with pytest.raises(WatcherGitError,match="rejected stage"):
        repo.commit(stage["stage_id"],reviewer="human",decision_note="now approve")


def test_version_change_marks_old_assessment_link_outdated(tmp_path):
    repo,*_=setup(tmp_path)
    old=add(repo,tmp_path)
    old_commit=repo.commit(old["stage_id"],reviewer="human",decision_note="old")
    repo.push(old_commit["commit_id"])
    (tmp_path/"official.txt").write_text("New model governance obligations",encoding="utf-8")
    latest=add(repo,tmp_path)
    assert latest["previous_version_hash"]==old["blob_hash"]
    repo.commit(latest["stage_id"],reviewer="human",decision_note="new version reviewed")
    assert repo.current_use()[0]["version_status"]=="OLDER_VERSION_IMPACT_REVIEW_REQUIRED"
    assert repo.current_use()[0]["blob_hash"]==old["blob_hash"]


def test_push_recovers_trigger_after_partial_delivery(tmp_path, monkeypatch):
    repo,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    commit=repo.commit(stage["stage_id"],reviewer="human",decision_note="reviewed")
    actual_enqueue=repo.scheduler.enqueue
    calls={"count":0}
    def transient_failure(trigger):
        calls["count"]+=1
        if calls["count"]==1:
            raise OSError("simulated local job-store I/O interruption")
        return actual_enqueue(trigger)
    monkeypatch.setattr(repo.scheduler,"enqueue",transient_failure)
    with pytest.raises(OSError):
        repo.push(commit["commit_id"])
    assert len(repo.monitor.store.read())==1
    assert len(repo.status()["pending_delivery"])==1
    recovered=repo.push(commit["commit_id"])
    assert recovered["kind"]=="PUSH_DELIVERED"
    assert len(repo.scheduler.queued())==1
    assert len(repo.monitor.store.read())==1
    assert repo.status()["pending_delivery"]==[]


def test_regulator_http_maintenance_is_degraded_not_no_changes(tmp_path,monkeypatch):
    import requests
    repo,cfg,blobs,snaps,monitor=setup(tmp_path)
    class Unavailable:
        def fetch(self,cfg,cursor):
            raise requests.HTTPError("503 Service Unavailable")
    monkeypatch.setattr("governance.watcher.agent.connector_for",lambda c:Unavailable())
    ag=RegulatoryWatcherAgent(cursor_store=CursorStore(tmp_path/"c.jsonl"),
       emission_store=EmissionStore(tmp_path/"e.jsonl"),health_store=HealthStore(tmp_path/"h.jsonl"),
       change_monitor=monitor,source_snapshots=snaps)
    result=ag.run_source(cfg)
    assert result.errors and result.emitted==0
    assert ag.health_store.latest(cfg.source_id)["status"]=="DEGRADED"
    assert ag.cursor_store.get(cfg.source_id) is None


def test_rss_pubdate_normalized_without_fabricating_unknown_date(monkeypatch):
    from governance.watcher.connectors import RSSConnector
    rss=b"<rss><channel><item><title>Consultation</title><link>https://regulator.example.test/1</link><pubDate>Sat, 19 Sep 2026 10:20:00 GMT</pubDate><description>Draft only</description></item></channel></rss>"
    class Response:
        content=rss
        def raise_for_status(self):pass
    monkeypatch.setattr("governance.watcher.connectors.requests.get",lambda *a,**k:Response())
    cfg=WatcherConfig("rss",SourceType.GUIDANCE,WatcherAuthority.EXPECTATION,"UK",{"type":"rss","url":"https://regulator.example.test/rss"})
    doc=RSSConnector().fetch(cfg,None)[0]
    assert doc.published_at.startswith("2026-09-19T10:20:00")


def test_empty_source_is_invalid_and_cannot_advance_cursor(tmp_path):
    repo,cfg,blobs,snaps,monitor=setup(tmp_path)
    item={"id":"blank","title":"Untitled","url":"https://www.mas.gov.sg/blank",
          "content":"","published_at":"2026-09-19","last_modified":"2026-09-19"}
    cfg=dataclasses.replace(cfg,connector={"type":"static","items":[item]},
                            filters={**cfg.filters,"require_source_validation":True})
    ag=RegulatoryWatcherAgent(cursor_store=CursorStore(tmp_path/"c.jsonl"),
       emission_store=EmissionStore(tmp_path/"e.jsonl"),health_store=HealthStore(tmp_path/"h.jsonl"),
       change_monitor=monitor,source_snapshots=snaps)
    result=ag.run_source(cfg)
    assert result.errors==()
    assert ag.health_store.latest(cfg.source_id)["status"]=="DEGRADED"
    assert ag.cursor_store.get(cfg.source_id) is None
    assert ag.emission_store.read()[0]["payload"]["emission_status"]=="INVALID_DOCUMENT"
    assert ag.emission_store.read()[0]["payload"]["source_snapshot_id"] is None


def test_staged_new_version_flags_existing_assessment_link(tmp_path):
    repo,*_=setup(tmp_path)
    old=add(repo,tmp_path)
    approved=repo.commit(old["stage_id"],reviewer="human",decision_note="approved")
    repo.push(approved["commit_id"])
    (tmp_path/"official.txt").write_text("Draft revised text for operator review",encoding="utf-8")
    add(repo,tmp_path)
    assert repo.current_use()[0]["version_status"]=="NEW_VERSION_STAGED_REVIEW_REQUIRED"


def test_newer_committed_version_prevents_old_commit_push(tmp_path):
    repo,*_=setup(tmp_path)
    old=add(repo,tmp_path)
    approved=repo.commit(old["stage_id"],reviewer="human",decision_note="approved")
    (tmp_path/"official.txt").write_text("Final revised text",encoding="utf-8")
    newer=add(repo,tmp_path)
    repo.commit(newer["stage_id"],reviewer="human",decision_note="updated approval")
    with pytest.raises(WatcherGitError,match="newer document version"):
        repo.push(approved["commit_id"])
    assert repo.monitor.store.read()==[]


def test_removed_official_domain_blocks_push(tmp_path):
    repo,cfg,*_=setup(tmp_path)
    stage=add(repo,tmp_path)
    approved=repo.commit(stage["stage_id"],reviewer="human",decision_note="approved")
    repo.registry=(dataclasses.replace(cfg,filters={"framework":"MAS","approved_domains":["other.example"]}),)
    with pytest.raises(WatcherGitError,match="approved source domain changed"):
        repo.push(approved["commit_id"])
    assert repo.monitor.store.read()==[]
