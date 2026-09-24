"""Conservative official-document intake. Fetch is NEVER commit, push or source approval.

Optional Playwright renders a landing page for discovering official links. PDF bytes
are always retrieved from the HTTP response, never page.pdf() (which prints a new PDF).
Browser challenges are reported as DEGRADED, not bypassed.
"""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from datetime import datetime, timezone

MAX_BYTES = 12 * 1024 * 1024
ALLOWED = {
    "MAS": {"www.mas.gov.sg", "mas.gov.sg"},
    "FCA": {"www.fca.org.uk", "fca.org.uk"},
    "HKMA": {"www.hkma.gov.hk", "hkma.gov.hk", "brdr.hkma.gov.hk"},
    "NFRA": {"www.nfra.gov.cn", "nfra.gov.cn", "big5.nfra.gov.cn"},
}
CHALLENGE = (b"cloudflare", b"captcha", b"turnstile", b"access denied", b"enable javascript", b"service unavailable")

class IntakeError(ValueError):
    pass


def approved_url(url: str, regulator: str) -> bool:
    u = urlsplit(url)
    return bool(u.scheme == "https" and u.hostname in ALLOWED[regulator.upper()]
                and u.port in (None, 443) and not u.username and not u.password)


class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, regulator: str):
        super().__init__(); self.regulator = regulator
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not approved_url(newurl, self.regulator):
            raise IntakeError("redirect leaves approved official domain: " + newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Fetched:
    url: str
    data: bytes
    content_type: str
    etag: str | None
    last_modified: str | None


def fetch_bytes(url: str, regulator: str, *, opener=None) -> Fetched:
    regulator = regulator.upper()
    if regulator not in ALLOWED or not approved_url(url, regulator):
        raise IntakeError("unapproved official document URL")
    opener = opener or build_opener(SafeRedirect(regulator))
    try:
        with opener.open(Request(url, headers={"User-Agent": "GaaR-Regulatory-Intake/1.0 (compliance archive)", "Accept": "application/pdf,text/html;q=0.9"}), timeout=25) as response:
            final_url = response.geturl()
            if not approved_url(final_url, regulator):
                raise IntakeError("response URL outside official domain")
            data = response.read(MAX_BYTES + 1)
            if not data or len(data) > MAX_BYTES:
                raise IntakeError("empty or oversized document (12 MiB cap)")
            ct = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
            if data.startswith(b"%PDF-"):
                ct = "application/pdf"
            elif data[:512].lstrip().lower().startswith((b"<!doctype html", b"<html")) or ct == "text/html":
                ct = "text/html"
                low = data[:100000].lower()
                if any(marker in low for marker in CHALLENGE):
                    raise IntakeError("DEGRADED: challenge, blocked or maintenance HTML; never treat as publication")
            else:
                raise IntakeError("INVALID_DOCUMENT: expected original PDF or HTML response")
            return Fetched(final_url, data, ct, response.headers.get("ETag"), response.headers.get("Last-Modified"))
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("DEGRADED: official retrieval failed: " + str(exc)) from exc


class Links(HTMLParser):
    def __init__(self): super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href", "")
            if href: self.urls.append(href)


def candidate_pdfs(html: str, base: str, regulator: str, *, match: str = "") -> list[str]:
    parser = Links(); parser.feed(html)
    found = set()
    for href in parser.urls:
        absolute = urljoin(base, href)
        if approved_url(absolute, regulator) and urlsplit(absolute).path.lower().endswith(".pdf") and match.lower() in absolute.lower():
            found.add(absolute)
    return sorted(found)


def browser_landing(url: str, regulator: str) -> tuple[bytes, str, list[str]]:
    """Optional JS-rendered link discovery, not anti-bot or access-control evasion."""
    if not approved_url(url, regulator): raise IntakeError("unapproved landing page")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise IntakeError("Playwright not installed: pip install playwright && python -m playwright install chromium") from exc
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(accept_downloads=False)
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if response is None or response.status >= 400 or not approved_url(page.url, regulator):
                    raise IntakeError("DEGRADED: browser landing request rejected or redirected")
                raw = response.body()
                if not raw or len(raw) > MAX_BYTES or any(x in raw[:100000].lower() for x in CHALLENGE):
                    raise IntakeError("DEGRADED: invalid/challenged browser landing")
                links = page.locator("a[href]").evaluate_all("els => els.map(e => e.href)")
                return raw, page.url, [x for x in links if approved_url(x, regulator)]
            finally:
                browser.close()
    except IntakeError: raise
    except Exception as exc: raise IntakeError("DEGRADED: browser fetch failed: " + str(exc)) from exc


def record_receipt(output: Path, regulator: str, landing: Fetched | None, doc: Fetched, *, method: str) -> dict:
    """Write exact origin response bytes and metadata in private intake directory.

    Intake is a candidate; returned receipt does not attest legal status/applicability.
    """
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(doc.data).hexdigest()
    suffix = ".pdf" if doc.content_type == "application/pdf" else ".html"
    dest = output / (digest + suffix)
    if dest.exists():
        if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
            raise IntakeError("existing intake file does not match hash")
    else:
        with dest.open("xb") as fh: fh.write(doc.data)
    receipt = {"state":"QUARANTINED_FOR_HUMAN_REVIEW", "regulator":regulator,
               "document_url":doc.url, "landing_url":landing.url if landing else None,
               "retrieved_at": datetime.now(timezone.utc).isoformat(),
               "source_sha256":digest, "source_bytes":len(doc.data), "source_content_type":doc.content_type,
               "etag":doc.etag, "last_modified":doc.last_modified, "retrieval_method":method,
               "source_file":str(dest), "authority_verified":False, "applicability_verified":False,
               "signed_commit":False, "impact_review_queued":False}
    if landing:
        ld = hashlib.sha256(landing.data).hexdigest()
        lp = output / (ld + ".landing.html")
        if not lp.exists():
            with lp.open("xb") as fh: fh.write(landing.data)
        elif hashlib.sha256(lp.read_bytes()).hexdigest() != ld:
            raise IntakeError("existing landing snapshot hash mismatch")
        receipt["landing_sha256"] = ld
    rp = output / (digest + ".receipt.json")
    if not rp.exists():
        with rp.open("x", encoding="utf-8") as fh: json.dump(receipt, fh, indent=2)
    return receipt
