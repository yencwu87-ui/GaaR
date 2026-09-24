"""Stand-in model servers for checking a GaaR install without real models.

    python tools/gaar_fake_models.py &
    python tools/gaar_phase0.py --mode C --ollama http://127.0.0.1:21434 \
        --colibri http://127.0.0.1:18000/v1 --workspace ~/gaar-selftest

Default ports 21434 and 18000 do not clash with a real Ollama (11434) or Colibri (8000).
Answers are scripted. A passing self-test proves the plumbing, never the judgment.

Ollama on :11434 (/api/tags, /api/chat) and an OpenAI-compatible Colibri on
:8000 (/v1/models, /v1/chat/completions). Colibri enforces max_tokens <= 1024,
serves one request at a time (429 when busy) and truncates output at the cap.
Ollama rejects calls that omit num_ctx. PERSONA=good answers like a competent
assessor; PERSONA=falsepass answers like qwen2.5:7b did (all SUPPORTED, no refs).
"""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PERSONA = os.environ.get("PERSONA", "good")
DELAY = float(os.environ.get("DELAY", "0.5"))
LOG = []
busy = threading.Lock()


def collect(node, key, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                out.append(v)
            collect(v, key, out)
    elif isinstance(node, list):
        for v in node:
            collect(v, key, out)
    return out


def answer(prompt_text):
    p = json.loads(prompt_text)
    task = p.get("task", "")
    ev = list(dict.fromkeys(collect(p, "evidence_id", [])))
    hyp = list(dict.fromkeys(collect(p, "hypothesis_id", [])))
    tests = list(dict.fromkeys(collect(p, "test_id", [])))
    if task.startswith("Examine each obligation"):
        elements = [e["element_id"] for e in p["expectations"]["elements"]]
        if PERSONA in ("falsepass", "qwen"):  # qwen2.5:7b run B behaviour: cites evidence, still all SUPPORTED
            return {"findings": [{"element_id": e, "status": "SUPPORTED", "evidence_refs": ["CHANGES", "POPULATION"],
                                  "rationale": "All changes in the provided evidence comply."} for e in elements]}
        statuses = {"chg.1": ("CONTRADICTED", ["CHANGES"]), "chg.2": ("CONTRADICTED", ["CHANGES"]),
                    "chg.3": ("NOT_EVIDENCED", ["CHANGES"]), "chg.4": ("CONTRADICTED", ["POPULATION"])}
        return {"findings": [{"element_id": e, "status": statuses[e][0], "evidence_refs": statuses[e][1],
                              "rationale": f"Examined the admitted records for {e}; see cited evidence."} for e in elements]}
    if task.startswith("Propose evidence-grounded") and PERSONA == "qwen":   # J7: ignores the basis rule
        return {"status": "COMPLETED", "retrieval": [], "hypotheses": [], "limitations": [],
                "dependencies": [{"dependency_id": "INTERNAL-003", "upstream": "CHANGE.MGMT", "downstream": "ACCESS.PRIVILEGED",
                                  "relation": "Actual credential use may differ from approval",
                                  "basis_refs": ["knowledge-sha256:" + "0" * 64], "status": "hypothesis"}]}
    if task.startswith("Propose evidence-grounded"):
        return {"status": "COMPLETED", "retrieval": [], "dependencies": [],
                "hypotheses": [{"hypothesis_id": "H1", "claim": "Production changes executed outside their approved authorisation",
                                "basis_refs": [ev[0]], "alternatives": ["Unexported emergency approvals", "Clock skew between sources"],
                                "compensating_controls_review": "Check recorded exceptions and independent audit events",
                                "dependencies": [], "material": True}],
                "limitations": ["Computed on supplied exports only"]}
    if task.startswith("Prioritize read-only tests"):
        return {"policy_id": "constructed-cm-v1", "tests": [
            {"test_id": "T1", "hypothesis_id": "H1", "tool": "change_authorization", "version": "2", "input_ref": "CHANGES",
             "decision_impact": "Separates authorisation discrepancies from missing records", "priority": 1},
            {"test_id": "T2", "hypothesis_id": "H1", "tool": "change_population", "version": "1", "input_ref": "POPULATION",
             "decision_impact": "Tests whether the change population reconciles", "priority": 2}]}
    if task.startswith("Treat every proposed dependency"):
        k = p["knowledge"]
        return {"knowledge_sha256": k["knowledge_sha256"], "treatments": [
            {"edge_id": e["edge_id"], "status": "INVESTIGATED", "material": True,
             "rationale": "Bound to the supplied exports and the executed comparisons",
             "evidence_refs": ev, "test_refs": tests or ["T1"], "risk_refs": hyp or ["H1"]} for e in k["edges"]]}
    if task.startswith("Independently attempt disproof"):
        return {"status": "COMPLETED", "input_head": p["investigation"]["input_head"],
                "reviewed_refs": ev + hyp + tests,
                "disproof_attempts": ["Tested whether unexported emergency approvals explain the discrepancies"],
                "missing_explanations": ["Self-approval on at least one ticket was not examined"],
                "findings": [{"finding_id": "C1", "material": True,
                              "claim": "The approver and implementer are the same person on one ticket",
                              "basis_refs": [ev[0], hyp[0] if hyp else "H1"]}]}
    raise ValueError("unknown stage: " + task[:60])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.server.kind == "ollama" and self.path == "/api/tags":
            return self.reply(200, {"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2:latest"}]})
        if self.server.kind == "colibri" and self.path == "/v1/models":
            return self.reply(200, {"data": [{"id": "glm-5.2-colibri"}]})
        self.reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][-1]["content"]
        if self.server.kind == "ollama":
            ctx = (body.get("options") or {}).get("num_ctx")
            if not ctx:
                return self.reply(400, {"error": "test server: num_ctx not sent, prompt would be truncated"})
            LOG.append(("ollama", body["model"], ctx, len(prompt)))
            time.sleep(DELAY)
            return self.reply(200, {"message": {"content": json.dumps(answer(prompt))}})
        cap = body.get("max_tokens", 0)
        if not 1 <= cap <= 1024:
            return self.reply(400, {"error": {"message": "`max_tokens` must be an integer between 1 and 1024."}})
        if not busy.acquire(blocking=False):
            return self.reply(429, {"error": {"message": "busy"}})
        try:
            time.sleep(DELAY)
            if prompt == "Reply OK":
                return self.reply(200, {"choices": [{"message": {"content": "OK"}}]})
            text = json.dumps(answer(prompt))
            LOG.append(("colibri", body["model"], cap, len(prompt)))
            if len(text) / 4 > cap:
                text = text[:cap * 4]
            return self.reply(200, {"choices": [{"message": {"content": text}}]})
        finally:
            busy.release()


def serve(port, kind):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.kind = kind
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    serve(int(os.environ.get("OLLAMA_PORT", "21434")), "ollama")
    serve(int(os.environ.get("COLIBRI_PORT", "18000")), "colibri")
    print("fake models up", PERSONA, flush=True)
    while True:
        time.sleep(3600)
