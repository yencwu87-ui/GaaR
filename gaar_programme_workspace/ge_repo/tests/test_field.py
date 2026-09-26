"""Field agents (GaaR Part 2): evidence collected from the systems, under an approved mandate, scored by the twin."""
import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import yaml

import re

from governance.field import builder, connectors, demo, mandate
from governance.production import recurring

SGT = timezone(timedelta(hours=8))
LATER = datetime(2026, 11, 15, 9, tzinfo=SGT)


@pytest.fixture
def series(tmp_path):
    from tests.test_guards_exercised import _cli, _load
    home = tmp_path / "home"
    home.mkdir()
    assert _cli(home, "authorise", "--constructed-demo", "--workspace", home / "field", "--periods", 4).returncode == 0
    config_path = home / "field/operations.json"
    config, root = _load(config_path)
    return SimpleNamespace(path=config_path, config=config, root=root)


def _ready(series, by="Test Owner"):
    demo.build_environment(series.config, series.root)
    mandate.approve(series.root, by)


def _inbox(series):
    return series.root / series.config["periodic_evidence"]["inbox"]


def test_field_agents_collect_every_ended_period_and_the_twin_scores_what_they_built(series):
    from governance.production import scheduler
    _ready(series)
    result = scheduler.tick(series.path, now=LATER)
    field = result["jobs"]["field"]
    assert field["status"] == "OK" and len(field["delivered"]) == 4 and field["gaps"] == []
    assert result["jobs"]["series"]["stopped_at_gate"] == field["delivered"]        # assessed in the same tick
    score = importlib.import_module("tools.gaar_twin").score_series(SimpleNamespace(config=str(series.path)))
    assert score["totals"]["planted"] == score["totals"]["detected"] > 0 and score["totals"]["false_positives"] == 0
    receipts = json.loads((_inbox(series) / field["delivered"][0] / "collection_receipts.json").read_text())
    assert receipts["mandate_approved_by"] == "Test Owner" and len(receipts["reads"]) == 7
    assert {r["connector"] for r in receipts["reads"]} == {"git", "table"}
    assert all(len(r["response_sha256"]) == 64 and r["rows"] == r["mapped"] for r in receipts["reads"])
    changes = json.loads((_inbox(series) / field["delivered"][0] / "changes.json").read_text())
    assert changes["collection"]["collected_by"].startswith("field agents under mandate FM-")
    assert changes["data_classification"] == "CONSTRUCTED_TEST_DATA"


def test_nothing_is_collected_before_a_period_has_ended_and_settled(series):
    _ready(series)
    first_end = datetime.fromisoformat(recurring.verify(series.config, series.root)["periods"][0]["as_of"])
    early = builder.run(series.config, series.root, now=first_end + timedelta(minutes=10))
    assert early["delivered"] == [] and len(early["waiting"]) == 4
    settled = builder.run(series.config, series.root, now=first_end + timedelta(minutes=31))
    assert len(settled["delivered"]) == 1 and len(settled["waiting"]) == 3


def test_delivered_evidence_is_never_replaced(series):
    _ready(series)
    builder.run(series.config, series.root, now=LATER)
    again = builder.run(series.config, series.root, now=LATER)
    assert again["delivered"] == [] and again["gaps"] == []
    m, approval = mandate.load_approved(series.root)
    period = recurring.verify(series.config, series.root)["periods"][0]
    built = builder.build(m, series.root, period, 7, LATER)
    with pytest.raises(ValueError, match=r"^evidence for .+ is already in the inbox; field agents never replace it$"):
        builder.deliver(built, _inbox(series), series.root, approval, LATER)


def test_a_source_that_cannot_be_read_is_a_gap_for_its_owner_and_nothing_partial_is_delivered(series):
    from governance.production import inbox, scheduler
    _ready(series)
    (series.root / "systems/iam/grants.csv").unlink()
    result = scheduler.tick(series.path, now=LATER)
    field = result["jobs"]["field"]
    assert field["status"] == "GAPS" and field["delivered"] == []
    assert {g["gap"] for g in field["gaps"]} == {"iam-grants: export grants.csv has not arrived"}
    assert not list(_inbox(series).rglob("changes.json"))
    items = [i for i in inbox.items(series.path) if i["kind"] == "evidence_gap"]
    assert len(items) == 4 and items[0]["who"] == "HUMAN"
    assert items[0]["action"].startswith("Payments platform tower (constructed): restore access")


def test_a_row_that_cannot_be_mapped_is_a_gap_not_a_silent_drop(series):
    _ready(series)
    tickets = series.root / "systems/itsm/tickets.csv"
    lines = tickets.read_text().splitlines()
    lines[1] = ",".join([""] + lines[1].split(",")[1:])                      # a ticket with no ticket_id
    tickets.write_text("\n".join(lines) + "\n")
    out = builder.run(series.config, series.root, now=LATER)
    assert out["status"] == "GAPS" and "itsm-tickets: 1 row(s) could not be mapped (row 1: no ticket_id)" in out["gaps"][0]["gap"]


# ------------------------------------------------------------------------------------------ the mandate

def _write(series, data):
    mandate.path_for(series.root).write_text(yaml.safe_dump(data))


def _base(series):
    return demo.mandate(recurring.verify(series.config, series.root)["system_id"])


@pytest.mark.parametrize("change, message", [
    (lambda d: d.pop("owner"), "a mandate needs owner"),
    (lambda d: d["sources"][0].update(password="hunter2"),
     "a mandate names the environment variable that holds a credential, never the credential itself: mandate.sources[0].password"),
    (lambda d: d["sources"][0].update(connector="shell"), "deploy-repo: connector must be one of git, table, http_json (all read-only)"),
    (lambda d: d["sources"][0].update(role="anything"), "deploy-repo: role must be one of changes, independent, tickets, "
                                                        "privilege_grants, freezes, freeze_exceptions, recoveries, incidents"),
    (lambda d: d["sources"][2].pop("map"), "itsm-tickets: a source needs a field map to the evidence contract"),
    (lambda d: d["sources"].pop(1), "a mandate needs a independent source"),
    (lambda d: d["sources"][1].update(source_id="deploy-repo"), "every source needs its own source_id"),
    (lambda d: d["sources"][1].update(path=None, repo=d["sources"][0]["repo"]),
     "the independent population must be read from a different system than the change records"),
])
def test_a_mandate_that_breaks_a_rule_is_refused(series, change, message):
    data = _base(series)
    change(data)
    _write(series, data)
    with pytest.raises(ValueError, match="^" + re.escape(message) + "$"):
        mandate.approve(series.root, "Test Owner")


def test_an_unapproved_changed_or_missing_mandate_stops_the_agents(series):
    assert builder.run(series.config, series.root, now=LATER)["status"] == "NOT_CONFIGURED"
    with pytest.raises(ValueError, match="^no mandate at "):
        mandate.approve(series.root, "Test Owner")
    demo.build_environment(series.config, series.root)
    out = builder.run(series.config, series.root, now=LATER)
    assert out == {"status": "FAILED", "error": "the collection mandate has not been approved"}
    with pytest.raises(ValueError, match="^'Your Name' is a placeholder, not a name: record the person's own name$"):
        mandate.approve(series.root, "Your Name")
    with pytest.raises(ValueError, match="^a mandate approval needs the name of the person approving it$"):
        mandate.approve(series.root, " ")
    mandate.approve(series.root, "Test Owner")
    path = mandate.path_for(series.root)
    path.write_text(path.read_text().replace("settle_minutes: 30", "settle_minutes: 1"))
    assert builder.run(series.config, series.root, now=LATER)["error"] == (
        "the collection mandate changed after it was approved; approve it again before the agents run")


def test_a_mandate_for_another_system_is_refused(series):
    demo.build_environment(series.config, series.root)
    path = mandate.path_for(series.root)
    path.write_text(path.read_text().replace("system_id: ", "system_id: OTHER-", 1))
    mandate.approve(series.root, "Test Owner")
    assert builder.run(series.config, series.root, now=LATER)["error"].startswith("the mandate is for OTHER-")


def test_the_constructed_environment_is_written_once_and_only_for_a_demonstration(series, monkeypatch):
    demo.build_environment(series.config, series.root)
    with pytest.raises(ValueError, match="already exists; the environment is written once$"):
        demo.build_environment(series.config, series.root)
    from governance.production import recurring
    real = recurring.verify
    monkeypatch.setattr(recurring, "verify", lambda c, r: {**real(c, r), "constructed_demo": False})
    with pytest.raises(ValueError, match="^the constructed environment is only for a signed constructed-demonstration series$"):
        demo.build_environment(series.config, series.root)


# ------------------------------------------------------------------------------------------ the connectors

class _Response:
    def __init__(self, status=200, body=b"[]"):
        self.status_code, self.content = status, body


def _api(**extra):
    return {"source_id": "okta", "connector": "http_json", "role": "privilege_grants", "url": "https://iam.example.com/v1/grants",
            "allowed_hosts": ["iam.example.com"], "items_path": "data", **extra}


def test_an_api_is_read_with_a_named_credential_and_nothing_else(monkeypatch):
    seen = {}

    def get(url, headers, timeout, allow_redirects):
        seen.update(url=url, auth=headers.get("Authorization"), redirects=allow_redirects)
        return _Response(body=json.dumps({"data": [{"grant_id": "G1"}]}).encode())
    monkeypatch.setenv("IAM_READ_TOKEN", "t0ken")
    rows, receipt = connectors.read_http_json(_api(token_env="IAM_READ_TOKEN"), get=get)
    assert rows == [{"grant_id": "G1"}] and seen == {"url": "https://iam.example.com/v1/grants", "auth": "Bearer t0ken",
                                                     "redirects": False}
    assert receipt["request"] == "GET https://iam.example.com/v1/grants" and "t0ken" not in json.dumps(receipt)


@pytest.mark.parametrize("source, response, message", [
    (_api(url="https://evil.example/v1"), None, "okta: endpoint outside the mandate's approved HTTPS hosts"),
    (_api(url="http://iam.example.com/v1"), None, "okta: endpoint outside the mandate's approved HTTPS hosts"),
    (_api(token_env="NOT_SET_ANYWHERE"), None, "okta: the credential variable NOT_SET_ANYWHERE is not set"),
    (_api(), _Response(302), "okta: redirected; field agents do not follow redirects"),
    (_api(), _Response(403), "okta: HTTP 403"),
    (_api(), _Response(body=b"x" * 30), "okta: response larger than 20 MB"),
])
def test_an_api_read_outside_the_rules_is_refused(monkeypatch, source, response, message):
    monkeypatch.setattr(connectors, "MAX_BYTES", 20)
    with pytest.raises(connectors.SourceUnavailable, match="^" + re.escape(message) + "$"):
        connectors.read_http_json(source, get=lambda *a, **k: response)


def test_git_and_table_sources_that_cannot_be_read_are_refused(tmp_path, monkeypatch):
    since, until = datetime(2026, 9, 1, tzinfo=SGT), datetime(2026, 9, 8, tzinfo=SGT)
    git = {"source_id": "repo", "connector": "git", "repo": str(tmp_path / "none"), "branch": "main"}
    with pytest.raises(connectors.SourceUnavailable, match="^repo: git log failed: "):
        connectors.read_git(git, tmp_path, since, until)
    with pytest.raises(connectors.SourceUnavailable, match=r"^repo: branch name 'main; rm -rf /' is not allowed$"):
        connectors.read_git({**git, "branch": "main; rm -rf /"}, tmp_path, since, until)
    import subprocess

    def boom(*a, **k):
        raise OSError("no git")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(connectors.SourceUnavailable, match=r"^repo: git could not run \(OSError\)$"):
        connectors.read_git(git, tmp_path, since, until)
    (tmp_path / "big.csv").write_text("a\n" + "1\n" * 20)
    monkeypatch.setattr(connectors, "MAX_BYTES", 10)
    with pytest.raises(connectors.SourceUnavailable, match="^t: export larger than 20 MB$"):
        connectors.read_table({"source_id": "t", "connector": "table", "path": str(tmp_path / "big.csv")}, tmp_path)
