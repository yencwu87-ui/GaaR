from __future__ import annotations
import json, time, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any
import requests
from .models import RawDocument, WatcherConfig

class ConnectorError(RuntimeError): pass

class BaseConnector:
    def fetch(self, config: WatcherConfig, cursor: str|None) -> list[RawDocument]: raise NotImplementedError

class StaticConnector(BaseConnector):
    """Deterministic connector for lab/demo/live injection."""
    def fetch(self,config,cursor):
        docs=[]
        for i,row in enumerate(config.connector.get("items") or []):
            marker=str(row.get(config.cursor_field) or row.get("last_modified") or i)
            if cursor is not None and marker <= str(cursor): continue
            docs.append(RawDocument(str(row.get("id") or f"item-{i}"),str(row.get("title") or "Untitled"),str(row.get("url") or ""),str(row.get("content") or ""),row.get("published_at"),row.get("effective_at"),dict(row)))
        return docs

class HTTPJSONConnector(BaseConnector):
    def fetch(self,config,cursor):
        url=str(config.connector.get("url") or "")
        if not url: raise ConnectorError("HTTP connector url is required")
        headers=dict(config.connector.get("headers") or {})
        resp=requests.get(url,headers=headers,timeout=float(config.connector.get("timeout",20)))
        resp.raise_for_status(); body=resp.json()
        items=body if isinstance(body,list) else body.get(config.connector.get("items_field","items"),[])
        docs=[]
        for i,row in enumerate(items[:config.max_items_per_run]):
            marker=str(row.get(config.cursor_field) or row.get("last_modified") or row.get("updated") or i)
            if cursor is not None and marker <= str(cursor): continue
            content=row.get(config.connector.get("content_field","content"))
            if isinstance(content,(dict,list)): content=json.dumps(content,sort_keys=True)
            # Preserve an official feed's documented field names; CISA KEV uses
            # cveID/dateAdded rather than generic title/published_at.
            title_key = str(config.connector.get("title_field") or "title")
            date_key = str(config.connector.get("publication_field") or "published_at")
            title = str(row.get(title_key) or row.get("title") or "").strip()
            if config.source_id == "cisa-kev-awareness" and row.get("cveID"):
                title = str(row["cveID"]).strip() + " — " + " ".join(
                    str(row.get(k) or "").strip() for k in ("vendorProject", "product")
                    if row.get(k)).strip()
            docs.append(RawDocument(str(row.get("id") or row.get("cveID") or marker),
                title or "Untitled",str(row.get("url") or row.get("link") or url),
                str(content or row),row.get(date_key) or row.get("published_at") or row.get("published"),
                row.get("effective_at"),dict(row)))
        return docs

class RSSConnector(BaseConnector):
    def fetch(self,config,cursor):
        url=str(config.connector.get("url") or "")
        if not url: raise ConnectorError("RSS connector url is required")
        resp=requests.get(url,headers=dict(config.connector.get("headers") or {}),timeout=float(config.connector.get("timeout",20)))
        resp.raise_for_status(); root=ET.fromstring(resp.content); docs=[]
        nodes=root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for i,node in enumerate(nodes[:config.max_items_per_run]):
            def txt(names):
                for n in names:
                    e=node.find(n)
                    if e is not None and e.text: return e.text.strip()
                return ""
            title=txt(["title","{http://www.w3.org/2005/Atom}title"])
            link=txt(["link"])
            if not link:
                le=node.find("{http://www.w3.org/2005/Atom}link")
                if le is not None: link=le.attrib.get("href","")
            published=txt(["pubDate","{http://www.w3.org/2005/Atom}updated","{http://www.w3.org/2005/Atom}published"])
            # RSS pubDate is RFC-2822; admission requires an ISO timestamp.
            # Preserve an unparseable value so validation degrades the source
            # instead of presenting an invented publication date.
            if published:
                try:
                    from datetime import datetime
                    datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    try: published=parsedate_to_datetime(published).isoformat()
                    except (ValueError, TypeError): pass
            marker=published or link or str(i)
            if cursor is not None and marker <= str(cursor): continue
            content=txt(["description","{http://www.w3.org/2005/Atom}summary","{http://www.w3.org/2005/Atom}content"])
            docs.append(RawDocument(link or marker,title,link,content,published or None,None,{config.cursor_field:marker}))
        return docs

def connector_for(config:WatcherConfig)->BaseConnector:
    typ=str(config.connector.get("type") or "").lower()
    if typ=="static": return StaticConnector()
    if typ in {"http","json","http_json"}: return HTTPJSONConnector()
    if typ in {"rss","atom"}: return RSSConnector()
    raise ConnectorError(f"unsupported watcher connector: {typ}")
