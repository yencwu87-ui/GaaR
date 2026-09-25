from __future__ import annotations
import hmac,json,os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from governance.ai_auditor.living_view import all_living_views,living_view
from governance.result_store import ResultStore
from governance.result_contract import ResultStateLog
from governance.passport import governance_passport,verify_passport
from governance.autopilot import AutopilotScheduler, load_policy as load_autopilot_policy
from governance.watcher import EmissionStore, HealthStore, load_sources
from governance.quality_gate import QualityGateLog

class RaaSService:
    def health(self): return {"service":"gaar-raas","status":"ok","schema":"gaar.raas.v1"}
    def results(self):
        states=ResultStateLog(); out=[]
        for r in ResultStore().read():
            out.append({"result_id":r.result_id,"result_version":r.result_version,"decision":r.decision.value,"state":states.current_state(r.result_id).value if states.current_state(r.result_id) else "UNKNOWN","requirement_version_id":r.requirement_version_id,"evidence_set_id":r.evidence_set_id,"content_hash":r.content_hash})
        return out
    def result(self,rid):
        r=ResultStore().get(rid)
        if not r: raise KeyError(rid)
        return r.model_dump(mode="json")
    def living(self,control_id=None,framework=None): return living_view(control_id,framework) if control_id else all_living_views()
    def quality(self,rid):
        g=QualityGateLog().latest_for_result(rid)
        if not g: return {"result_id":rid,"status":"NOT_RUN","blockers":[]}
        return g.model_dump(mode="json") if hasattr(g,"model_dump") else g.to_dict()
    def passport(self,rid): return governance_passport(rid)
    def verify(self,payload): return verify_passport(payload)
    def autopilot(self): return AutopilotScheduler(policy=load_autopilot_policy()).status()
    def watcher(self):
        hs=HealthStore(); sources=load_sources(); emissions=EmissionStore().read()
        return {"sources":[{"source_id":s.source_id,"authority":s.authority.value,"jurisdiction":s.jurisdiction,"health":hs.latest(s.source_id)} for s in sources],"emission_count":len(emissions),"emitted_changes":sum((r.get("payload") or {}).get("emission_status")=="EMITTED" for r in emissions)}

class PeriodService:
    """Block 1 (B1-7): the sealed periods, verifications and warranties, read-only. Nothing here writes, and nothing
    creates the RaaS home: with no RaaS state every list is empty. The planted-case seed never leaves the tenant."""
    def _ready(self):
        from governance import raas
        return raas.exists()
    def periods(self):
        from governance.raas import store
        return [r["payload"] for r in store("periods").read()] if self._ready() else []
    def period(self,pack_id):
        from governance import raas
        if not self._ready(): raise KeyError(pack_id)
        folder=raas.home()/"packs"; pack=folder/f"{pack_id}.json"; passport=folder/f"{pack_id}.passport.json"
        if "/" in pack_id or not pack.is_file() or not passport.is_file(): raise KeyError(pack_id)
        return {"pack":json.loads(pack.read_text()),"passport":json.loads(passport.read_text())}
    def verifications(self):
        from governance.raas import verifier
        return [{k:v for k,v in r.items() if k!="seed"} for r in verifier.verifications()] if self._ready() else []
    def warranties(self):
        from governance.raas import store
        if not self._ready(): return []
        rows=[r["payload"] for r in store("warranty").read()]
        return [dict(c,claims=[x for x in rows if "payout" in x and x["certificate_id"]==c["certificate_id"]]) for c in rows if "cap" in c]
    def verify(self,payload):
        from governance.raas import seal
        if not isinstance(payload,dict) or "pack" not in payload or "passport" not in payload:
            raise ValueError("send the pack and its passport: {\"pack\": ..., \"passport\": ...}")
        register=seal.key_register() if self._ready() else []
        key=register[-1]["public_key_b64"] if register else None
        return seal.verify(payload["pack"],payload["passport"],key)

class RaaSHandler(BaseHTTPRequestHandler):
    service=RaaSService()
    periods=PeriodService()
    server_version="GaaR-RaaS/1.0"
    def _auth(self,required=False):
        expected=os.environ.get("WB_GAAR_API_KEY","").strip()
        if not expected: return not required        # the period endpoints are never open: no key set, no answer
        header=self.headers.get("Authorization","")
        return hmac.compare_digest(header.encode(),f"Bearer {expected}".encode())
    def _send(self,status,payload,etag=None):
        body=json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body)))
        if etag: self.send_header("ETag",etag)
        self.send_header("Cache-Control","no-store")
        self.end_headers(); self.wfile.write(body)
    RAAS=("periods","verifications","warranties","packs")
    def do_GET(self):
        p=urlparse(self.path); parts=[x for x in p.path.split('/') if x]
        tenant=len(parts)>=2 and parts[0]=="v1" and parts[1] in self.RAAS
        if not self._auth(required=tenant): return self._send(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"})
        try:
            if p.path=="/v1/periods": return self._send(200,self.periods.periods())
            if len(parts)==3 and parts[:2]==["v1","periods"]:
                obj=self.periods.period(parts[2]); return self._send(200,obj,etag='"'+obj['passport']['content_hash']+'"')
            if p.path=="/v1/verifications": return self._send(200,self.periods.verifications())
            if p.path=="/v1/warranties": return self._send(200,self.periods.warranties())
            if p.path=="/health": return self._send(200,self.service.health())
            if p.path=="/v1/results": return self._send(200,self.service.results())
            if len(parts)==3 and parts[:2]==["v1","results"]:
                obj=self.service.result(parts[2]); return self._send(200,obj,etag='"'+obj['content_hash']+'"')
            if len(parts)==4 and parts[:2]==["v1","results"] and parts[3]=="passport": return self._send(200,self.service.passport(parts[2]))
            if len(parts)==4 and parts[:2]==["v1","results"] and parts[3]=="quality": return self._send(200,self.service.quality(parts[2]))
            if p.path=="/v1/living": return self._send(200,self.service.living())
            if len(parts)==3 and parts[:2]==["v1","living"]:
                q=parse_qs(p.query); return self._send(200,self.service.living(parts[2],(q.get('framework') or [None])[0]))
            if p.path=="/v1/autopilot/status": return self._send(200,self.service.autopilot())
            if p.path=="/v1/watcher/status": return self._send(200,self.service.watcher())
            return self._send(404,{"error":"not_found"})
        except KeyError as e: return self._send(404,{"error":"not_found","id":str(e.args[0])})
        except Exception as e: return self._send(500,{"error":type(e).__name__,"message":str(e)})
    def do_POST(self):
        tenant=self.path=="/v1/packs/verify"
        if not self._auth(required=tenant): return self._send(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"})
        if self.path not in ("/v1/passports/verify","/v1/packs/verify"): return self._send(404,{"error":"not_found"})
        try:
            n=int(self.headers.get("Content-Length","0")); payload=json.loads(self.rfile.read(n) or b"{}")
            if tenant: return self._send(200,self.periods.verify(payload))
            return self._send(200,self.service.verify(payload))
        except Exception as e: return self._send(400,{"error":type(e).__name__,"message":str(e)})
    def log_message(self,format,*args):
        if os.environ.get("WB_GAAR_API_QUIET","0")!="1": super().log_message(format,*args)

def serve(host="127.0.0.1",port=8787):
    httpd=ThreadingHTTPServer((host,int(port)),RaaSHandler); httpd.serve_forever()
