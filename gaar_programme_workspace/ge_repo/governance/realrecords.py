"""Real-records pilot (kit v31): change controls tested on a public repository's own history.

The twin proves detection against an answer key we wrote. This pilot runs the same kind of change controls on
records nobody here made: a public open-source project's changes to its default branch, the pull requests that
carried them, their reviews and their automated checks, read from the GitHub API. Nothing is planted. Whether a flagged
exception is real is decided afterwards by people, under a labelling protocol that is fixed before collection.

Order, each step refusing to run out of turn:
1. plan: repository, window, request budget and the credential variable's NAME. The plan pins the SHA-256 of the
   labelling protocol (docs/pilot/labeling_protocol.md) and of these control definitions.
2. approve: a named person approves the plan; collection refuses a plan or protocol changed since.
3. collect: read-only GETs to api.github.com only, no redirects, truthful user agent, every response kept byte for
   byte with a receipt in a hash-chained ledger. A rerun reuses what was already read, so a rate-limit stop resumes.
   An incomplete collection is reported as incomplete, never evaluated as if whole.
4. evaluate: four deterministic rules per change (RC1-RC4 below) and the identity picture.
5. sample: every exception up to 40, plus 20 changes the rules passed, chosen by a seed fixed in the plan.
6. label: a named person labels each sampled item, stating whether they are independent of GaaR.
7. score: precision and missed exceptions, per labeller, never merged across provenance.

Identity (limit L1). Pull-request rules compare GitHub's numeric account IDs, which are unique and stable, so the
namesake blind spot does not apply to RC2 and RC3. Commit-level identity is weaker: a commit can carry an email linked
to no account, one person can commit under several emails, and one email can appear under several accounts. Those are
counted and reported as their own numbers; RC1 exceptions by unlinked authors are marked identity-unresolved.

Hosted models are not used here: detection is deterministic, and the rule that hosted models see constructed cases
only stays in force. Changing that for public data is the owner's decision, not the pilot's.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from governance.names import require_person
from governance.watcher.store import HashChainStore

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "docs" / "pilot" / "labeling_protocol.md"
API = "https://api.github.com"
USER_AGENT = "GaaR-realrecords/1 (read-only governance pilot; no writes)"
CONTROLS_VERSION = "realrecords-controls/1"
CONTROLS = {
    "RC1": "Every change to the default branch arrived through a merged pull request.",
    "RC2": "Every merged pull request was approved by someone other than its author (numeric account IDs).",
    "RC3": "An approval covers the code that was merged: an approving review was made on the final commit.",
    "RC4": "Automated checks on the final commit passed; none failed or were still running at merge.",
}
LABELS = ("TRUE_EXCEPTION", "FALSE_POSITIVE", "CANNOT_TELL", "MISSED_EXCEPTION", "CORRECTLY_PASSED",
          "CORRECTLY_LINKED", "WRONGLY_LINKED")
ANSWERS = {"exception": ("TRUE_EXCEPTION", "FALSE_POSITIVE", "CANNOT_TELL"),
           "passed": ("CORRECTLY_PASSED", "MISSED_EXCEPTION", "CANNOT_TELL"),
           "linked": ("CORRECTLY_LINKED", "WRONGLY_LINKED", "CANNOT_TELL")}
RUBRIC_VERDICTS = ("ACCEPTED", "CHANGES_NEEDED")
GIT_RUN = subprocess.run            # the git baseline's only command runner (tests replace it)
EDGE = timedelta(hours=1)          # commits this close to a window edge are reported, never refused on
PROVENANCE = ("self", "independent")
MAX_BYTES = 20 * 1024 * 1024
EXCEPTION_SAMPLE, CLEAN_SAMPLE, LINKED_SAMPLE = 40, 20, 20


class PilotRefused(ValueError):
    """A step asked out of turn, or on inputs that changed since they were approved."""


class CollectionStopped(RuntimeError):
    """The source stopped answering. What was read is kept; the collection is incomplete, never empty."""


def home(path=None) -> Path:
    p = Path(path or os.environ.get("GAAR_REALRECORDS_HOME") or Path.home() / "gaar-realrecords").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canon(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def controls_sha256() -> str:
    return _sha_bytes(_canon({"version": CONTROLS_VERSION, "controls": CONTROLS}))


def _folder(repo: str, path=None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise PilotRefused("repo must be owner/name, for example python-poetry/poetry")
    folder = home(path) / repo.replace("/", "__")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def ledger(repo: str, path=None) -> HashChainStore:
    return HashChainStore(_folder(repo, path) / "ledger.jsonl", "gaar.realrecords.v1")


def _day(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc) if len(text) == 10 else \
        datetime.fromisoformat(text.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------------------------------------
# 1-2. Plan and approval
# ---------------------------------------------------------------------------------------------------------

def make_plan(repo: str, start: str, end: str, token_env: str = "GAAR_GITHUB_TOKEN", max_requests: int = 2000,
              path=None, keychain_service: str = "gaar-github") -> dict:
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", token_env or ""):
        raise PilotRefused("token_env must be the NAME of an environment variable (for example GAAR_GITHUB_TOKEN), "
                           "never the token itself")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", keychain_service or ""):
        raise PilotRefused("keychain_service must be the NAME of a Keychain entry, for example gaar-github")
    begin, finish = _day(start), _day(end)
    if not begin < finish <= datetime.now(timezone.utc):
        raise PilotRefused("the window must start before it ends and must have ended: a pilot reads closed history")
    if not PROTOCOL.is_file():
        raise PilotRefused(f"no labelling protocol at {PROTOCOL}; it is written before collection, not after")
    plan = {"repo": repo, "window": {"from": begin.isoformat(), "to": finish.isoformat()}, "token_env": token_env,
            "max_requests": int(max_requests), "api": API, "user_agent": USER_AGENT,
            "controls_version": CONTROLS_VERSION, "controls_sha256": controls_sha256(),
            "protocol": str(PROTOCOL.relative_to(ROOT)), "protocol_sha256": _sha_bytes(PROTOCOL.read_bytes()),
            "sample": {"exceptions": EXCEPTION_SAMPLE, "clean": CLEAN_SAMPLE, "linked": LINKED_SAMPLE},
            "keychain_service": keychain_service}
    folder = _folder(repo, path)
    baseline = git_baseline(repo, begin, finish, folder)
    raw = json.dumps(baseline, indent=1, sort_keys=True).encode()
    (folder / "baseline.json").write_bytes(raw)
    plan["baseline"] = {"source": baseline["source"], "branch": baseline["branch"], "head": baseline["head"],
                        "first_parent_commits": len(baseline["first_parent"]), "sha256": _sha_bytes(raw)}
    plan["seed"] = int(_sha_bytes(_canon(plan))[:12], 16)
    (folder / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return plan


def git_baseline(repo: str, begin: datetime, finish: datetime, folder: Path) -> dict:
    """The second channel (v32): the same window read from git itself, pinned in the plan before the API is asked.

    The likeliest silent failure of an API collector is a skipped page: fewer changes, and the rules report a
    cleaner history than exists. Git's own first-parent history of the default branch is the population the API
    collection must cover; evaluate refuses when a commit git shows is missing from what the API returned."""
    if GIT_RUN is subprocess.run and not shutil.which("git"):
        raise PilotRefused("git is needed for the baseline the plan pins; install it (xcode-select --install)")
    clone = folder / "git"
    url = f"https://github.com/{repo}"
    since = (begin - timedelta(days=7)).date().isoformat()

    def git(*args):
        result = GIT_RUN(["git", *args], capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise PilotRefused(f"git {args[0] if args[0] != '-C' else args[2]} failed for the baseline: "
                               f"{(result.stderr or '').strip()[:300]}")
        return result.stdout
    if (clone / "HEAD").exists():
        git("-C", str(clone), "fetch", "--quiet", f"--shallow-since={since}", "origin")
    else:
        git("clone", "--quiet", "--bare", "--filter=blob:none", f"--shallow-since={since}", url, str(clone))
    branch = git("-C", str(clone), "symbolic-ref", "HEAD").strip().removeprefix("refs/heads/")
    head = git("-C", str(clone), "rev-parse", branch).strip()
    log = git("-C", str(clone), "log", "--first-parent", "--format=%H%x1f%cI%x1f%s", branch)
    commits = []
    for line in log.splitlines():
        sha, date, subject = (line.split("\x1f") + ["", ""])[:3]
        when = _day(date)
        if begin <= when < finish:
            commits.append({"sha": sha, "date": when.isoformat(), "subject": subject[:200],
                            "near_edge": when - begin < EDGE or finish - when < EDGE})
    refs = sorted(_pr_refs(commits))
    return {"source": f"git clone {url} (first-parent history of the default branch)", "branch": branch, "head": head,
            "first_parent": commits, "pr_refs": refs}


def _pr_refs(commits: list[dict]) -> set[int]:
    """PR numbers the commit subjects name by GitHub's own conventions: squash "(#N)" and "Merge pull request #N"."""
    refs = set()
    for c in commits:
        for match in re.finditer(r"\(#(\d+)\)$|^Merge pull request #(\d+)", c["subject"]):
            refs.add(int(match.group(1) or match.group(2)))
    return refs


def approve(repo: str, by: str, path=None) -> dict:
    by = require_person(by, "a plan is approved by a named person: pass --by with your name")
    file = _folder(repo, path) / "plan.json"
    if not file.is_file():
        raise PilotRefused("no plan to approve; run plan first")
    digest = _sha_bytes(file.read_bytes())
    ledger(repo, path).append("PlanApproved", {"plan_sha256": digest, "by": by,
                                                "at": datetime.now(timezone.utc).isoformat()})
    return {"status": "PLAN_APPROVED", "plan_sha256": digest, "by": by}


def approved_plan(repo: str, path=None) -> dict:
    file = _folder(repo, path) / "plan.json"
    approvals = [r["payload"] for r in ledger(repo, path).read() if r["record_type"] == "PlanApproved"]
    if not file.is_file() or not approvals:
        raise PilotRefused("the plan is not approved; run plan, then approve with your name")
    if _sha_bytes(file.read_bytes()) != approvals[-1]["plan_sha256"]:
        raise PilotRefused("the plan changed after it was approved; approve the new plan before collecting")
    plan = json.loads(file.read_text())
    if _sha_bytes(PROTOCOL.read_bytes()) != plan["protocol_sha256"]:
        raise PilotRefused("the labelling protocol changed after the plan pinned it; a new protocol needs a new plan")
    if controls_sha256() != plan["controls_sha256"]:
        raise PilotRefused("these control definitions differ from the ones the plan pinned; make and approve a new "
                           "plan")
    return {**plan, "approved_by": approvals[-1]["by"]}


# ---------------------------------------------------------------------------------------------------------
# 3. Collection
# ---------------------------------------------------------------------------------------------------------

class _Reader:
    """Read-only GETs to the GitHub API. Every response is kept as evidence; a rerun reads the kept copy."""

    def __init__(self, plan: dict, folder: Path, store: HashChainStore, get=None, keychain=None):
        self.plan, self.raw, self.store = plan, folder / "raw", store
        self.raw.mkdir(exist_ok=True)
        self.get = get
        self.network = 0
        self.last_url = None
        self.token, self.token_source = token(plan, keychain)

    def __call__(self, path: str, **query) -> object:
        url = self.last_url = f"{API}{path}" + (f"?{urlencode(query)}" if query else "")
        key = _sha_bytes(url.encode())[:32]
        kept = self.raw / f"{key}.json"
        if kept.exists():
            return json.loads(kept.read_bytes())
        if self.network >= self.plan["max_requests"]:
            raise CollectionStopped(f"the plan's request budget ({self.plan['max_requests']}) is used up; "
                                    "rerun collect later to continue from what was read")
        import requests
        started = datetime.now(timezone.utc)
        response = (self.get or requests.get)(url, timeout=30, allow_redirects=False, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT, "Authorization": f"Bearer {self.token}"})
        self.network += 1
        headers = {k.lower(): v for k, v in (getattr(response, "headers", None) or {}).items()}
        if response.status_code in (403, 429) and (headers.get("x-ratelimit-remaining") == "0"
                                                   or response.status_code == 429):
            reset = headers.get("x-ratelimit-reset")
            when = datetime.fromtimestamp(int(reset), timezone.utc).isoformat() if reset else "later"
            raise CollectionStopped(f"GitHub's rate limit was reached; rerun collect after {when} to continue")
        if response.status_code == 401:
            raise CollectionStopped(f"GitHub refused the token from {self.token_source} (HTTP 401). Fine-grained tokens "
                                    "expire on the date set when they were made: create a new read-only token and "
                                    "store it where this one was")
        if 300 <= response.status_code < 400:
            raise CollectionStopped(f"{urlparse(url).path}: redirected; the pilot does not follow redirects")
        if response.status_code != 200:
            raise CollectionStopped(f"{urlparse(url).path}: HTTP {response.status_code}")
        raw = response.content
        if len(raw) > MAX_BYTES:
            raise CollectionStopped(f"{urlparse(url).path}: response larger than 20 MB")
        try:
            data = json.loads(raw)
        except ValueError:
            raise CollectionStopped(f"{urlparse(url).path}: the response is not JSON")
        kept.write_bytes(raw)
        self.store.append("Read", {"url": url, "status": response.status_code, "sha256": _sha_bytes(raw),
                                   "bytes": len(raw), "kept_as": f"raw/{kept.name}", "started_at": started.isoformat(),
                                   "finished_at": datetime.now(timezone.utc).isoformat(), "user_agent": USER_AGENT,
                                   "token_from": self.token_source})
        return data

    def pages(self, path: str, stop=None, **query):
        page = 1
        while True:
            batch = self(path, **query, per_page=100, page=page)
            items = batch.get("check_runs", batch) if isinstance(batch, dict) else batch
            yield from items
            if len(items) < 100 or (stop and items and stop(items)):
                return
            page += 1


def keychain_read(service: str, run=subprocess.run, platform=None) -> str | None:
    """macOS: read the token from the Keychain at the moment of use, so it is never in any shell's environment."""
    if (platform or sys.platform) != "darwin":
        return None
    result = run(["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", service, "-w"],
                 capture_output=True, text=True)
    return result.stdout.strip() or None if result.returncode == 0 else None


def token(plan: dict, keychain=None) -> tuple[str, str]:
    """The token and where it came from (the where is recorded; the token never is)."""
    service = plan.get("keychain_service", "gaar-github")
    value = (keychain or keychain_read)(service)
    if value:
        return value, f"the macOS Keychain entry {service}"
    value = os.environ.get(plan["token_env"])
    if value:
        return value, f"the environment variable {plan['token_env']}"
    raise CollectionStopped(f"no GitHub token: on a Mac add it to the Keychain as {service} "
                            f"(security add-generic-password -a \"$USER\" -s {service} -w); elsewhere set "
                            f"{plan['token_env']} for this one command")


def collect(repo: str, path=None, get=None, keychain=None) -> dict:
    plan = approved_plan(repo, path)
    folder = _folder(repo, path)
    store = ledger(repo, path)
    read = _Reader(plan, folder, store, get, keychain)
    begin, finish = _day(plan["window"]["from"]), _day(plan["window"]["to"])
    owner_repo = f"/repos/{repo}"
    snapshot = {"repo": repo, "window": plan["window"], "plan_seed": plan["seed"], "complete": False, "stopped": None,
                "default_branch": None, "pulls": [], "commits": []}
    try:
        meta = read(owner_repo)
        branch = snapshot["default_branch"] = meta["default_branch"]
        pulls = []
        for pr in read.pages(f"{owner_repo}/pulls", stop=lambda items: _day(items[-1]["updated_at"]) < begin,
                             state="closed", base=branch, sort="updated", direction="desc"):
            if pr.get("merged_at") and begin <= _day(pr["merged_at"]) < finish:
                pulls.append(pr)
        for pr in pulls:
            number, head = pr["number"], pr["head"]["sha"]
            full = read(f"{owner_repo}/pulls/{number}")
            reviews = list(read.pages(f"{owner_repo}/pulls/{number}/reviews"))
            runs = list(read.pages(f"{owner_repo}/commits/{head}/check-runs"))
            combined = read(f"{owner_repo}/commits/{head}/status")
            snapshot["pulls"].append({
                "number": number, "url": pr["html_url"], "title": pr["title"], "merged_at": pr["merged_at"],
                "author": _actor(pr.get("user")), "merged_by": _actor(full.get("merged_by")), "head_sha": head,
                "merge_commit_sha": full.get("merge_commit_sha"),
                "reviews": [{"by": _actor(r.get("user")), "state": r.get("state"), "commit_id": r.get("commit_id"),
                             "at": r.get("submitted_at")} for r in reviews],
                "checks": [{"name": c.get("name"), "status": c.get("status"), "conclusion": c.get("conclusion")}
                           for c in runs],
                "status": {"state": combined.get("state"), "total": combined.get("total_count", 0)}})
        by_merge = {p["merge_commit_sha"]: p["number"] for p in snapshot["pulls"] if p["merge_commit_sha"]}
        for c in read.pages(f"{owner_repo}/commits", sha=branch, since=plan["window"]["from"],
                            until=plan["window"]["to"]):
            # squash and merge commits are linked by the pull request's own merge_commit_sha; anything else is
            # asked of GitHub (rebase merges, branch commits of a merge), so no change is called direct on a guess
            prs = [by_merge[c["sha"]]] if c["sha"] in by_merge else [
                p["number"] for p in read(f"{owner_repo}/commits/{c['sha']}/pulls")
                if p.get("merged_at") and p.get("base", {}).get("ref") == branch]
            linked_by = "merge_commit_sha" if c["sha"] in by_merge else "commit_pulls_lookup" if prs else None
            snapshot["commits"].append({
                "sha": c["sha"], "url": c.get("html_url"), "message": (c["commit"]["message"] or "").split("\n")[0][:200],
                "date": c["commit"]["committer"]["date"], "parents": len(c.get("parents") or []),
                "author": _actor(c.get("author")), "author_email_sha256": _email(c["commit"]["author"].get("email")),
                "committer": _actor(c.get("committer")), "pulls": sorted(set(prs)), "linked_by": linked_by})
        snapshot["complete"] = True
    except CollectionStopped as exc:
        snapshot["stopped"] = str(exc)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        # v32: a response in a shape this collector does not know is a recorded stop, never an unrecorded crash
        snapshot["stopped"] = (f"unexpected response shape ({type(exc).__name__}: {exc}) after reading "
                               f"{read.last_url}; the response is kept in raw/ for diagnosis")
    snapshot["reads_this_run"] = read.network
    snapshot["reads_kept"] = sum(1 for r in store.read() if r["record_type"] == "Read")
    raw = json.dumps(snapshot, indent=1, sort_keys=True).encode()
    (folder / "snapshot.json").write_bytes(raw)
    store.append("Collected", {"snapshot_sha256": _sha_bytes(raw), "complete": snapshot["complete"],
                               "stopped": snapshot["stopped"], "pulls": len(snapshot["pulls"]),
                               "commits": len(snapshot["commits"]), "at": datetime.now(timezone.utc).isoformat()})
    return {"status": "COLLECTED" if snapshot["complete"] else "INCOMPLETE", "stopped": snapshot["stopped"],
            "pulls": len(snapshot["pulls"]), "commits": len(snapshot["commits"]), "reads_this_run": read.network,
            "reads_kept": snapshot["reads_kept"]}


def _actor(user) -> dict | None:
    if not user:
        return None
    return {"login": user.get("login"), "id": user.get("id"), "type": user.get("type")}


def _email(address) -> str | None:
    """Emails are kept only as hashes: enough to count identities, never to contact or profile anyone."""
    return _sha_bytes((address or "").strip().lower().encode())[:16] if address else None


# ---------------------------------------------------------------------------------------------------------
# 4. Evaluation
# ---------------------------------------------------------------------------------------------------------

def _snapshot(repo: str, path=None) -> dict:
    file = _folder(repo, path) / "snapshot.json"
    if not file.is_file():
        raise PilotRefused("nothing collected yet; run collect")
    recorded = [r["payload"] for r in ledger(repo, path).read() if r["record_type"] == "Collected"]
    if not recorded or recorded[-1]["snapshot_sha256"] != _sha_bytes(file.read_bytes()):
        raise PilotRefused("snapshot.json differs from what the last collection recorded; it is evidence and is "
                           "never edited. Run collect again")
    snapshot = json.loads(file.read_text())
    if not snapshot["complete"]:
        raise PilotRefused(f"the collection is incomplete ({snapshot['stopped']}); an incomplete collection is "
                           "never evaluated as if whole. Run collect again to continue")
    return snapshot


def _latest_reviews(pr: dict) -> dict:
    latest = {}
    for r in sorted((r for r in pr["reviews"] if r["by"] and r["state"] != "COMMENTED"), key=lambda r: r["at"] or ""):
        latest[r["by"]["id"]] = r
    return latest


def evaluate_pull(pr: dict) -> dict:
    author = (pr["author"] or {}).get("id")
    approvals = [r for uid, r in _latest_reviews(pr).items() if r["state"] == "APPROVED" and uid != author]
    results = {}
    results["RC2"] = ("PASS", f"approved by {', '.join(r['by']['login'] for r in approvals)}") if approvals else \
        ("EXCEPTION", "no approval from anyone other than the author"
         + (f"; merged by {pr['merged_by']['login']}" if pr.get("merged_by") else ""))
    on_final = [r for r in approvals if r["commit_id"] == pr["head_sha"]]
    results["RC3"] = ("NOT_APPLICABLE", "no independent approval (see RC2)") if not approvals else \
        ("PASS", "an approval was made on the final commit") if on_final else \
        ("EXCEPTION", "every independent approval predates the final commit; later changes were merged unreviewed")
    failed = [c["name"] for c in pr["checks"] if c["conclusion"] in ("failure", "timed_out", "cancelled",
                                                                     "action_required")]
    running = [c["name"] for c in pr["checks"] if c["status"] != "completed"]
    status_bad = pr["status"]["total"] and pr["status"]["state"] in ("failure", "error", "pending")
    if not pr["checks"] and not pr["status"]["total"]:
        results["RC4"] = ("NOT_EVIDENCED", "no automated checks are recorded on the final commit")
    elif failed or running or status_bad:
        results["RC4"] = ("EXCEPTION", "checks on the final commit: " + "; ".join(filter(None, [
            f"failed {', '.join(sorted(set(failed)))}" if failed else "",
            f"still running {', '.join(sorted(set(running)))}" if running else "",
            f"combined status {pr['status']['state']}" if status_bad else ""])))
    else:
        results["RC4"] = ("PASS", f"{len(pr['checks'])} check run(s) passed")
    return results


def coverage(repo: str, snapshot: dict, path=None) -> dict:
    """The API collection against the git baseline the plan pinned. A missing commit refuses evaluation."""
    plan = approved_plan(repo, path)
    file = _folder(repo, path) / "baseline.json"
    if not file.is_file() or _sha_bytes(file.read_bytes()) != plan["baseline"]["sha256"]:
        raise PilotRefused("baseline.json differs from the baseline the plan pinned; it is evidence and is never "
                           "edited. Make and approve a new plan")
    baseline = json.loads(file.read_text())
    found = {c["sha"] for c in snapshot["commits"]}
    missing = [b for b in baseline["first_parent"] if b["sha"] not in found]
    hard = [m for m in missing if not m["near_edge"]]
    if hard:
        raise PilotRefused(f"the API collection is missing {len(hard)} of the {len(baseline['first_parent'])} commits "
                           f"git shows on {baseline['branch']} in the window (first: {hard[0]['sha'][:10]} "
                           f"\"{hard[0]['subject'][:60]}\"); a page was probably skipped. Nothing is evaluated on an "
                           "incomplete population: run collect again, and report this if it repeats")
    numbers = {p["number"] for p in snapshot["pulls"]} | {n for c in snapshot["commits"] for n in c["pulls"]}
    return {"git_first_parent_commits": len(baseline["first_parent"]),
            "found_by_the_api": len(baseline["first_parent"]) - len(missing),
            "near_a_window_edge_not_found": [m["sha"][:10] for m in missing],
            "pr_numbers_named_in_commit_subjects": len(baseline["pr_refs"]),
            "named_but_not_collected": [n for n in baseline["pr_refs"] if n not in numbers],
            "reading": "commits git shows are all in the API collection; PR numbers named in messages but not "
                       "collected are listed, not refused: a message can name another branch's or an older PR"}


def evaluate(repo: str, path=None) -> dict:
    snapshot = _snapshot(repo, path)
    covered = coverage(repo, snapshot, path)
    changes = []
    for pr in snapshot["pulls"]:
        changes.append({"id": f"PR#{pr['number']}", "url": pr["url"], "title": pr["title"], "at": pr["merged_at"],
                        "actor": pr["author"], "results": evaluate_pull(pr), "identity": "account ID"})
    for c in snapshot["commits"]:
        if c["pulls"]:
            continue                                     # carried by a merged pull request
        unresolved = c["author"] is None
        changes.append({"id": f"commit {c['sha'][:10]}", "url": c["url"], "title": c["message"], "at": c["date"],
                        "actor": c["author"], "identity": "unresolved (email linked to no account)" if unresolved
                        else "account ID",
                        "results": {"RC1": ("EXCEPTION", "reached the default branch without a merged pull request"
                                            + ("; the author is not linked to any account" if unresolved else ""))}})
    for change in changes:
        change["exception"] = any(r[0] == "EXCEPTION" for r in change["results"].values())
    linked = [{"id": f"commit {c['sha'][:10]}", "url": c["url"], "pull": c["pulls"][0],
               "pull_url": f"https://github.com/{repo}/pull/{c['pulls'][0]}", "title": c["message"]}
              for c in snapshot["commits"] if c.get("linked_by") == "commit_pulls_lookup"]
    result = {"repo": repo, "window": snapshot["window"], "controls_version": CONTROLS_VERSION, "coverage": covered,
              "changes": changes, "linked_by_lookup": linked, "identity": identity(snapshot),
              "counts": {rc: {s: sum(1 for c in changes if c["results"].get(rc, ("",))[0] == s)
                              for s in ("PASS", "EXCEPTION", "NOT_EVIDENCED", "NOT_APPLICABLE")} for rc in CONTROLS}}
    (_folder(repo, path) / "results.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def identity(snapshot: dict) -> dict:
    """The L1 picture on real history, as numbers of their own."""
    commits = snapshot["commits"]
    unlinked = [c for c in commits if c["author"] is None]
    emails_per_account, accounts_per_email = {}, {}
    for c in commits:
        if c["author"] and c["author_email_sha256"]:
            emails_per_account.setdefault(c["author"]["id"], set()).add(c["author_email_sha256"])
            accounts_per_email.setdefault(c["author_email_sha256"], set()).add(c["author"]["id"])
    actors = [p["author"] for p in snapshot["pulls"] if p["author"]] + [c["author"] for c in commits if c["author"]]
    return {"commits": len(commits), "commits_author_unlinked": len(unlinked),
            "accounts_with_several_emails": sum(1 for v in emails_per_account.values() if len(v) > 1),
            "emails_under_several_accounts": sum(1 for v in accounts_per_email.values() if len(v) > 1),
            "changes_by_bot_accounts": sum(1 for a in actors if a.get("type") == "Bot"),
            "pull_request_rules_use": "numeric account IDs (unique and stable: L1 does not apply to RC2 and RC3)"}


# ---------------------------------------------------------------------------------------------------------
# 5-7. Sample, label, score
# ---------------------------------------------------------------------------------------------------------

def sample(repo: str, path=None) -> dict:
    plan = approved_plan(repo, path)
    file = _folder(repo, path) / "results.json"
    if not file.is_file():
        raise PilotRefused("no results yet; run evaluate")
    changes = json.loads(file.read_text())["changes"]
    rng = random.Random(plan["seed"])
    exceptions = [c for c in changes if c["exception"]]
    clean = [c for c in changes if not c["exception"]]
    picked = sorted(rng.sample(exceptions, min(len(exceptions), plan["sample"]["exceptions"])), key=lambda c: c["id"])
    checks = sorted(rng.sample(clean, min(len(clean), plan["sample"]["clean"])), key=lambda c: c["id"])
    items = [{"item": f"E{i + 1:02d}", "change": c["id"], "url": c["url"], "kind": "exception",
              "claim": "; ".join(f"{rc}: {r[1]}" for rc, r in sorted(c["results"].items()) if r[0] == "EXCEPTION"),
              "answer_with": "TRUE_EXCEPTION, FALSE_POSITIVE or CANNOT_TELL"} for i, c in enumerate(picked)]
    items += [{"item": f"C{i + 1:02d}", "change": c["id"], "url": c["url"], "kind": "passed",
               "claim": "the rules found no exception", "answer_with": "CORRECTLY_PASSED, MISSED_EXCEPTION or "
                                                                     "CANNOT_TELL"} for i, c in enumerate(checks)]
    # v32: the linking decision is a rule output too. A commit judged "arrived through PR #N" by GitHub's lookup,
    # rather than by the PR's own merge commit, is where a direct change could be passed as reviewed.
    results = json.loads(file.read_text())
    link_pool = results.get("linked_by_lookup", [])
    links = sorted(rng.sample(link_pool, min(len(link_pool), plan["sample"].get("linked", LINKED_SAMPLE))),
                   key=lambda c: c["id"])
    items += [{"item": f"L{i + 1:02d}", "change": c["id"], "url": c["url"], "kind": "linked",
               "claim": f"this commit reached the default branch through PR #{c['pull']} ({c['pull_url']})",
               "answer_with": "CORRECTLY_LINKED, WRONGLY_LINKED or CANNOT_TELL"} for i, c in enumerate(links)]
    out = {"repo": repo, "seed": plan["seed"], "exceptions_found": len(exceptions), "passed_found": len(clean),
           "linked_by_lookup": len(link_pool), "items": items}
    raw = json.dumps(out, indent=1).encode()
    (_folder(repo, path) / "sample.json").write_bytes(raw)
    ledger(repo, path).append("SampleDrawn", {"sample_sha256": _sha_bytes(raw), "items": len(items)})
    return out


def label(repo: str, item: str, value: str, by: str, provenance: str, note: str = "", path=None) -> dict:
    by = require_person(by, "a label is made by a named person: pass --by with your name")
    if provenance not in PROVENANCE:
        raise PilotRefused(f"provenance must be one of {', '.join(PROVENANCE)}: say whether you are independent of "
                           "GaaR's builders")
    file = _folder(repo, path) / "sample.json"
    if not file.is_file():
        raise PilotRefused("no sample drawn yet; run sample")
    items = {i["item"]: i for i in json.loads(file.read_text())["items"]}
    if item not in items:
        raise PilotRefused(f"no item {item} in the sample")
    allowed = ANSWERS[items[item]["kind"]]
    if value not in allowed:
        raise PilotRefused(f"item {item} is answered with {', '.join(allowed)}")
    if value in ("FALSE_POSITIVE", "MISSED_EXCEPTION", "WRONGLY_LINKED", "CANNOT_TELL") and not note.strip():
        raise PilotRefused(f"{value} needs a note saying what you saw on GitHub")
    ledger(repo, path).append("Labelled", {"item": item, "change": items[item]["change"], "label": value, "by": by,
                                           "provenance": provenance, "note": note,
                                           "at": datetime.now(timezone.utc).isoformat()})
    return {"status": "LABELLED", "item": item, "label": value, "provenance": provenance}


def score(repo: str, path=None) -> dict:
    file = _folder(repo, path) / "sample.json"
    if not file.is_file():
        raise PilotRefused("no sample drawn yet; run sample")
    items = json.loads(file.read_text())["items"]
    latest = {}
    for r in ledger(repo, path).read():
        if r["record_type"] == "Labelled":
            latest[(r["payload"]["provenance"], r["payload"]["by"], r["payload"]["item"])] = r["payload"]["label"]
    by_labeller = {}
    for (provenance, by, item), value in latest.items():
        by_labeller.setdefault((provenance, by), {})[item] = value
    out = []
    for (provenance, by), labels in sorted(by_labeller.items()):
        n = {v: sum(1 for x in labels.values() if x == v) for v in LABELS}
        judged = n["TRUE_EXCEPTION"] + n["FALSE_POSITIVE"]
        out.append({"labeller": by, "provenance": provenance, "labelled": len(labels), "of": len(items), **n,
                    "precision": round(n["TRUE_EXCEPTION"] / judged, 3) if judged else None,
                    "missed_in_passed_sample": n["MISSED_EXCEPTION"], "wrong_links": n["WRONGLY_LINKED"],
                    "reads_as": "labelled by a builder of GaaR, not independent" if provenance == "self" else
                    "independent labels"})
    pairs = [(a, b) for a in out for b in out if a["provenance"] == "self" and b["provenance"] == "independent"]
    agreement = []
    for a, b in pairs:
        la, lb = by_labeller[("self", a["labeller"])], by_labeller[("independent", b["labeller"])]
        both = set(la) & set(lb)
        agreement.append({"self": a["labeller"], "independent": b["labeller"], "items_both": len(both),
                          "agree": sum(1 for i in both if la[i] == lb[i])})
    reviews = [r["payload"] for r in ledger(repo, path).read() if r["record_type"] == "RubricReviewed"]
    independent = [r for r in reviews if r["provenance"] == "independent"]
    return {"repo": repo, "labellers": out, "agreement": agreement,
            "rubric": ("reviewed independently: " + independent[-1]["verdict"] + f" by {independent[-1]['by']}")
            if independent else "not yet reviewed by anyone independent: every label rests on a self-approved rubric",
            "headline": None if not out else ("independent" if any(o["provenance"] == "independent" for o in out)
                                              else "self-labelled only: no independent result yet")}


def review_rubric(repo: str, by: str, provenance: str, verdict: str, note: str = "", path=None) -> dict:
    """The rubric comes first in the reviewer's packet: a blind spot in it invalidates every label beneath it."""
    by = require_person(by, "a rubric review is made by a named person: pass --by with your name")
    if provenance not in PROVENANCE:
        raise PilotRefused(f"provenance must be one of {', '.join(PROVENANCE)}")
    if verdict not in RUBRIC_VERDICTS:
        raise PilotRefused(f"verdict must be one of {', '.join(RUBRIC_VERDICTS)}")
    if verdict == "CHANGES_NEEDED" and not note.strip():
        raise PilotRefused("CHANGES_NEEDED needs a note naming what the rubric misses")
    ledger(repo, path).append("RubricReviewed", {"by": by, "provenance": provenance, "verdict": verdict, "note": note,
                                                 "protocol_sha256": _sha_bytes(PROTOCOL.read_bytes()),
                                                 "at": datetime.now(timezone.utc).isoformat()})
    return {"status": "RUBRIC_REVIEWED", "verdict": verdict, "provenance": provenance}


def packet(repo: str, path=None) -> Path:
    """The reviewer's packet: the protocol (the rubric) first, then every sampled item with its link."""
    file = _folder(repo, path) / "sample.json"
    if not file.is_file():
        raise PilotRefused("no sample drawn yet; run sample")
    drawn = json.loads(file.read_text())
    lines = [f"# Labelling packet: {repo}", "",
             "Read the protocol first and record your view of it before labelling anything:",
             f"`python tools/gaar_realrecords.py review-rubric --repo {repo} --by \"<your name>\" "
             "--provenance independent --verdict ACCEPTED` (or CHANGES_NEEDED with --note).", "", "---", "",
             PROTOCOL.read_text(), "", "---", "", "## Items", "",
             "| Item | Kind | Change | What GaaR claims | Answer with |", "|---|---|---|---|---|"]
    for i in drawn["items"]:
        lines.append(f"| {i['item']} | {i['kind']} | [{i['change']}]({i['url']}) | {i['claim']} | {i['answer_with']} |")
    lines += ["", f"Record each: `python tools/gaar_realrecords.py label --repo {repo} --item <item> --label <answer> "
              "--by \"<your name>\" --provenance independent --note \"what you saw\"`"]
    out = _folder(repo, path) / "reviewer_packet.md"
    out.write_text("\n".join(lines) + "\n")
    return out


def status(repo: str, path=None) -> dict:
    folder = _folder(repo, path)
    records = ledger(repo, path).read()
    kinds = [r["record_type"] for r in records]
    collected = [r["payload"] for r in records if r["record_type"] == "Collected"]
    return {"repo": repo, "plan": (folder / "plan.json").is_file(), "approved": "PlanApproved" in kinds,
            "reads_kept": kinds.count("Read"), "last_collection": collected[-1] if collected else None,
            "evaluated": (folder / "results.json").is_file(), "sampled": "SampleDrawn" in kinds,
            "labels": kinds.count("Labelled")}
