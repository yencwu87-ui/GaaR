"""Regulatory watch as a subscribed intel service (kit v21).

Like a SOC threat-intel subscription: you subscribe to sources and topics; the scheduler checks each subscribed
source every 8 hours; every new publication becomes an intel item with a priority, the controls it most likely
touches, and an outlook. Triage (relevant / not relevant / keep watching) is a person's call and is recorded.

What it is and is not:

- It observes official publication indexes and feeds. It does not download or read instruments, and it never
  decides legal applicability. A match to a control is a lead for a person, not a finding.
- A failed, blocked or empty fetch is UNABLE_TO_CHECK, never "no updates" (the existing index rule).
- The outlook is labelled as such. Forecast windows come from a planning assumption the governance owner sets in
  subscriptions.yaml; trends need history and say so when they do not have it.
- State lives in the watch home (default ~/gaar-watch, or GAAR_WATCH_HOME), never inside the software folder, so
  installing a kit cannot overwrite it.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .official_index import IndexErrorSafe, OfficialIndexMonitor, load_manifest, safe_url
from .store import HashChainStore

PACKAGE = Path(__file__).resolve().parents[2]
CATALOGUE = PACKAGE / "config" / "watch_catalogue.yaml"
CONTRACTS = PACKAGE / "governance" / "knowledge" / "contracts"
DEFAULT_INTERVAL_MINUTES = 480                     # every 8 hours
RETRY_FAILED_AFTER_MINUTES = 60
TRIAGE = ("RELEVANT", "NOT_RELEVANT", "WATCH")

DEFAULT_SUBSCRIPTIONS = {
    "interval_minutes": DEFAULT_INTERVAL_MINUTES,
    "sources": ["mas-consultations-index", "mas-notices-index", "mas-guidelines-index", "cisa-kev"],
    "topics": ["artificial intelligence", "model risk", "technology risk", "outsourcing", "cyber", "data",
               "generative", "operational resilience", "third party", "fairness"],
    "frameworks": ["MAS", "MGF Agentic", "SAFR"],
    "triage_due_days": {"P1": 2, "P2": 7},
    "forecast": {"consultation_to_final_months": [6, 18],
                 "basis": "Planning assumption set by the governance owner; not derived from regulator data."},
}

STOP = set("a an and are as at be by for from in into is it its of on or that the this to with on under new "
           "paper papers consultation response responses guidelines guideline notice notices circular circulars "
           "mas amendments amendment proposed proposal revised draft final".split())


def home_path(home=None) -> Path:
    return Path(home or os.environ.get("GAAR_WATCH_HOME") or Path.home() / "gaar-watch").expanduser()


def configured(home=None) -> bool:
    """The watch runs only after someone has set it up (tools/gaar_watch.py setup)."""
    return (home_path(home) / "subscriptions.yaml").exists()


def home_dir(home=None) -> Path:
    path = home_path(home)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _when(text: str) -> datetime:
    moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------------
# Catalogue and subscriptions
# ---------------------------------------------------------------------------------------------------------

def catalogue() -> dict[str, dict]:
    rows = {r["source_id"]: {**r, "type": "index"} for r in load_manifest()}
    extra = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")) or {}
    for r in extra.get("indexes") or []:
        rows[r["source_id"]] = {**r, "type": "index"}
    for r in extra.get("feeds") or []:
        rows[r["source_id"]] = {**r, "type": "feed"}
    return rows


def subscriptions(home=None) -> dict:
    path = home_dir(home) / "subscriptions.yaml"
    if not path.exists():
        path.write_text("# Your regulatory watch subscriptions. Edit here or in the app.\n"
                        + yaml.safe_dump(DEFAULT_SUBSCRIPTIONS, sort_keys=False), encoding="utf-8")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged = {**DEFAULT_SUBSCRIPTIONS, **data}
    interval = int(merged["interval_minutes"])
    if interval < 60:
        raise ValueError("the minimum checking interval is 60 minutes")
    unknown = sorted(set(merged["sources"]) - set(catalogue()))
    if unknown:
        raise ValueError(f"subscribed to unknown source(s): {', '.join(unknown)}")
    return merged


REGIONS = {"sg": "Singapore", "us": "US", "uk": "UK", "hk": "Hong Kong", "cn": "China", "global": "GLOBAL"}


def subscribe_regions(regions: list[str], home=None, by: str = "") -> dict:
    """Subscribe every catalogue source in the named regions (sg, us, uk, hk, cn, global)."""
    unknown = sorted(set(regions) - set(REGIONS))
    if unknown:
        raise ValueError(f"unknown region(s): {', '.join(unknown)}; use {', '.join(REGIONS)}")
    wanted = {REGIONS[r] for r in regions}
    data = subscriptions(home)
    for sid, row in sorted(catalogue().items()):
        if row.get("jurisdiction") in wanted and sid not in data["sources"]:
            data = set_subscribed(sid, True, home, by)
    return data


def set_subscribed(source_id: str, subscribed: bool, home=None, by: str = "") -> dict:
    """A subscription change is a configuration change: written, and logged with who made it."""
    if source_id not in catalogue():
        raise ValueError(f"unknown source: {source_id}")
    current = subscriptions(home)
    sources = [s for s in current["sources"] if s != source_id] + ([source_id] if subscribed else [])
    data = {**current, "sources": sources}
    path = home_dir(home) / "subscriptions.yaml"
    path.write_text("# Your regulatory watch subscriptions. Edit here or in the app.\n"
                    + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _store(home, "changes").append("SubscriptionChanged", {"source_id": source_id, "subscribed": subscribed,
                                                           "by": by or "unnamed", "at": _now().isoformat()})
    return data


def _store(home, name: str) -> HashChainStore:
    return HashChainStore(home_dir(home) / f"{name}.jsonl", f"gaar.watch-{name}.v1")


def _monitor(home) -> OfficialIndexMonitor:
    return OfficialIndexMonitor(home_dir(home) / "official_indexes.jsonl")


# ---------------------------------------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------------------------------------

def _scans(home) -> list[dict]:
    """Every scan attempt, indexes and feeds alike, oldest first."""
    rows = [r["payload"] for r in _monitor(home).store.read()] + [r["payload"] for r in _store(home, "feeds").read()]
    return sorted(rows, key=lambda p: _when(p["checked_at"]))


def _last(home, source_id, successful=False):
    rows = [p for p in _scans(home) if p["source_id"] == source_id
            and (not successful or p["status"] != "UNABLE_TO_CHECK")]
    return rows[-1] if rows else None


def _json_feed(data, row) -> dict:
    items = data.get(row["items_field"]) if isinstance(data, dict) else None
    inventory = {}
    for item in items if isinstance(items, list) else []:
        key = str(item.get(row["id_field"]) or "")
        if key:
            inventory[key] = {"title": " — ".join(str(item.get(f, "")) for f in row["title_fields"] if item.get(f)),
                              "date": item.get(row.get("date_field", "")),
                              "flagged": item.get(row.get("flag_field", "")) == row.get("flag_value")}
    return inventory


def _rss(body: bytes, row) -> dict:
    """RSS 2.0 or Atom. Only links on the source's approved hosts count; anything else is ignored."""
    import xml.etree.ElementTree as ET
    if b"<!ENTITY" in body[:4096]:
        raise IndexErrorSafe("feed declares XML entities; refused")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise IndexErrorSafe(f"feed is not valid XML ({exc})")
    atom = "{http://www.w3.org/2005/Atom}"
    inventory = {}
    for item in root.iter("item"):
        link, title = (item.findtext("link") or "").strip(), (item.findtext("title") or "").strip()
        if link and title and safe_url(link, row["approved_hosts"]):
            inventory[link] = {"title": title[:400], "date": (item.findtext("pubDate") or "").strip(), "flagged": False}
    for entry in root.iter(f"{atom}entry"):
        node = entry.find(f"{atom}link")
        link = (node.get("href") if node is not None else "") or ""
        title = (entry.findtext(f"{atom}title") or "").strip()
        if link and title and safe_url(link, row["approved_hosts"]):
            inventory[link] = {"title": title[:400], "date": (entry.findtext(f"{atom}updated") or "").strip(), "flagged": False}
    return inventory


def scan_feed(row: dict, home=None, get=None) -> dict:
    """One JSON feed (e.g. CISA KEV): same baseline and failure rules as the index monitor."""
    import requests
    get = get or requests.get
    sid = row["source_id"]
    before = _last(home, sid, successful=True)
    try:
        if not safe_url(row["url"], row["approved_hosts"]):
            raise IndexErrorSafe("unapproved feed URL")
        agent = (subscriptions(home).get("user_agent") if configured(home) else None) or "GaaR-RegulatoryWatch/1.0"
        response = get(row["url"], timeout=30, allow_redirects=False, headers={"User-Agent": agent})
        if response.status_code in (301, 302, 303, 307, 308):
            raise IndexErrorSafe("feed redirected; redirects are not followed for feeds")
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            raise IndexErrorSafe("feed larger than 5 MB; refused")
        inventory = _rss(response.content, row) if row.get("format") == "rss" else _json_feed(response.json(), row)
        if not inventory:
            raise IndexErrorSafe("feed returned no items; coverage unverified")
        previous = (before or {}).get("inventory") or {}
        new = [] if before is None else [{"url": k, **v} for k, v in inventory.items() if k not in previous]
        payload = {"source_id": sid, "status": "BASELINE_ESTABLISHED" if before is None else
                   ("UPDATES_AVAILABLE" if new else "UP_TO_DATE"), "checked_at": _now().isoformat(),
                   "inventory": inventory, "new": new, "coverage": "bounded_official_feed_only", "error": None,
                   "content_sha256": hashlib.sha256(response.content).hexdigest()}
    except Exception as exc:
        payload = {"source_id": sid, "status": "UNABLE_TO_CHECK", "checked_at": _now().isoformat(),
                   "error": f"{type(exc).__name__}: {exc}"[:400], "coverage": "unverified",
                   "last_successful_check": (before or {}).get("checked_at")}
    _store(home, "feeds").append("FeedScan", payload)
    return payload


def due(source_id: str, interval_minutes: int, home=None, now=None) -> bool:
    last = _last(home, source_id)
    if last is None:
        return True
    wait = RETRY_FAILED_AFTER_MINUTES if last["status"] == "UNABLE_TO_CHECK" else interval_minutes
    return _now(now) - _when(last["checked_at"]) >= timedelta(minutes=wait)


def run_due(home=None, now=None, get=None, force=False) -> dict:
    """Check every subscribed source that is due. Called by the scheduler every tick."""
    subs, cat = subscriptions(home), catalogue()
    scanned, not_due, failed = [], [], []
    for sid in subs["sources"]:
        row = cat[sid]
        if not force and not due(sid, subs["interval_minutes"], home, now):
            not_due.append(sid)
            continue
        if row["type"] == "feed":
            result = scan_feed(row, home, get=get)
        else:
            agent = subscriptions(home).get("user_agent")        # kit v23: indexes honour it too, like feeds
            result = _monitor(home).scan({**row, "enabled": True, **({"user_agent": agent} if agent else {})}, get=get)
        scanned.append({"source_id": sid, "status": result["status"], "new": len(result.get("new") or [])})
        if result["status"] == "UNABLE_TO_CHECK":
            failed.append({"source_id": sid, "error": result.get("error")})
    return {"scanned": scanned, "not_due": not_due, "failed": failed}


# ---------------------------------------------------------------------------------------------------------
# Intel: items, matching, triage, outlook
# ---------------------------------------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9\-]+", text.lower()) if t not in STOP and len(t) > 2]


class ControlIndex:
    """BM25 over the control contracts, so a publication title can point at the controls it most likely touches."""

    def __init__(self, frameworks):
        self.controls = []
        for path in sorted(CONTRACTS.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if data.get("framework") not in frameworks:
                continue
            for c in data.get("controls") or []:
                text = " ".join([c.get("title", ""), c.get("requirement", "")] + [e.get("text", "") for e in c.get("elements") or []])
                self.controls.append({"framework": c["framework"], "control_id": c["control_id"], "title": c.get("title", ""),
                                      "tokens": _tokens(text)})
        self.df = Counter(t for c in self.controls for t in set(c["tokens"]))
        self.avg = sum(len(c["tokens"]) for c in self.controls) / max(1, len(self.controls))

    def match(self, title: str, top: int = 3) -> list[dict]:
        query = set(_tokens(title))
        if not query or not self.controls:
            return []
        n = len(self.controls)
        scored = []
        for c in self.controls:
            tf = Counter(c["tokens"])
            score = 0.0
            for t in query:
                if t in tf:
                    idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                    score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(c["tokens"]) / self.avg))
            overlap = len(query & set(c["tokens"]))
            if score > 0 and overlap >= 2:
                scored.append((score, overlap, c))
        scored.sort(key=lambda x: -x[0])
        if not scored:
            return []
        best = scored[0][0]
        return [{"framework": c["framework"], "control_id": c["control_id"], "title": c["title"],
                 "score": round(s / best, 2), "shared_terms": o}
                for s, o, c in scored[:top] if s >= 0.6 * best]


def _kind(source: dict, title: str, url: str) -> str:
    text = f"{title} {url}".lower()
    if source.get("kind") == "threat":
        return "THREAT"
    if "consult" in text:
        return "CONSULTATION"
    if re.search(r"\b(notice|guideline|circular|regulation|act|rules|standard|requirement)s?\b", text):
        return "INSTRUMENT"
    return "OTHER"


def _language(source: dict, title: str) -> dict:
    """Say what language an item is in. Chinese items arrive labelled and are never silently translated: the
    bilingual review workflow is deferred, so the label is the interim truth."""
    if re.search(r"[\u3400-\u9fff]", title) or str(source.get("language", "")).lower().startswith(("zh", "chinese")):
        return {"language": "zh", "language_label": "Chinese: not translated (read the original, or use a review aid)"}
    return {"language": "en", "language_label": None}


def items(home=None, now=None) -> list[dict]:
    """Every new publication seen after each source's baseline, as intel items. Derived, never stored."""
    subs, cat = subscriptions(home), catalogue()
    index = ControlIndex(subs["frameworks"])
    triaged = {}
    for r in _store(home, "triage").read():
        triaged[r["payload"]["item_id"]] = r["payload"]
    months = subs["forecast"]["consultation_to_final_months"]
    out, seen = [], set()
    for scan in _scans(home):
        source = cat.get(scan["source_id"], {"source_id": scan["source_id"]})
        for entry in scan.get("new") or []:
            url, title = entry["url"], entry.get("title", "")
            item_id = hashlib.sha256(f"{scan['source_id']}|{url}".encode()).hexdigest()[:16]
            if item_id in seen:
                continue
            seen.add(item_id)
            kind = _kind(source, title, url)
            topics = [t for t in subs["topics"] if t.lower() in title.lower()]
            matches = [] if kind == "THREAT" else index.match(title)
            if kind == "THREAT":
                priority = "P1" if entry.get("flagged") else "P2"
            elif kind == "INSTRUMENT":
                priority = "P1" if (matches or topics) else "P3"
            elif kind == "CONSULTATION":
                priority = "P2" if (matches or topics) else "P3"
            else:
                priority = "P3"
            first_seen = _when(scan["checked_at"])
            forecast = None
            if kind == "CONSULTATION":
                forecast = {"final_expected_from": (first_seen + timedelta(days=30.4 * months[0])).date().isoformat(),
                            "final_expected_to": (first_seen + timedelta(days=30.4 * months[1])).date().isoformat(),
                            "basis": subs["forecast"]["basis"]}
            out.append({"item_id": item_id, "source_id": scan["source_id"], "authority": source.get("authority"),
                        "jurisdiction": source.get("jurisdiction"), "title": title, "url": url, "kind": kind,
                        "priority": priority, "first_seen": first_seen.isoformat(), "topics": topics,
                        "matched_controls": matches, "forecast": forecast, "flagged": bool(entry.get("flagged")),
                        "triage": triaged.get(item_id), **_language(source, title)})
    order = {"P1": 0, "P2": 1, "P3": 2}
    return sorted(out, key=lambda i: (order[i["priority"]], -_when(i["first_seen"]).timestamp()))


def triage(item_id: str, decision: str, by: str, note: str = "", home=None) -> dict:
    if decision not in TRIAGE:
        raise ValueError(f"triage must be one of {', '.join(TRIAGE)}")
    if not by.strip():
        raise ValueError("triage needs the name of the person making it")
    if item_id not in {i["item_id"] for i in items(home)}:
        raise ValueError("unknown intel item")
    return _store(home, "triage").append("IntelTriaged", {"item_id": item_id, "decision": decision, "by": by.strip(),
                                                          "note": note.strip(), "at": _now().isoformat()})["payload"]


def needs_triage(home=None, now=None) -> list[dict]:
    """What the inbox shows: untriaged P1/P2 regulatory items one by one; new threats as one digest per source."""
    found = [i for i in items(home, now) if not i["triage"] and i["priority"] in ("P1", "P2")]
    regulatory = [i for i in found if i["kind"] != "THREAT"]
    digests = []
    for sid in sorted({i["source_id"] for i in found if i["kind"] == "THREAT"}):
        threats = [i for i in found if i["kind"] == "THREAT" and i["source_id"] == sid]
        digests.append({"item_id": f"digest:{sid}", "source_id": sid, "kind": "THREAT_DIGEST",
                        "priority": "P1" if any(t["flagged"] for t in threats) else "P2",
                        "title": f"{len(threats)} new known-exploited vulnerabilities from {sid}"
                                 + (f" ({sum(t['flagged'] for t in threats)} linked to ransomware)" if any(t["flagged"] for t in threats) else ""),
                        "members": [t["item_id"] for t in threats],
                        "first_seen": min(t["first_seen"] for t in threats)})
    return regulatory + digests


def triage_digest(source_id: str, decision: str, by: str, note: str = "", home=None) -> int:
    members = [i for i in items(home) if i["source_id"] == source_id and i["kind"] == "THREAT" and not i["triage"]]
    for member in members:
        triage(member["item_id"], decision, by, note, home)
    return len(members)


def health(home=None, now=None) -> list[dict]:
    subs, cat = subscriptions(home), catalogue()
    out = []
    for sid in subs["sources"]:
        rows = [p for p in _scans(home) if p["source_id"] == sid]
        last = rows[-1] if rows else None
        ok = [p for p in rows if p["status"] != "UNABLE_TO_CHECK"]
        fails, failing_since = 0, None
        for p in reversed(rows):
            if p["status"] != "UNABLE_TO_CHECK":
                break
            fails, failing_since = fails + 1, p["checked_at"]
        if last is None:
            state = "NEVER_CHECKED"
        elif last["status"] == "UNABLE_TO_CHECK":
            state = "FAILING"
        elif _now(now) - _when(last["checked_at"]) > timedelta(minutes=2 * subs["interval_minutes"]):
            state = "OVERDUE"
        else:
            state = "OK"
        next_due = (_when(last["checked_at"]) + timedelta(minutes=RETRY_FAILED_AFTER_MINUTES if state == "FAILING"
                                                          else subs["interval_minutes"])).isoformat() if last else None
        out.append({"source_id": sid, "authority": cat[sid].get("authority"), "state": state,
                    "jurisdiction": cat[sid].get("jurisdiction"),
                    # a source from public documentation is unverified until its first successful scan here
                    "address_verified": bool(ok) or cat[sid].get("verified", True) is not False,
                    "last_checked": last["checked_at"] if last else None,
                    "last_success": ok[-1]["checked_at"] if ok else None,
                    "last_status": last["status"] if last else None, "error": (last or {}).get("error"),
                    "consecutive_failures": fails, "failing_since": failing_since, "next_due": next_due,
                    "baseline": bool(ok), "tracked": len((ok[-1] if ok else {}).get("inventory") or {})})
    return out


def outlook(home=None, now=None) -> dict:
    """Labelled forecasts: topic trends and the controls most likely to need reassessment. Never a finding."""
    now = _now(now)
    found = items(home, now)
    history_days = 0
    scans = [p for p in _scans(home) if p["status"] != "UNABLE_TO_CHECK"]
    if scans:
        history_days = (now - _when(scans[0]["checked_at"])).days
    trends = []
    for topic in subscriptions(home)["topics"]:
        hits = [i for i in found if topic in i["topics"]]
        recent = sum(now - _when(i["first_seen"]) <= timedelta(days=30) for i in hits)
        prior = sum(timedelta(days=30) < now - _when(i["first_seen"]) <= timedelta(days=120) for i in hits)
        if history_days < 60:
            state = "INSUFFICIENT_HISTORY"
        elif recent >= 2 and recent > 1.5 * (prior / 3):
            state = "RISING"
        else:
            state = "STEADY"
        if hits or history_days >= 60:
            trends.append({"topic": topic, "last_30_days": recent, "prior_90_days": prior, "state": state})
    impact = Counter()
    basis = {}
    for i in found:
        if i["kind"] in ("INSTRUMENT", "CONSULTATION") and now - _when(i["first_seen"]) <= timedelta(days=180):
            for m in i["matched_controls"]:
                key = (m["framework"], m["control_id"], m["title"])
                impact[key] += 2 if i["kind"] == "INSTRUMENT" else 1
                basis.setdefault(key, []).append(i["title"])
    controls = [{"framework": k[0], "control_id": k[1], "title": k[2], "weight": w, "because_of": basis[k][:3]}
                for k, w in impact.most_common(10)]
    return {"history_days": history_days, "trends": trends, "controls_likely_to_need_reassessment": controls,
            "label": "Outlook: forecasts from publication patterns and a stated planning assumption. "
                     "Not a finding, not legal applicability."}


def propose_control(item_id: str, by: str, home=None) -> dict:
    """One click from a watch item to a DRAFT control in the governed requirements-draft format (kit v22).

    The draft is the whole MAS library plus one proposed control carrying the source, the publication's title and the
    controls it most likely overlaps. It lands in the watch home, never in the live library. Admitting it into the
    assessment suite stays a named approval with a change ticket (governance/regulatory_change.promote_draft)."""
    from governance.regulatory_change import build_draft, load_requirements, save_draft
    item = next((i for i in items(home) if i["item_id"] == item_id), None)
    if item is None:
        raise ValueError("unknown intel item")
    if not by.strip():
        raise ValueError("a draft needs the name of the person proposing it")
    controls = dict(load_requirements().get("controls") or {})
    new_id = f"MX-{item_id[:6].upper()}"
    overlaps = ", ".join(f"{m['framework']} {m['control_id']}" for m in item["matched_controls"]) or "none found"
    controls[new_id] = {
        "requirement": f"[DRAFT - the control owner writes the requirement] Obligations arising from: {item['title']}",
        "elements": [], "boundary": {}, "assurance_mode": "human_only", "severity": "medium", "status": "proposed",
        "source": [{"title": item["title"], "url": item["url"], "authority": item.get("authority"),
                    "first_seen": item["first_seen"], "watch_item": item_id}],
        "rationale": f"Proposed by {by.strip()} from regulatory watch item {item_id}. Overlaps with existing controls: "
                     f"{overlaps}. Decide whether this is a new control or an amendment to one of those.",
    }
    draft = build_draft(controls, source_title=item["title"], source_reference=item["url"],
                        notes=f"Drafted from regulatory watch by {by.strip()}; not in force until promoted.")
    drafts = home_dir(home) / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    target = save_draft(draft, drafts / f"mas-watch-{item_id}-draft.yaml")
    if not item["triage"]:
        triage(item_id, "RELEVANT", by, f"control drafted: {target.name}", home)
    return {"status": "CONTROL_DRAFTED", "draft": str(target), "proposed_control": new_id, "overlaps": overlaps,
            "next": "the control owner writes the requirement and elements; then a governance approver promotes it: "
                    "python -c \"from governance.regulatory_change import promote_draft; "
                    f"print(promote_draft('{target}', approved_by='NAME', change_ticket='TICKET'))\""}
