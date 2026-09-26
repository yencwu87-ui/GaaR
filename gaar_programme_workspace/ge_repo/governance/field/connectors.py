"""Read-only connectors. Each reads one source named in the mandate and returns its rows with a receipt.

- git: the change history of a repository clone (`git log` only; no other git command is run).
- table: an export file a system produces on schedule (CSV or JSON), e.g. an ITSM ticket export or an IAM grant
  report, from a folder the mandate names.
- http_json: one bounded HTTPS GET to an approved host (no redirects, size cap, token from a named environment
  variable), for systems with a read API.

A connector never writes to a source. A receipt records what was read, when, by which connector version, and the hash
of exactly what came back, so any delivery can be traced to the reads that produced it.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

VERSION = "field-connectors/1"
MAX_BYTES = 20 * 1024 * 1024
FIELD_SEP, RECORD_SEP = "\x1f", "\x1e"


class SourceUnavailable(RuntimeError):
    """The source could not be read. Always an evidence gap, never an empty result."""


def _receipt(source: dict, request: str, raw: bytes, rows: int, started: datetime) -> dict:
    return {"source_id": source["source_id"], "connector": source["connector"], "connector_version": VERSION,
            "request": request, "response_sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "rows": rows,
            "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat()}


def read_git(source: dict, root: Path, since: datetime, until: datetime) -> tuple[list[dict], dict]:
    repo = (Path(root) / source["repo"]).resolve() if not Path(source["repo"]).is_absolute() else Path(source["repo"])
    branch = source.get("branch", "main")
    if not re.fullmatch(r"[\w./-]+", branch):
        raise SourceUnavailable(f"{source['source_id']}: branch name {branch!r} is not allowed")
    command = ["git", "-C", str(repo), "log", branch, "--no-color", f"--since={since.isoformat()}",
               f"--until={until.isoformat()}", f"--format=%H{FIELD_SEP}%ae{FIELD_SEP}%cI{FIELD_SEP}%T{FIELD_SEP}%B{RECORD_SEP}"]
    started = datetime.now(timezone.utc)
    try:
        done = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceUnavailable(f"{source['source_id']}: git could not run ({type(exc).__name__})") from exc
    if done.returncode != 0:
        raise SourceUnavailable(f"{source['source_id']}: git log failed: {done.stderr.decode(errors='replace').strip()[:200]}")
    rows = []
    for record in done.stdout.decode("utf-8", errors="replace").split(RECORD_SEP):
        parts = record.strip("\n").split(FIELD_SEP)
        if len(parts) != 5:
            continue
        sha, email, committed, tree, body = parts
        trailers = dict(re.findall(r"^([A-Za-z][\w-]*):\s*(.+)$", body, re.M))
        rows.append({"sha": sha, "author_email": email, "committed_at": committed, "tree": tree,
                     "subject": body.strip().splitlines()[0] if body.strip() else "", "body": body, **trailers})
    return rows, _receipt(source, " ".join(command[3:6]) + f" {since.date()}..{until.date()}", done.stdout, len(rows), started)


def read_table(source: dict, root: Path, since=None, until=None) -> tuple[list[dict], dict]:
    path = (Path(root) / source["path"]).resolve() if not Path(source["path"]).is_absolute() else Path(source["path"])
    started = datetime.now(timezone.utc)
    if not path.is_file():
        raise SourceUnavailable(f"{source['source_id']}: export {path.name} has not arrived")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise SourceUnavailable(f"{source['source_id']}: export larger than 20 MB")
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    else:
        data = json.loads(raw)
        for key in (source.get("items_path") or "").split(".") if source.get("items_path") else []:
            data = data[key]
        rows = list(data)
    return rows, _receipt(source, f"read {path.name}", raw, len(rows), started)


def read_http_json(source: dict, root=None, since=None, until=None, get=None) -> tuple[list[dict], dict]:
    import requests
    get = get or requests.get
    url = source["url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in source.get("allowed_hosts", []) or parsed.username:
        raise SourceUnavailable(f"{source['source_id']}: endpoint outside the mandate's approved HTTPS hosts")
    headers = {"Accept": "application/json"}
    if source.get("token_env"):
        token = os.environ.get(source["token_env"])
        if not token:
            raise SourceUnavailable(f"{source['source_id']}: the credential variable {source['token_env']} is not set")
        headers["Authorization"] = f"Bearer {token}"
    started = datetime.now(timezone.utc)
    response = get(url, headers=headers, timeout=30, allow_redirects=False)
    if response.status_code in (301, 302, 303, 307, 308):
        raise SourceUnavailable(f"{source['source_id']}: redirected; field agents do not follow redirects")
    if response.status_code != 200:
        raise SourceUnavailable(f"{source['source_id']}: HTTP {response.status_code}")
    raw = response.content
    if len(raw) > MAX_BYTES:
        raise SourceUnavailable(f"{source['source_id']}: response larger than 20 MB")
    data = json.loads(raw)
    for key in (source.get("items_path") or "").split(".") if source.get("items_path") else []:
        data = data[key]
    rows = list(data)
    return rows, _receipt(source, f"GET {parsed.scheme}://{parsed.netloc}{parsed.path}", raw, len(rows), started)


READERS = {"git": read_git, "table": read_table, "http_json": read_http_json}


# ---------------------------------------------------------------------------------------------------------
# Mapping rows to the evidence contract. Declarative, so a person can read what the agent does to each column.
# ---------------------------------------------------------------------------------------------------------

def _value(row: dict, spec):
    if not isinstance(spec, dict):
        return row.get(spec)                                 # shorthand: `field: column`
    if "value" in spec:
        return spec["value"]
    value = row.get(spec["column"])
    if value is None or value == "":
        return spec.get("default")
    value = str(value)
    if "regex" in spec:
        match = re.search(spec["regex"], value)
        value = match.group(1) if match else None
        if value is None:
            return spec.get("default")
    if "split" in spec:
        return [v.strip() for v in value.split(spec["split"]) if v.strip()]
    return spec.get("prefix", "") + value[: spec["slice"]] if "slice" in spec else spec.get("prefix", "") + value


def map_rows(rows: list[dict], field_map: dict, required: tuple[str, ...]) -> tuple[list[dict], list[str]]:
    """Map each row; a row missing a required field is reported, never silently dropped."""
    out, problems = [], []
    for i, row in enumerate(rows, 1):
        record = {field: _value(row, spec) for field, spec in field_map.items()}
        missing = [f for f in required if record.get(f) in (None, "", [])]
        if missing:
            problems.append(f"row {i}: no {', '.join(missing)}")
        else:
            out.append(record)
    return out, problems
