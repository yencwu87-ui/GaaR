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


# ---------------------------------------------------------------------------------------------------------
# Kit v22: RSS feeds, regions, drafting a control from a watch item
# ---------------------------------------------------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Press</title>
<item><title>Board issues guidance on model risk management for AI</title><link>https://www.federalreserve.gov/newsevents/pressreleases/a1.htm</link><pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Offsite link that must be ignored</title><link>https://evil.example/x</link></item>
</channel></rss>"""


def _fed_row():
    return dict(intel.catalogue()["fed-press-rss"])


def test_an_rss_feed_is_read_and_only_approved_hosts_count():
    result = intel.scan_feed(_fed_row(), get=lambda url, **k: Response(RSS, "application/rss+xml"))
    assert result["status"] == "BASELINE_ESTABLISHED"
    assert list(result["inventory"]) == ["https://www.federalreserve.gov/newsevents/pressreleases/a1.htm"]


def test_an_atom_feed_is_read_too():
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>New PRA statement on AI</title>'
            '<link href="https://www.bankofengland.co.uk/prudential-regulation/x"/><updated>2026-09-22</updated></entry></feed>')
    row = dict(intel.catalogue()["boe-news-rss"])
    result = intel.scan_feed(row, get=lambda url, **k: Response(atom, "application/atom+xml"))
    assert list(result["inventory"]) == ["https://www.bankofengland.co.uk/prudential-regulation/x"]


@pytest.mark.parametrize("body, message", [
    ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><rss></rss>', "IndexErrorSafe: feed declares XML entities; refused"),
    ("<rss><channel><item>", None),
    ("x" * (5 * 1024 * 1024 + 1), "IndexErrorSafe: feed larger than 5 MB; refused"),
])
def test_a_hostile_or_broken_feed_is_unable_to_check(body, message):
    result = intel.scan_feed(_fed_row(), get=lambda url, **k: Response(body, "application/rss+xml"))
    assert result["status"] == "UNABLE_TO_CHECK"
    if message:
        assert result["error"] == message
    else:
        assert result["error"].startswith("IndexErrorSafe: feed is not valid XML (")


def test_regions_subscribe_every_source_in_them_and_unknown_regions_are_refused():
    intel.subscriptions()
    data = intel.subscribe_regions(["hk", "cn"], by="Test Owner")
    assert {"hkma-brdr-whats-new", "hkma-press-rss", "nfra-rules-en-index", "pboc-en-news-index"} <= set(data["sources"])
    with pytest.raises(ValueError, match=exactly("unknown region(s): mars; use sg, us, uk, hk, cn, global")):
        intel.subscribe_regions(["mars"])


def test_the_catalogue_covers_singapore_us_uk_hong_kong_china_and_global():
    regions = {row.get("jurisdiction") for row in intel.catalogue().values()}
    assert {"Singapore", "US", "UK", "Hong Kong", "China", "GLOBAL"} <= regions


def test_one_click_drafts_a_control_that_is_not_live_until_promoted(web):
    from governance.regulatory_change import LIVE, load_requirements
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    item = intel.needs_triage()[0]
    live_before = Path(LIVE).read_bytes()
    made = intel.propose_control(item["item_id"], "Test Owner")
    draft = load_requirements(made["draft"])
    new = draft["controls"][made["proposed_control"]]
    assert draft["status"] == "draft" and new["status"] == "proposed" and new["source"][0]["url"] == item["url"]
    assert "M3.15" in new["rationale"] and Path(made["draft"]).is_relative_to(intel.home_path())
    assert Path(LIVE).read_bytes() == live_before                          # the live library is untouched
    assert intel.items()[0]["triage"]["decision"] == "RELEVANT"
    with pytest.raises(ValueError, match=exactly("a draft needs the name of the person proposing it")):
        intel.propose_control(item["item_id"], " ")
    with pytest.raises(ValueError, match=exactly("unknown intel item")):
        intel.propose_control("0" * 16, "Test Owner")


def test_a_dead_source_is_one_aging_item_not_one_per_check(web, monkeypatch):
    import requests
    from tests.test_guards_exercised import _cli
    from governance.production import inbox
    monkeypatch.setattr(requests, "get", web)
    web.blocked.add("guidelines")
    intel.subscriptions()
    intel.run_due(get=web, force=True)
    since = {x["source_id"]: x for x in intel.health()}["mas-guidelines-index"]["last_checked"]
    for _ in range(2):
        intel.run_due(get=web, force=True)
    h = {x["source_id"]: x for x in intel.health()}["mas-guidelines-index"]
    assert h["state"] == "FAILING" and h["consecutive_failures"] == 3 and h["failing_since"] == since
    home = intel.home_path().parent / "home"
    home.mkdir()
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "demo").returncode == 0
    found = [i for i in inbox.items(home / "demo/operations.json") if i["kind"] == "watch_source"]
    assert len(found) == 1 and f"3 failed attempt(s) in a row since {since[:16]}" in found[0]["why"]


def test_chinese_items_arrive_labelled_and_are_never_silently_translated(web):
    zh = intel._language({"jurisdiction": "China"}, "中国人民银行发布人工智能风险管理指引")
    assert zh == {"language": "zh", "language_label": "Chinese: not translated (read the original, or use a review aid)"}
    assert intel._language({"language": "zh-CN"}, "Notice 12")["language"] == "zh"
    assert intel._language({"language": "English"}, "PBOC issues guideline")["language"] == "en"
    _setup(web)
    web.consultations.append(CONSULTATION)
    intel.run_due(get=web, force=True)
    item = intel.items()[0]
    assert item["language"] == "en" and item["language_label"] is None
