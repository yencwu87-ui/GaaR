"""Regulatory watch as a subscribed intel service (kit v21). No test touches the network or the real ~/gaar-watch."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance.watcher import intel

CONSULTATION = "/publications/consultations/2026/consultation-paper-on-proposed-guidelines-on-generative-ai-model-risk-management"


def exactly(message):
    return "^" + re.escape(message) + "$"


class Response:
    def __init__(self, body, ctype="text/html", code=200, headers=None):
        self.content, self.status_code = body.encode(), code
        self.headers = {"Content-Type": ctype, **(headers or {})}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.content)


class Web:
    """Recorded regulator pages and feeds; each test changes them to simulate new publications."""

    def __init__(self):
        self.consultations = ["/publications/consultations/2026/consultation-paper-on-cyber-hygiene"]
        self.notices = ["/regulation/notices/notice-626"]
        self.guidelines = ["/regulation/guidelines/guidelines-on-outsourcing"]
        self.kev = [{"cveID": "CVE-2026-1000", "vulnerabilityName": "Old bug", "dateAdded": "2026-09-01",
                     "knownRansomwareCampaignUse": "Unknown"}]
        self.blocked = set()
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        if any(b in url for b in self.blocked):
            return Response("<html><title>Access denied</title></html>")
        if "cisa" in url:
            return Response(json.dumps({"vulnerabilities": self.kev}), "application/json")
        paths = self.consultations if "consultations" in url else self.notices if "notices" in url else self.guidelines
        links = "".join(f'<a href="{p}">{p.rsplit("/", 1)[-1].replace("-", " ").title()}</a>' for p in paths)
        return Response(f"<html><body>{links}</body></html>")


@pytest.fixture
def web():
    return Web()


def _setup(web):
    intel.subscriptions()
    return intel.run_due(get=web)


def test_state_lives_in_the_watch_home_never_in_the_software_folder(web):
    _setup(web)
    home = intel.home_path()
    assert (home / "subscriptions.yaml").exists() and (home / "official_indexes.jsonl").exists()
    assert not str(home).startswith(str(Path(intel.__file__).resolve().parents[2]))


def test_the_first_check_sets_a_baseline_and_raises_no_alerts(web):
    result = _setup(web)
    assert {s["status"] for s in result["scanned"]} == {"BASELINE_ESTABLISHED"}
    assert intel.items() == [] and intel.needs_triage() == []


def test_a_new_consultation_becomes_a_matched_p2_item_with_a_labelled_outlook(web):
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    item = next(i for i in intel.items() if i["kind"] == "CONSULTATION")
    assert item["priority"] == "P2" and "generative" in item["topics"]
    assert "M3.15" in [m["control_id"] for m in item["matched_controls"]]
    assert item["forecast"]["basis"].startswith("Planning assumption set by the governance owner")
    assert [i["item_id"] for i in intel.needs_triage()] == [item["item_id"]]


def test_an_instrument_matching_nothing_stays_below_the_alert_line(web):
    _setup(web)
    web.notices.append("/regulation/notices/notice-on-something-unrelated-xyz")
    intel.run_due(get=web, force=True)
    item = next(i for i in intel.items() if i["kind"] == "INSTRUMENT")
    assert item["priority"] == "P3" and intel.needs_triage() == []


def test_new_exploited_vulnerabilities_arrive_as_one_digest_and_ransomware_raises_it(web):
    _setup(web)
    web.kev += [{"cveID": "CVE-2026-2000", "vulnerabilityName": "Gateway RCE", "dateAdded": "2026-09-20",
                 "knownRansomwareCampaignUse": "Known"},
                {"cveID": "CVE-2026-2001", "vulnerabilityName": "Portal SQLi", "dateAdded": "2026-09-20",
                 "knownRansomwareCampaignUse": "Unknown"}]
    intel.run_due(get=web, force=True)
    digests = [i for i in intel.needs_triage() if i["kind"] == "THREAT_DIGEST"]
    assert len(digests) == 1 and digests[0]["priority"] == "P1" and len(digests[0]["members"]) == 2
    assert intel.triage_digest("cisa-kev", "WATCH", "Test Reviewer") == 2
    assert intel.needs_triage() == []


def test_a_blocked_source_is_unable_to_check_never_no_updates(web):
    web.blocked.add("notices")
    result = _setup(web)
    assert {"source_id": "mas-notices-index", "status": "UNABLE_TO_CHECK", "new": 0} in result["scanned"]
    health = {h["source_id"]: h for h in intel.health()}
    assert health["mas-notices-index"]["state"] == "FAILING" and not health["mas-notices-index"]["baseline"]
    assert health["mas-consultations-index"]["state"] == "OK"


def test_sources_are_checked_every_eight_hours_and_failures_retried_after_an_hour(web):
    web.blocked.add("notices")
    _setup(web)
    now = datetime.now(timezone.utc)
    assert intel.subscriptions()["interval_minutes"] == 480
    soon = intel.run_due(get=web, now=now + timedelta(minutes=30))
    assert soon["scanned"] == [] and len(soon["not_due"]) == 4
    later = intel.run_due(get=web, now=now + timedelta(minutes=61))
    assert [s["source_id"] for s in later["scanned"]] == ["mas-notices-index"]          # only the failing one
    next_day = intel.run_due(get=web, now=now + timedelta(hours=8, minutes=1))
    assert len(next_day["scanned"]) == 4


def test_triage_is_recorded_with_a_name_and_removes_the_item(web):
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    item = intel.needs_triage()[0]
    record = intel.triage(item["item_id"], "RELEVANT", "Test Reviewer", "Assess M3.15 next quarter")
    assert record["by"] == "Test Reviewer" and record["decision"] == "RELEVANT"
    assert intel.needs_triage() == [] and intel.items()[0]["triage"]["decision"] == "RELEVANT"


def test_the_outlook_names_controls_and_admits_when_it_lacks_history(web):
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    view = intel.outlook()
    assert view["label"].startswith("Outlook: forecasts") and "Not a finding" in view["label"]
    assert view["controls_likely_to_need_reassessment"][0]["control_id"] == "M3.15"
    assert {t["state"] for t in view["trends"]} == {"INSUFFICIENT_HISTORY"}


def test_a_subscription_change_is_logged_with_who_made_it(web):
    _setup(web)
    intel.set_subscribed("mas-circulars-index", True, by="Test Owner")
    assert "mas-circulars-index" in intel.subscriptions()["sources"]
    changes = [json.loads(line)["payload"] for line in (intel.home_path() / "changes.jsonl").read_text().splitlines()]
    assert changes[-1]["by"] == "Test Owner" and changes[-1]["subscribed"] is True


# ---------------------------------------------------------------------------------------------------------
# Every refusal, by its exact message
# ---------------------------------------------------------------------------------------------------------

def _write_subscriptions(**changes):
    intel.subscriptions()
    path = intel.home_path() / "subscriptions.yaml"
    import yaml
    data = {**yaml.safe_load(path.read_text()), **changes}
    path.write_text(yaml.safe_dump(data))


def test_an_interval_under_an_hour_is_refused():
    _write_subscriptions(interval_minutes=30)
    with pytest.raises(ValueError, match=exactly("the minimum checking interval is 60 minutes")):
        intel.subscriptions()


def test_a_subscription_to_an_unknown_source_is_refused():
    _write_subscriptions(sources=["mas-notices-index", "made-up-feed"])
    with pytest.raises(ValueError, match=exactly("subscribed to unknown source(s): made-up-feed")):
        intel.subscriptions()
    with pytest.raises(ValueError, match=exactly("unknown source: made-up-feed")):
        intel.set_subscribed("made-up-feed", True)


@pytest.mark.parametrize("change, message", [
    (lambda row: row.update(url="https://evil.example/kev.json"), "IndexErrorSafe: unapproved feed URL"),
    ("redirect", "IndexErrorSafe: feed redirected; redirects are not followed for feeds"),
    ("empty", "IndexErrorSafe: feed returned no items; coverage unverified"),
])
def test_a_feed_that_cannot_be_trusted_is_unable_to_check(change, message):
    row = dict(intel.catalogue()["cisa-kev"])
    get = lambda url, **k: Response(json.dumps({"vulnerabilities": [{"cveID": "X"}]}), "application/json")
    if change == "redirect":
        get = lambda url, **k: Response("", code=302, headers={"Location": "https://elsewhere.example/"})
    elif change == "empty":
        get = lambda url, **k: Response(json.dumps({"vulnerabilities": []}), "application/json")
    else:
        change(row)
    result = intel.scan_feed(row, get=get)
    assert result["status"] == "UNABLE_TO_CHECK" and result["error"] == message


def test_triage_refuses_an_unknown_decision_a_missing_name_and_an_unknown_item(web):
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    item = intel.needs_triage()[0]["item_id"]
    with pytest.raises(ValueError, match=exactly("triage must be one of RELEVANT, NOT_RELEVANT, WATCH")):
        intel.triage(item, "MAYBE", "Test Reviewer")
    with pytest.raises(ValueError, match=exactly("triage needs the name of the person making it")):
        intel.triage(item, "RELEVANT", "  ")
    with pytest.raises(ValueError, match=exactly("unknown intel item")):
        intel.triage("0" * 16, "RELEVANT", "Test Reviewer")


# ---------------------------------------------------------------------------------------------------------
# The scheduler job and the inbox
# ---------------------------------------------------------------------------------------------------------

def test_the_scheduler_job_does_nothing_until_the_watch_is_set_up():
    from governance.production.scheduler import job_watcher
    assert job_watcher({})["status"] == "NOT_CONFIGURED"
    assert not intel.home_path().exists()                                   # not even created


def test_the_scheduler_job_checks_due_sources_and_failures_become_system_items(web, monkeypatch):
    import requests
    from tests.test_guards_exercised import _cli, _load
    from governance.production import inbox, scheduler
    monkeypatch.setattr(requests, "get", web)
    web.blocked.add("guidelines")
    intel.subscriptions()
    home = intel.home_path().parent / "home"
    home.mkdir()
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo").returncode == 0
    config_path = home / "demo/operations.json"
    result = scheduler.tick(config_path)
    assert result["jobs"]["watcher"]["status"] == "OK"
    assert result["jobs"]["watcher"]["sources_failing"] == ["mas-guidelines-index"]
    found = inbox.items(config_path)
    assert [i["id"] for i in found if i["kind"] == "watch_source"] == ["watch:mas-guidelines-index"]
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    triage = [i for i in inbox.items(config_path) if i["kind"] == "triage"]
    assert len(triage) == 1 and triage[0]["due_rule"] == "P2 triage within 7 day(s) (watch subscriptions)"
    line = inbox.status_line(config_path)
    assert "(covers series, watcher, gate_status)" in line["text"] and "It covers only the jobs named" in line["help"]


def test_the_pilot_inbox_opens_an_intel_item_and_records_triage_by_the_named_reviewer(web, monkeypatch):
    import ast
    import inspect
    import app_gaar
    from streamlit.testing.v1 import AppTest
    from tests.test_guards_exercised import _cli
    from governance.production import scheduler
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    home = intel.home_path().parent / "home"
    home.mkdir()
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo").returncode == 0
    config_path = home / "demo/operations.json"
    scheduler.tick(config_path, jobs=[("series", scheduler.job_series)])
    monkeypatch.setenv("GAAR_UI", "simple")
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    app = AppTest.from_file(str(Path(app_gaar.__file__)), default_timeout=90).run()
    app.text_input[0].input("t").run()
    item = intel.needs_triage()[0]["item_id"]
    app.button(key=f"open-intel:{item}").click().run()
    assert not app.exception and any("Likely touches" in m.value for m in app.markdown)
    app.button(key="triage-RELEVANT").click().run()
    assert intel.needs_triage() == [] and intel.items()[0]["triage"]["by"] == "Test Reviewer"
    # the card's only actions are the three triage buttons, and its only writes are triage records
    source = inspect.getsource(app_gaar.render_intel_item)
    calls = {getattr(n.func, "attr", getattr(n.func, "id", None)) for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)}
    assert not calls & {"tick", "run", "run_due", "scan_feed", "append", "attest", "set_subscribed"}
