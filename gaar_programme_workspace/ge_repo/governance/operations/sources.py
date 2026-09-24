"""Exact official snapshots are quarantined; publication is not authority approval."""
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

HOSTS = {"MAS": {"www.mas.gov.sg"}, "FCA": {"www.fca.org.uk", "www.handbook.fca.org.uk"},
         "HKMA": {"www.hkma.gov.hk"}, "NFRA": {"www.nfra.gov.cn"}}


def approved_url(issuer, url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS.get(issuer, set()) or parsed.username or parsed.password:
        raise ValueError("source URL outside the configured official origin")


def validate_content(raw, content_type):
    text = raw.decode("utf-8", errors="ignore").lower()
    if "html" in content_type:
        from html.parser import HTMLParser
        class Visible(HTMLParser):
            def __init__(self):
                super().__init__(); self.parts=[]; self.hidden=0
            def handle_starttag(self, tag, attrs):
                if tag in {"script", "style"}: self.hidden += 1
            def handle_endtag(self, tag):
                if tag in {"script", "style"}: self.hidden = max(0, self.hidden-1)
            def handle_data(self, data):
                if not self.hidden: self.parts.append(data)
        parser=Visible(); parser.feed(text)
        text=" ".join(" ".join(parser.parts).split())
        if len(text) < 200:
            raise ValueError("HTML shell contains insufficient readable publication content")
    if len(raw) < 100 or any(x in text for x in ("service is currently unavailable", "service is temporarily unavailable", "access denied", "just a moment...", "verify you are human")):
        raise ValueError("empty, maintenance or bot-challenge response; not a regulatory snapshot")
    return True


def snapshot(source, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    approved_url(source["issuer"], source["url"])
    receipt = {"source_id": source["source_id"], "issuer": source["issuer"], "url": source["url"],
        "retrieved_at": datetime.now(timezone.utc).isoformat(), "status": "UNABLE_TO_CHECK", "authority": "UNAPPROVED"}
    issuer = source["issuer"]
    class RedirectGuard(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            approved_url(issuer, newurl)
            return super().redirect_request(req, fp, code, msg, hdrs, newurl)
    try:
        with urllib.request.build_opener(RedirectGuard).open(source["url"], timeout=15) as r:
            raw = r.read(20_000_001)
            if len(raw) > 20_000_000:
                raise ValueError("snapshot exceeds 20MB limit")
            content_type = r.headers.get("Content-Type", "")
            receipt["final_url"] = r.url
            approved_url(issuer, r.url)
        validate_content(raw, content_type)
        digest = hashlib.sha256(raw).hexdigest()
        path = directory / (digest + ".snapshot")
        if not path.exists():
            with path.open("xb") as f:f.write(raw)
        receipt.update(status="QUARANTINED", sha256=digest, content_type=content_type, byte_length=len(raw), snapshot=path.name)
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    receipt_path = directory / (hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest() + ".receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2))
    return receipt


def validate_source(entry, root, trust):
    if entry.get("issuer")=="INTERNAL":
        if entry.get("authority")!="internal" or not entry.get("version"):raise ValueError("internal source cannot acquire regulatory authority")
        raw=(Path(root)/entry["snapshot_path"]).read_bytes()
        if not raw or hashlib.sha256(raw).hexdigest()!=entry["sha256"]:raise ValueError("internal source snapshot mismatch")
        from governance.production.qualification import signed_document
        payload,signer,_=signed_document(Path(root)/entry["authority_decision_ref"],trust,"governance",True)
        expected={k:entry[k] for k in ("source_id","sha256","authority","version")}
        if payload!=expected or signer.get("actor")!=entry.get("approved_by"):raise ValueError("internal policy approval does not bind source/version")
        return True
    approved_url(entry["issuer"], entry["url"])
    raw = (Path(root) / entry["snapshot_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("source snapshot hash mismatch")
    receipt = json.loads((Path(root) / entry["retrieval_receipt"]).read_text())
    validate_content(raw, receipt.get("content_type", ""))
    if receipt.get("sha256") != entry["sha256"] or receipt.get("url") != entry["url"] or receipt.get("status") != "QUARANTINED":
        raise ValueError("source receipt does not bind this exact official snapshot")
    if not entry.get("authority_decision_ref") or not entry.get("approved_by"):
        raise ValueError("source-authority approval absent")
    if entry.get("authority") not in {"binding", "guidance", "consultation", "internal"} or not entry.get("version"):
        raise ValueError("source authority/version not configured")
    from governance.result_contract import verify_signature
    from governance.investigation.store import canonical
    decision = json.loads((Path(root) / entry["authority_decision_ref"]).read_text())
    payload = decision["payload"]
    signer = trust.get(decision["key_id"], {})
    if "governance" not in signer.get("roles", []) or signer.get("actor") != entry["approved_by"]:
        raise ValueError("source approval lacks a trusted governance signer")
    expected = {k: entry[k] for k in ("source_id", "sha256", "authority", "version", "url")}
    if payload != expected or not verify_signature(signer.get("public_key", ""), decision["signature"], canonical(payload).encode()):
        raise ValueError("invalid source-authority decision signature/binding")
    return True
