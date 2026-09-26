"""Official email alerts as a watch source (kit v24).

Some regulators block automated clients on their websites (MAS answers with a challenge page, the FCA with HTTP
403). Both publish official email alerts: MAS through its subscription services, the FCA through its daily news and
publications alert. This source reads those alerts from your own mailbox and records every publication link in them.

Two ways in, one parser:
- a folder: ~/gaar-watch/mail/<source_id>/ holding .eml files (drag the alert emails there from Mail), or
- IMAP: set `mail:` in subscriptions.yaml; matching alerts are copied into that same folder first, so every alert
  the watch acted on is kept as the evidence it came from. The password is read from the environment variable named
  in `password_env`; it is never written anywhere.

The rules the other sources follow hold here too. A folder with no alerts, an unreadable mailbox, or no alert for
longer than the source's `stale_after_days` is UNABLE_TO_CHECK, never "no updates". The first successful read sets
the baseline. Links count only if they point at the regulator's approved hosts and publication paths. A tracking
redirect is decoded locally and never followed. Sender checks are recorded as they are: a From domain on the
allowlist, and DKIM only if the mailbox recorded a pass for that domain.
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from .official_index import IndexErrorSafe, _Links, safe_url

MAX_MESSAGE_BYTES = 5 * 1024 * 1024


def folder(home_dir: Path, source_id: str) -> Path:
    path = Path(home_dir) / "mail" / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sender_ok(address: str, domains: list[str]) -> bool:
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    return any(domain == d or domain.endswith("." + d) for d in domains)


def _dkim(message, domains: list[str]) -> str:
    for header in message.get_all("Authentication-Results") or []:
        for match in re.finditer(r"dkim=(\w+)[^;]*?header\.(?:d|i)=@?([\w.-]+)", str(header), re.I):
            if match.group(1).lower() == "pass" and any(match.group(2).lower().endswith(d) for d in domains):
                return "pass"
    return "not verified"


def unwrap(url: str, redirect_hosts: list[str]) -> str:
    """Decode a mail-tracking redirect to the address it carries, without following it."""
    host = urlparse(url).hostname or ""
    if host not in redirect_hosts:
        return url
    query = parse_qs(urlparse(url).query)
    for key in ("url", "u", "target", "redirect"):
        if query.get(key):
            return query[key][0]
    rest = url.split(host, 1)[1]
    start = re.search(r"https?(?::|%3A)(?:/|%2F){2}", rest, re.I)
    if not start:
        return url
    target = re.sub(r"/\d+/[0-9a-f]{16}[0-9a-f-]*(?:/.*)?$", "", rest[start.start():], flags=re.I)  # GovDelivery tail
    return unquote(target)


def links(message, row: dict) -> dict[str, str]:
    """Publication links in one alert: {url: title}. Only approved hosts and publication paths count."""
    found: list[tuple[str, str]] = []
    for part in message.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        body = part.get_payload(decode=True) or b""
        text = body.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html":
            parser = _Links()
            parser.feed(text)
            found += [(h, t) for h, t in parser.links if h]
        else:
            found += [(u, "") for u in re.findall(r"https://[^\s<>\"')]+", text)]
    out: dict[str, str] = {}
    for href, title in found:
        url = unwrap(href.strip(), row.get("redirect_hosts") or []).split("#", 1)[0]
        if not safe_url(url, row["approved_hosts"]):
            continue
        if not any(urlparse(url).path.startswith(p) for p in row["path_prefixes"]):
            continue
        title = " ".join(title.split()) or urlparse(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        if len(title) > len(out.get(url, "")):
            out[url] = title[:400]
    return out


def fetch_imap(row: dict, mail: dict, target: Path, since: datetime, imap_factory=None) -> int:
    """Copy matching alerts from the mailbox into the source's folder. Returns how many were new."""
    password_env = mail.get("password_env")
    if password_env and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", str(password_env)):
        # D26 (v24 round): a password was typed where the variable's name belongs. Never echo the value.
        raise IndexErrorSafe("mail.password_env must be the NAME of an environment variable (for example "
                             "GAAR_MAIL_PASSWORD), never the password itself. Remove the value from "
                             "subscriptions.yaml, and change that password if it was a real one")
    password = os.environ.get(password_env or "")
    if not mail.get("imap_host") or not mail.get("imap_user") or not password:
        raise IndexErrorSafe(f"mail is not configured: set imap_host, imap_user and password_env in subscriptions.yaml,"
                             f" and put the password in the environment variable {password_env or '(unnamed)'}")
    client = (imap_factory or imaplib.IMAP4_SSL)(mail["imap_host"])
    try:
        client.login(mail["imap_user"], password)
        client.select(mail.get("folder", "INBOX"), readonly=True)
        added = 0
        for domain in row["sender_domains"]:
            status, data = client.search(None, "FROM", f'"{domain}"', "SINCE", since.strftime("%d-%b-%Y"))
            if status != "OK":
                raise IndexErrorSafe(f"mailbox search failed for {domain}")
            for num in (data[0] or b"").split():
                status, parts = client.fetch(num, "(RFC822)")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                if not raw or len(raw) > MAX_MESSAGE_BYTES:
                    continue
                path = target / f"{hashlib.sha256(raw).hexdigest()[:24]}.eml"
                if not path.exists():
                    path.write_bytes(raw)
                    added += 1
        return added
    finally:
        try:
            client.logout()
        except Exception:
            pass


def read(row: dict, home_dir: Path, previous: dict | None, now: datetime, mail: dict | None = None,
         imap_factory=None) -> dict:
    """One read of an email-alert source. Returns a scan payload in the same shape as index and feed scans."""
    sid = row["source_id"]
    target = folder(home_dir, sid)
    fetched = None
    if mail and mail.get("imap_host"):
        since = now - timedelta(days=int(row.get("stale_after_days", 14)) * 2)
        fetched = fetch_imap(row, mail, target, since, imap_factory)
    messages, ignored, newest, verified = [], [], None, 0
    for path in sorted(target.glob("*.eml")):
        raw = path.read_bytes()
        if len(raw) > MAX_MESSAGE_BYTES:
            ignored.append({"file": path.name, "why": "larger than 5 MB"})
            continue
        message = email.message_from_bytes(raw)
        sender = parseaddr(message.get("From", ""))[1]
        if not _sender_ok(sender, row["sender_domains"]):
            ignored.append({"file": path.name, "why": f"sender {sender or '(none)'} is not on the allowlist"})
            continue
        try:
            sent = parsedate_to_datetime(message.get("Date"))
            sent = sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            sent = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        dkim = _dkim(message, row["sender_domains"])
        verified += dkim == "pass"
        newest = max(newest, sent) if newest else sent
        messages.append({"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "sent": sent.isoformat(),
                         "subject": str(message.get("Subject", ""))[:200], "dkim": dkim, "links": links(message, row)})
    if not messages:
        raise IndexErrorSafe(f"no alert emails from {', '.join(row['sender_domains'])} yet"
                             + (f"; subscribe at {row['subscribe_url']}" if row.get("subscribe_url") else "")
                             + f" and put the alerts in {target}" + (f" ({len(ignored)} file(s) ignored)" if ignored else ""))
    stale = int(row.get("stale_after_days", 14))
    if now - newest > timedelta(days=stale):
        raise IndexErrorSafe(f"no alert received in {stale} days (latest {newest.date().isoformat()}); "
                             "the subscription may have lapsed")
    inventory = {}
    for m in messages:
        for url, title in m["links"].items():
            inventory.setdefault(url, {"title": title, "date": m["sent"][:10], "flagged": False,
                                       "sender_dkim": m["dkim"], "alert": m["file"]})
    if not inventory:
        raise IndexErrorSafe("the alert emails contain no links to the regulator's publication pages; coverage unverified")
    before = (previous or {}).get("inventory") or {}
    new = [] if previous is None else [{"url": k, **v} for k, v in inventory.items() if k not in before]
    return {"source_id": sid, "status": "BASELINE_ESTABLISHED" if previous is None else
            ("UPDATES_AVAILABLE" if new else "UP_TO_DATE"), "checked_at": now.isoformat(), "inventory": inventory,
            "new": new, "coverage": "official_email_alerts_only", "error": None,
            "messages_read": len(messages), "messages_ignored": ignored, "fetched_from_mailbox": fetched,
            "sender_dkim_pass": verified, "latest_alert": newest.isoformat(),
            "sender_check": "From domain on the allowlist; DKIM only where the mailbox recorded a pass"}
