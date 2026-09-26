"""Real-records pilot (kit v31). No test touches the network: a constructed GitHub API answers every read."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from governance import realrecords as rr

REPO = "acme/widgets"
A = {"login": "ana", "id": 1, "type": "User"}
B = {"login": "ben", "id": 2, "type": "User"}
C = {"login": "cai", "id": 3, "type": "User"}
BOT = {"login": "dependabot[bot]", "id": 49699333, "type": "Bot"}
TOKEN = "ghp_constructed_not_a_real_token"


def _pr(number, author, merged_at, head, merge_sha, updated=None, merged_by=None):
    return {"number": number, "html_url": f"https://github.com/{REPO}/pull/{number}", "title": f"change {number}",
            "user": author, "merged_at": merged_at, "updated_at": updated or merged_at, "head": {"sha": head},
            "merge_commit_sha": merge_sha, "merged_by": merged_by or author, "base": {"ref": "main"}}


def _review(user, state, commit, at):
    return {"user": user, "state": state, "commit_id": commit, "submitted_at": at}


def _commit(sha, author, email, date, message="x"):
    return {"sha": sha, "html_url": f"https://github.com/{REPO}/commit/{sha}", "author": author, "committer": author,
            "parents": [{"sha": "p"}], "commit": {"message": message, "author": {"email": email},
                                                  "committer": {"date": date}}}


PULLS = [
    _pr(1, A, "2026-07-02T10:00:00Z", "h1", "m1"),                    # approved by ben on the final commit, checks pass
    _pr(2, A, "2026-07-05T10:00:00Z", "h2", "m2"),                    # no reviews; a failing check
    _pr(3, C, "2026-07-09T10:00:00Z", "h3", "m3"),                    # approved on an older commit; no checks at all
    _pr(4, BOT, "2026-07-12T10:00:00Z", "h4", "m4", merged_by=A),     # changes requested, then approved by ana
    _pr(5, B, "2026-07-15T10:00:00Z", "h5", "m5"),                    # approved, then changes requested by the same
    _pr(6, A, None, "h6", None, updated="2026-07-20T10:00:00Z"),      # closed, not merged
    _pr(7, A, "2026-05-01T10:00:00Z", "h7", "m7", updated="2026-05-01T10:00:00Z"),   # merged before the window
]
REVIEWS = {
    1: [_review(B, "APPROVED", "h1", "2026-07-02T09:00:00Z")],
    2: [],
    3: [_review(B, "APPROVED", "old3", "2026-07-08T09:00:00Z"), _review(C, "COMMENTED", "h3", "2026-07-09T09:00:00Z")],
    4: [_review(B, "CHANGES_REQUESTED", "h4", "2026-07-11T09:00:00Z"), _review(A, "APPROVED", "h4", "2026-07-12T09:00:00Z")],
    5: [_review(A, "APPROVED", "h5", "2026-07-14T09:00:00Z"), _review(A, "CHANGES_REQUESTED", "h5", "2026-07-15T09:00:00Z")],
}
CHECKS = {"h1": [("test", "completed", "success")], "h2": [("test", "completed", "failure")], "h3": [],
          "h4": [("lint", "completed", "success"), ("test", "in_progress", None)], "h5": [("test", "completed", "skipped")]}
COMMITS = [
    _commit("m1", A, "ana@home.example", "2026-07-02T10:00:00Z"), _commit("m2", A, "ana@work.example", "2026-07-05T10:00:00Z"),
    _commit("m3", C, "cai@example", "2026-07-09T10:00:00Z"), _commit("m4", BOT, "bot@example", "2026-07-12T10:00:00Z"),
    _commit("m5", B, "ben@example", "2026-07-15T10:00:00Z"),
    _commit("r3", C, "cai@example", "2026-07-09T10:00:01Z"),        # a rebase-merged commit of PR 3
    _commit("d1", B, "ben@example", "2026-07-20T10:00:00Z", "hotfix straight to main"),
    _commit("d2", None, "someone@laptop.local", "2026-07-21T10:00:00Z", "unlinked author"),
]


GIT_LOG = [  # git's own first-parent history: the population the API collection must cover
    ("m1", "2026-07-02T10:00:00+00:00", "change 1 (#1)"), ("m2", "2026-07-05T10:00:00+00:00", "change 2 (#2)"),
    ("m3", "2026-07-09T10:00:00+00:00", "change 3 (#3)"), ("r3", "2026-07-09T10:00:01+00:00", "rebased part, see (#42)"),
    ("m4", "2026-07-12T10:00:00+00:00", "Merge pull request #4 from bot/deps"), ("m5", "2026-07-15T10:00:00+00:00", "x"),
    ("d1", "2026-07-20T10:00:00+00:00", "hotfix straight to main"), ("d2", "2026-07-21T10:00:00+00:00", "unlinked"),
    ("e1", "2026-06-01T00:20:00+00:00", "at the window's opening edge"),
    ("old", "2026-05-20T10:00:00+00:00", "before the window"),
]


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class FakeGit:
    def __init__(self, log=GIT_LOG, fail=None):
        self.log, self.fail, self.calls = log, fail, []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if self.fail:
            return Done("", 128, self.fail)
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True)
            (Path(args[-1]) / "HEAD").write_text("ref: refs/heads/main\n")
            return Done()
        verb = args[3]
        if verb == "symbolic-ref":
            return Done("refs/heads/main\n")
        if verb == "rev-parse":
            return Done("f" * 40 + "\n")
        if verb == "log":
            return Done("".join(f"{sha}\x1f{date}\x1f{subject}\n" for sha, date, subject in self.log))
        return Done()                                                   # fetch


@pytest.fixture(autouse=True)
def constructed_git(monkeypatch):
    git = FakeGit()
    monkeypatch.setattr(rr, "GIT_RUN", git)
    return git


class Resp:
    def __init__(self, status, data=None, headers=None, raw=None):
        self.status_code, self.headers = status, headers or {}
        self.content = raw if raw is not None else json.dumps(data).encode()


class FakeGitHub:
    def __init__(self):
        self.calls, self.fail_at, self.fail_with = [], None, None

    def __call__(self, url, timeout=None, allow_redirects=None, headers=None):
        self.calls.append((url, headers))
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            return self.fail_with
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.removeprefix(f"/repos/{REPO}")
        if path == "":
            return Resp(200, {"default_branch": "main"})
        if path == "/pulls":
            return Resp(200, PULLS)
        if path.startswith("/pulls/") and path.endswith("/reviews"):
            return Resp(200, REVIEWS[int(path.split("/")[2])])
        if path.startswith("/pulls/"):
            return Resp(200, next(p for p in PULLS if p["number"] == int(path.split("/")[2])))
        if path.endswith("/check-runs"):
            runs = CHECKS[path.split("/")[2]]
            return Resp(200, {"total_count": len(runs), "check_runs": [
                {"name": n, "status": s, "conclusion": c} for n, s, c in runs]})
        if path.endswith("/status"):
            return Resp(200, {"state": "pending" if path.split("/")[2] == "h3" else "success", "total_count": 0})
        if path == "/commits":
            assert q["sha"] == "main" and q["since"].startswith("2026-06-01")
            return Resp(200, COMMITS)
        if path.endswith("/pulls"):
            sha = path.split("/")[2]
            return Resp(200, [{"number": 3, "merged_at": "2026-07-09T10:00:00Z", "base": {"ref": "main"}}]
                        if sha == "r3" else [])
        raise AssertionError(f"unexpected read {url}")


@pytest.fixture
def pilot(monkeypatch):
    monkeypatch.setenv("GAAR_GITHUB_TOKEN", TOKEN)
    rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    rr.approve(REPO, "Wu Yen Ching")
    return FakeGitHub()


def _collected(pilot):
    assert rr.collect(REPO, get=pilot)["status"] == "COLLECTED"
    return rr.evaluate(REPO)


def _change(result, change_id):
    return next(c for c in result["changes"] if c["id"] == change_id)


# ---------------------------------------------------------------------------------------------------------
# Plan and approval
# ---------------------------------------------------------------------------------------------------------

def test_a_plan_names_the_credential_variable_and_a_closed_window_only():
    with pytest.raises(rr.PilotRefused, match=r"^repo must be owner/name, for example python-poetry/poetry$"):
        rr.make_plan("poetry", "2026-06-01", "2026-09-01")
    with pytest.raises(rr.PilotRefused, match=r"^token_env must be the NAME of an environment variable"):
        rr.make_plan(REPO, "2026-06-01", "2026-09-01", token_env="ghp_abc123")
    with pytest.raises(rr.PilotRefused, match=r"^the window must start before it ends and must have ended"):
        rr.make_plan(REPO, "2026-09-01", "2026-06-01")
    with pytest.raises(rr.PilotRefused, match=r"^the window must start before it ends and must have ended"):
        rr.make_plan(REPO, "2026-06-01", "2999-01-01")


def test_the_protocol_is_written_before_collection(monkeypatch, tmp_path):
    monkeypatch.setattr(rr, "PROTOCOL", tmp_path / "absent.md")
    with pytest.raises(rr.PilotRefused, match=r"^no labelling protocol at .*absent\.md; it is written before"):
        rr.make_plan(REPO, "2026-06-01", "2026-09-01")


def test_the_plan_pins_the_protocol_and_the_rules():
    plan = rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    assert plan["protocol_sha256"] == rr._sha_bytes(rr.PROTOCOL.read_bytes())
    assert plan["controls_sha256"] == rr.controls_sha256() and plan["controls_version"] == "realrecords-controls/1"
    assert plan["seed"] == rr.make_plan(REPO, "2026-06-01", "2026-09-01")["seed"]      # reproducible sample


def test_nothing_is_collected_before_a_named_person_approves_the_plan(monkeypatch):
    with pytest.raises(rr.PilotRefused, match=r"^no plan to approve; run plan first$"):
        rr.approve(REPO, "Wu Yen Ching")
    rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    with pytest.raises(rr.PilotRefused, match=r"^the plan is not approved; run plan, then approve with your name$"):
        rr.collect(REPO, get=FakeGitHub())
    with pytest.raises(ValueError, match=r"^'Your Name' is a placeholder, not a name"):
        rr.approve(REPO, "Your Name")
    with pytest.raises(ValueError, match=r"^a plan is approved by a named person: pass --by with your name$"):
        rr.approve(REPO, " ")
    assert rr.approve(REPO, "Wu Yen Ching")["status"] == "PLAN_APPROVED"


def test_a_plan_protocol_or_rule_changed_after_approval_stops_collection(pilot, monkeypatch, tmp_path):
    rr.make_plan(REPO, "2026-06-01", "2026-08-01")
    with pytest.raises(rr.PilotRefused, match=r"^the plan changed after it was approved; approve the new plan"):
        rr.collect(REPO, get=pilot)
    rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    assert rr.approved_plan(REPO)["approved_by"] == "Wu Yen Ching"          # the same plan again: still approved
    copy = tmp_path / "protocol.md"
    copy.write_bytes(rr.PROTOCOL.read_bytes() + b"\nedited after the plan\n")
    original = rr.PROTOCOL
    monkeypatch.setattr(rr, "PROTOCOL", copy)
    with pytest.raises(rr.PilotRefused, match=r"^the labelling protocol changed after the plan pinned it"):
        rr.collect(REPO, get=pilot)
    monkeypatch.setattr(rr, "PROTOCOL", original)       # never monkeypatch.undo(): it would also undo the isolation
    monkeypatch.setitem(rr.CONTROLS, "RC4", "checks may fail")
    with pytest.raises(rr.PilotRefused, match=r"^these control definitions differ from the ones the plan pinned"):
        rr.collect(REPO, get=pilot)


# ---------------------------------------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------------------------------------

def test_collection_reads_only_the_api_says_who_it_is_and_keeps_every_response(pilot):
    result = rr.collect(REPO, get=pilot)
    assert result["status"] == "COLLECTED" and result["pulls"] == 5 and result["commits"] == 8
    assert all(url.startswith("https://api.github.com/repos/acme/widgets") for url, _ in pilot.calls)
    headers = pilot.calls[0][1]
    assert headers["User-Agent"].startswith("GaaR-realrecords/1") and headers["Authorization"] == f"Bearer {TOKEN}"
    folder = rr._folder(REPO)
    reads = [r["payload"] for r in rr.ledger(REPO).read() if r["record_type"] == "Read"]
    assert len(reads) == len(pilot.calls) == result["reads_kept"]
    for read in reads:
        assert rr._sha_bytes((folder / read["kept_as"]).read_bytes()) == read["sha256"]
    for path in folder.rglob("*"):
        if path.is_file():
            assert TOKEN not in path.read_text(errors="ignore")             # the token is never written anywhere


def test_a_rerun_reads_what_was_kept_and_asks_github_nothing_again(pilot):
    rr.collect(REPO, get=pilot)
    again = FakeGitHub()
    assert rr.collect(REPO, get=again)["reads_this_run"] == 0 and again.calls == []


def test_without_the_token_nothing_is_read(pilot, monkeypatch):
    monkeypatch.delenv("GAAR_GITHUB_TOKEN")
    with pytest.raises(rr.CollectionStopped, match=r"^no GitHub token: on a Mac add it to the Keychain as gaar-github "
                                                   r"\(security add-generic-password -a \"\$USER\" -s gaar-github -w\); "
                                                   r"elsewhere set GAAR_GITHUB_TOKEN for this one command$"):
        rr.collect(REPO, get=pilot)
    assert pilot.calls == []


def test_on_a_mac_the_token_is_read_from_the_keychain_when_it_is_used(pilot, monkeypatch):
    # v32: an exported token sits in every shell's environment, including shells an agent runs commands in.
    seen = []

    def security(args, **kwargs):
        seen.append(args)
        return Done("ghp_from_keychain\n")
    assert rr.keychain_read("gaar-github", run=security, platform="darwin") == "ghp_from_keychain"
    assert seen[0][:2] == ["security", "find-generic-password"] and seen[0][-3:] == ["-s", "gaar-github", "-w"]
    assert rr.keychain_read("gaar-github", run=security, platform="linux") is None
    assert rr.keychain_read("gaar-github", run=lambda a, **k: Done("", 44), platform="darwin") is None
    monkeypatch.delenv("GAAR_GITHUB_TOKEN")
    rr.collect(REPO, get=pilot, keychain=lambda service: "ghp_from_keychain")
    assert pilot.calls[0][1]["Authorization"] == "Bearer ghp_from_keychain"
    reads = [r["payload"] for r in rr.ledger(REPO).read() if r["record_type"] == "Read"]
    assert reads[0]["token_from"] == "the macOS Keychain entry gaar-github"
    assert "ghp_from_keychain" not in (rr._folder(REPO) / "ledger.jsonl").read_text()


@pytest.mark.parametrize("response, message", [
    (Resp(403, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790400000"}),
     r"^GitHub's rate limit was reached; rerun collect after 2026-09-26T0\d:\d\d:00\+00:00 to continue$"),
    (Resp(429, {}), r"^GitHub's rate limit was reached; rerun collect after later to continue$"),
    (Resp(401, {}), r"^GitHub refused the token from the environment variable GAAR_GITHUB_TOKEN \(HTTP 401\)\. "
                    r"Fine-grained tokens expire on the date set when they were made"),
    (Resp(200, raw=b"<html>busy</html>"), r"^/repos/acme/widgets/pulls/1: the response is not JSON$"),
    (Resp(302, {}), r"^/repos/acme/widgets/pulls/1: redirected; the pilot does not follow redirects$"),
    (Resp(500, {}), r"^/repos/acme/widgets/pulls/1: HTTP 500$"),
    (Resp(200, raw=b"x" * (rr.MAX_BYTES + 1)), r"^/repos/acme/widgets/pulls/1: response larger than 20 MB$"),
])
def test_a_stop_leaves_an_incomplete_collection_that_resumes_where_it_stopped(pilot, response, message):
    pilot.fail_at, pilot.fail_with = 3, response
    stopped = rr.collect(REPO, get=pilot)
    assert stopped["status"] == "INCOMPLETE" and __import__("re").match(message, stopped["stopped"])
    with pytest.raises(rr.PilotRefused, match=r"^the collection is incomplete \(.+\); an incomplete collection is "
                                              r"never evaluated as if whole"):
        rr.evaluate(REPO)
    resumed = FakeGitHub()
    assert rr.collect(REPO, get=resumed)["status"] == "COLLECTED"
    assert not any(url.endswith(f"/repos/{REPO}") for url, _ in resumed.calls)     # what was kept is not re-read


def test_the_request_budget_is_a_stop_not_a_silent_truncation(monkeypatch):
    monkeypatch.setenv("GAAR_GITHUB_TOKEN", TOKEN)
    rr.make_plan(REPO, "2026-06-01", "2026-09-01", max_requests=4)
    rr.approve(REPO, "Wu Yen Ching")
    result = rr.collect(REPO, get=FakeGitHub())
    assert result["status"] == "INCOMPLETE"
    assert result["stopped"] == ("the plan's request budget (4) is used up; rerun collect later to continue from "
                                 "what was read")


def test_a_response_in_an_unknown_shape_is_a_recorded_stop(pilot, monkeypatch):
    broken = [dict(COMMITS[0])]
    del broken[0]["commit"]
    real = pilot.__class__.__call__

    def shaped(self, url, **kw):
        return Resp(200, broken) if urlparse(url).path.endswith("/commits") else real(self, url, **kw)
    monkeypatch.setattr(FakeGitHub, "__call__", shaped)
    result = rr.collect(REPO, get=FakeGitHub())
    assert result["status"] == "INCOMPLETE"
    assert result["stopped"].startswith("unexpected response shape (KeyError: 'commit') after reading "
                                        "https://api.github.com/repos/acme/widgets/commits?")
    collected = [r["payload"] for r in rr.ledger(REPO).read() if r["record_type"] == "Collected"]
    assert collected[-1]["complete"] is False and collected[-1]["stopped"] == result["stopped"]


def test_the_snapshot_is_evidence_and_is_never_edited(pilot):
    with pytest.raises(rr.PilotRefused, match=r"^nothing collected yet; run collect$"):
        rr.evaluate(REPO)
    rr.collect(REPO, get=pilot)
    file = rr._folder(REPO) / "snapshot.json"
    file.write_text(file.read_text().replace("ana", "anna"))
    with pytest.raises(rr.PilotRefused, match=r"^snapshot\.json differs from what the last collection recorded"):
        rr.evaluate(REPO)


# ---------------------------------------------------------------------------------------------------------
# The git baseline
# ---------------------------------------------------------------------------------------------------------

def test_the_plan_pins_gits_own_history_of_the_window(constructed_git):
    plan = rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    assert constructed_git.calls[0][:3] == ["git", "clone", "--quiet"] and "--shallow-since=2026-05-25" in \
        constructed_git.calls[0]
    assert constructed_git.calls[0][-2] == "https://github.com/acme/widgets"
    assert plan["baseline"]["first_parent_commits"] == 9 and plan["baseline"]["branch"] == "main"  # not "old"
    baseline = json.loads((rr._folder(REPO) / "baseline.json").read_text())
    assert baseline["pr_refs"] == [1, 2, 3, 4, 42]
    rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    assert constructed_git.calls[-4][3] == "fetch"                        # a second plan updates the same clone


def test_without_git_there_is_no_baseline_and_no_plan(monkeypatch):
    import subprocess
    monkeypatch.setattr(rr, "GIT_RUN", subprocess.run)
    monkeypatch.setattr(rr.shutil, "which", lambda name: None)
    with pytest.raises(rr.PilotRefused, match=r"^git is needed for the baseline the plan pins"):
        rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    monkeypatch.setattr(rr, "GIT_RUN", FakeGit(fail="fatal: repository not found"))
    with pytest.raises(rr.PilotRefused, match=r"^git clone failed for the baseline: fatal: repository not found$"):
        rr.make_plan(REPO, "2026-06-01", "2026-09-01")
    with pytest.raises(rr.PilotRefused, match=r"^keychain_service must be the NAME of a Keychain entry"):
        rr.make_plan(REPO, "2026-06-01", "2026-09-01", keychain_service="ghp_secret value")


def test_a_skipped_page_is_caught_by_the_baseline_and_nothing_is_evaluated(pilot, monkeypatch):
    real = pilot.__class__.__call__

    def short(self, url, **kw):
        if urlparse(url).path.endswith("/commits"):
            return Resp(200, [c for c in COMMITS if c["sha"] != "d1"])     # as if a page had been skipped
        return real(self, url, **kw)
    monkeypatch.setattr(FakeGitHub, "__call__", short)
    assert rr.collect(REPO, get=FakeGitHub())["status"] == "COLLECTED"   # the API alone cannot tell
    with pytest.raises(rr.PilotRefused, match=r'^the API collection is missing 1 of the 9 commits git shows on main '
                                              r'in the window \(first: d1 "hotfix straight to main"\); a page was '
                                              r'probably skipped'):
        rr.evaluate(REPO)


def test_coverage_is_reported_and_edge_commits_are_listed_not_refused(pilot):
    covered = _collected(pilot)["coverage"]
    assert covered["git_first_parent_commits"] == 9 and covered["found_by_the_api"] == 8
    assert covered["near_a_window_edge_not_found"] == ["e1"]
    assert covered["named_but_not_collected"] == [42]                    # named in a message, not a collected PR


def test_the_baseline_is_evidence_and_is_never_edited(pilot):
    rr.collect(REPO, get=pilot)
    file = rr._folder(REPO) / "baseline.json"
    file.write_text(file.read_text().replace("hotfix", "feature"))
    with pytest.raises(rr.PilotRefused, match=r"^baseline\.json differs from the baseline the plan pinned"):
        rr.evaluate(REPO)


# ---------------------------------------------------------------------------------------------------------
# The rules on the records
# ---------------------------------------------------------------------------------------------------------

def test_each_rule_reads_the_record_as_it_is(pilot):
    result = _collected(pilot)
    assert {c["id"] for c in result["changes"]} == {"PR#1", "PR#2", "PR#3", "PR#4", "PR#5", "commit d1", "commit d2"}
    assert {k: v[0] for k, v in _change(result, "PR#1")["results"].items()} == {"RC2": "PASS", "RC3": "PASS",
                                                                               "RC4": "PASS"}
    pr2 = _change(result, "PR#2")["results"]
    assert pr2["RC2"] == ("EXCEPTION", "no approval from anyone other than the author; merged by ana")
    assert pr2["RC3"][0] == "NOT_APPLICABLE" and pr2["RC4"] == ("EXCEPTION", "checks on the final commit: failed test")
    pr3 = _change(result, "PR#3")["results"]
    assert pr3["RC2"][0] == "PASS" and pr3["RC3"][0] == "EXCEPTION"
    assert pr3["RC4"] == ("NOT_EVIDENCED", "no automated checks are recorded on the final commit")
    pr4 = _change(result, "PR#4")["results"]                               # a bot's change approved by a person
    assert pr4["RC2"] == ("PASS", "approved by ana") and pr4["RC4"] == ("EXCEPTION", "checks on the final commit: "
                                                                               "still running test")
    assert _change(result, "PR#5")["results"]["RC2"][0] == "EXCEPTION"    # the latest review is what counts
    assert _change(result, "commit d1")["results"]["RC1"] == ("EXCEPTION", "reached the default branch without a "
                                                                          "merged pull request")
    d2 = _change(result, "commit d2")
    assert d2["identity"] == "unresolved (email linked to no account)" and "not linked to any account" in \
        d2["results"]["RC1"][1]
    assert result["counts"]["RC1"]["EXCEPTION"] == 2 and result["counts"]["RC2"]["EXCEPTION"] == 2


def test_the_identity_picture_is_its_own_set_of_numbers(pilot):
    identity = _collected(pilot)["identity"]
    assert identity["commits"] == 8 and identity["commits_author_unlinked"] == 1
    assert identity["accounts_with_several_emails"] == 1                  # ana, under two emails
    assert identity["emails_under_several_accounts"] == 0
    assert identity["changes_by_bot_accounts"] == 2                       # the bot's pull request and its commit
    snapshot = json.loads((rr._folder(REPO) / "snapshot.json").read_text())
    assert "ana@home.example" not in json.dumps(snapshot)                 # emails are counted, never kept


# ---------------------------------------------------------------------------------------------------------
# Sample, labels, score
# ---------------------------------------------------------------------------------------------------------

def test_the_sample_is_every_exception_and_a_seeded_set_of_passed_changes(pilot):
    with pytest.raises(rr.PilotRefused, match=r"^no results yet; run evaluate$"):
        rr.sample(REPO)
    _collected(pilot)
    first = rr.sample(REPO)
    assert first == rr.sample(REPO)                                       # the same seed draws the same sample
    kinds = [i["kind"] for i in first["items"]]
    assert kinds.count("exception") == first["exceptions_found"] == 6 and kinds.count("passed") == 1
    assert kinds.count("linked") == first["linked_by_lookup"] == 1          # r3: linked by GitHub's lookup
    [linked] = [i for i in first["items"] if i["kind"] == "linked"]
    assert linked["change"] == "commit r3" and "through PR #3" in linked["claim"]
    assert first["items"][0]["url"].startswith("https://github.com/acme/widgets/")


def test_labels_are_named_stated_as_self_or_independent_and_explained_when_negative(pilot):
    with pytest.raises(rr.PilotRefused, match=r"^no sample drawn yet; run sample$"):
        rr.label(REPO, "E01", "TRUE_EXCEPTION", "Wu Yen Ching", "self")
    _collected(pilot)
    rr.sample(REPO)
    with pytest.raises(rr.PilotRefused, match=r"^provenance must be one of self, independent"):
        rr.label(REPO, "E01", "TRUE_EXCEPTION", "Wu Yen Ching", "builder")
    with pytest.raises(ValueError, match=r"^'Your Name' is a placeholder, not a name"):
        rr.label(REPO, "E01", "TRUE_EXCEPTION", "Your Name", "self")
    with pytest.raises(ValueError, match=r"^a label is made by a named person: pass --by with your name$"):
        rr.label(REPO, "E01", "TRUE_EXCEPTION", "", "self")
    with pytest.raises(rr.PilotRefused, match=r"^no item E99 in the sample$"):
        rr.label(REPO, "E99", "TRUE_EXCEPTION", "Wu Yen Ching", "self")
    with pytest.raises(rr.PilotRefused, match=r"^item E01 is answered with TRUE_EXCEPTION, FALSE_POSITIVE, "
                                              r"CANNOT_TELL$"):
        rr.label(REPO, "E01", "CORRECTLY_PASSED", "Wu Yen Ching", "self")
    with pytest.raises(rr.PilotRefused, match=r"^FALSE_POSITIVE needs a note saying what you saw on GitHub$"):
        rr.label(REPO, "E01", "FALSE_POSITIVE", "Wu Yen Ching", "self")
    with pytest.raises(rr.PilotRefused, match=r"^item L01 is answered with CORRECTLY_LINKED, WRONGLY_LINKED, "
                                              r"CANNOT_TELL$"):
        rr.label(REPO, "L01", "TRUE_EXCEPTION", "Wu Yen Ching", "self")
    with pytest.raises(rr.PilotRefused, match=r"^WRONGLY_LINKED needs a note saying what you saw on GitHub$"):
        rr.label(REPO, "L01", "WRONGLY_LINKED", "Wu Yen Ching", "self")
    assert rr.label(REPO, "L01", "CORRECTLY_LINKED", "Wu Yen Ching", "self")["status"] == "LABELLED"


def test_the_reviewers_packet_starts_with_the_rubric_and_the_rubric_review_is_recorded(pilot):
    with pytest.raises(rr.PilotRefused, match=r"^no sample drawn yet; run sample$"):
        rr.packet(REPO)
    _collected(pilot)
    rr.sample(REPO)
    text = rr.packet(REPO).read_text()
    assert text.index("review-rubric") < text.index("## What is being labelled") < text.index("## Items")
    assert "| L01 | linked | [commit r3]" in text
    assert rr.score(REPO)["rubric"].startswith("not yet reviewed by anyone independent")
    with pytest.raises(ValueError, match=r"^'Your Name' is a placeholder, not a name"):
        rr.review_rubric(REPO, "Your Name", "independent", "ACCEPTED")
    with pytest.raises(ValueError, match=r"^a rubric review is made by a named person"):
        rr.review_rubric(REPO, "", "independent", "ACCEPTED")
    with pytest.raises(rr.PilotRefused, match=r"^provenance must be one of self, independent$"):
        rr.review_rubric(REPO, "Priya Raman", "friend", "ACCEPTED")
    with pytest.raises(rr.PilotRefused, match=r"^verdict must be one of ACCEPTED, CHANGES_NEEDED$"):
        rr.review_rubric(REPO, "Priya Raman", "independent", "OK")
    with pytest.raises(rr.PilotRefused, match=r"^CHANGES_NEEDED needs a note naming what the rubric misses$"):
        rr.review_rubric(REPO, "Priya Raman", "independent", "CHANGES_NEEDED")
    rr.review_rubric(REPO, "Wu Yen Ching", "self", "ACCEPTED")
    assert rr.score(REPO)["rubric"].startswith("not yet reviewed by anyone independent")
    rr.review_rubric(REPO, "Priya Raman", "independent", "CHANGES_NEEDED", note="RC4 ignores required reviewers")
    assert rr.score(REPO)["rubric"] == "reviewed independently: CHANGES_NEEDED by Priya Raman"


def test_the_score_keeps_each_labeller_apart_and_says_when_nobody_independent_has_labelled(pilot):
    with pytest.raises(rr.PilotRefused, match=r"^no sample drawn yet; run sample$"):
        rr.score(REPO)
    _collected(pilot)
    items = rr.sample(REPO)["items"]
    exceptions = [i["item"] for i in items if i["kind"] == "exception"]
    for item in exceptions[:5]:
        rr.label(REPO, item, "TRUE_EXCEPTION", "Wu Yen Ching", "self")
    rr.label(REPO, exceptions[5], "FALSE_POSITIVE", "Wu Yen Ching", "self", note="approved on the final commit")
    rr.label(REPO, "C01", "MISSED_EXCEPTION", "Wu Yen Ching", "self", note="RC4: check failed")
    score = rr.score(REPO)
    [mine] = score["labellers"]
    assert mine["precision"] == round(5 / 6, 3) and mine["missed_in_passed_sample"] == 1 and mine["labelled"] == 7
    assert mine["reads_as"] == "labelled by a builder of GaaR, not independent"
    assert score["headline"] == "self-labelled only: no independent result yet"
    for item in exceptions[:3]:
        rr.label(REPO, item, "TRUE_EXCEPTION", "Priya Raman", "independent")
    rr.label(REPO, exceptions[5], "TRUE_EXCEPTION", "Priya Raman", "independent")
    score = rr.score(REPO)
    assert score["headline"] == "independent" and len(score["labellers"]) == 2
    assert score["agreement"] == [{"self": "Wu Yen Ching", "independent": "Priya Raman", "items_both": 4, "agree": 3}]


def test_the_command_line_runs_the_steps_in_order(pilot, capsys, monkeypatch):
    import importlib
    cli = importlib.import_module("tools.gaar_realrecords")
    collect = rr.collect
    monkeypatch.setattr(rr, "collect", lambda repo: collect(repo, get=pilot))
    assert cli.main(["status", "--repo", REPO])["approved"] is True
    assert cli.main(["collect", "--repo", REPO])["status"] == "COLLECTED"
    evaluated = cli.main(["evaluate", "--repo", REPO])
    assert len(evaluated["exceptions"]) == 6 and evaluated["identity"]["commits"] == 8
    assert evaluated["coverage"]["found_by_the_api"] == 8 and evaluated["linked_by_lookup"] == 1
    assert cli.main(["sample", "--repo", REPO])["items"]
    assert cli.main(["packet", "--repo", REPO])["packet"].endswith("reviewer_packet.md")
    assert cli.main(["review-rubric", "--repo", REPO, "--by", "Wu Yen Ching", "--provenance", "self",
                     "--verdict", "ACCEPTED"])["status"] == "RUBRIC_REVIEWED"
    assert cli.main(["label", "--repo", REPO, "--item", "E01", "--label", "TRUE_EXCEPTION", "--by", "Wu Yen Ching",
                     "--provenance", "self"])["status"] == "LABELLED"
    assert cli.main(["score", "--repo", REPO])["labellers"][0]["labelled"] == 1
    assert cli.main(["plan", "--repo", "acme/other", "--from", "2026-06-01", "--to", "2026-09-01"])["repo"] == \
        "acme/other"
    assert cli.main(["approve", "--repo", "acme/other", "--by", "Wu Yen Ching"])["status"] == "PLAN_APPROVED"
