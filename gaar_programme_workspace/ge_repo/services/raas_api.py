from __future__ import annotations
import json,os
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

class RaaSHandler(BaseHTTPRequestHandler):
    service=RaaSService()
    server_version="GaaR-RaaS/1.0"
    def _auth(self):
        expected=os.environ.get("WB_GAAR_API_KEY","").strip()
        if not expected: return True
        header=self.headers.get("Authorization","")
        return header==f"Bearer {expected}"
    def _send(self,status,payload,etag=None):
        body=json.dumps(payload,ensure_ascii=False,sort_keys=True,default=str).encode()
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body)))
        if etag: self.send_header("ETag",etag)
        self.send_header("Cache-Control","no-store")
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if not self._auth(): return self._send(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"})
        p=urlparse(self.path); parts=[x for x in p.path.split('/') if x]
        try:
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
        if not self._auth(): return self._send(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"})
        if self.path!="/v1/passports/verify": return self._send(404,{"error":"not_found"})
        try:
            n=int(self.headers.get("Content-Length","0")); payload=json.loads(self.rfile.read(n) or b"{}")
            return self._send(200,self.service.verify(payload))
        except Exception as e: return self._send(400,{"error":type(e).__name__,"message":str(e)})
    def log_message(self,format,*args):
        if os.environ.get("WB_GAAR_API_QUIET","0")!="1": super().log_message(format,*args)

def serve(host="127.0.0.1",port=8787):
    httpd=ThreadingHTTPServer((host,int(port)),RaaSHandler); httpd.serve_forever()
