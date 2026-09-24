"""Arena contestants. Each takes a case and returns what the model attempted, verbatim, plus the parsed answer.

    ollama:<model>          local Ollama (http://127.0.0.1:11434), e.g. ollama:qwen2.5:14b, ollama:mistral-nemo:12b
    colibri                 Colibri's OpenAI-compatible API (COLIBRI_BASE_URL, default http://127.0.0.1:8000/v1)
    mlx:<model>             an MLX server (mlx_lm.server; MLX_BASE_URL, default http://127.0.0.1:8080/v1)
    openai:<base_url>|<model>   any other OpenAI-compatible endpoint
    jev                     Jev, per the adapter contract (GAAR_JEV_URL, GAAR_JEV_MODEL, and GAAR_JEV_KEY_ENV naming the
                            environment variable that holds the key: the key itself is never written anywhere)
    baseline:rules          the pilot's own deterministic checks: what every model has to beat
    baseline:always-supported   a model that always says "authorised": the false-assurance floor
    baseline:always-contradicted  a model that flags everything: the alarm-fatigue floor
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urlparse

from .cases import CHOICES

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class NotConfigured(RuntimeError):
    pass


def parse(raw: str) -> dict:
    """Read the model's reply without improving it: no answer or no confidence is a HOLD, never a pass."""
    try:
        match = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(match.group(0)) if match else {}
    except (ValueError, AttributeError):
        data = {}
    answer = str(data.get("answer") or data.get("choice") or data.get("label") or "").strip().upper()
    confidence = data.get("confidence")
    if confidence is None and isinstance(data.get("probabilities"), dict):
        confidence = data["probabilities"].get(answer)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = None
    if answer not in CHOICES:
        return {"answer": "HOLD", "hold_reason": "no valid answer", "confidence": confidence}
    if confidence is None or not 0 <= confidence <= 1:
        return {"answer": "HOLD", "hold_reason": "no confidence field (adapter contract: a HOLD)", "attempted": answer,
                "confidence": None}
    return {"answer": answer, "confidence": confidence, "violations": data.get("violations") or [],
            "reason": str(data.get("reason", ""))[:400]}


class Contestant:
    name = "contestant"
    local = True
    family = "unknown"

    def raw(self, prompt: str) -> str:
        raise NotImplementedError("a contestant must say how it is asked")

    def ask(self, case: dict) -> dict:
        if not self.local and case["provenance"] != "constructed":
            raise PermissionError(f"{self.name} is not on this machine; it may only receive constructed cases")
        started = time.monotonic()
        try:
            text = self.raw(case["prompt"])
            error = None
        except NotConfigured:
            raise
        except Exception as exc:
            text, error = "", f"{type(exc).__name__}: {exc}"[:300]
        parsed = parse(text) if error is None else {"answer": "HOLD", "hold_reason": "call failed", "confidence": None}
        return {"raw": text[:4000], "parsed": parsed, "error": error, "seconds": round(time.monotonic() - started, 2)}


class Ollama(Contestant):
    def __init__(self, model: str, host: str | None = None):
        self.model, self.name, self.family = model, f"ollama:{model}", model.split(":")[0].split("-")[0]
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.local = urlparse(self.host).hostname in LOCAL_HOSTS

    def raw(self, prompt: str) -> str:
        import requests
        r = requests.post(f"{self.host}/api/generate", timeout=300,
                          json={"model": self.model, "prompt": prompt, "format": "json", "stream": False,
                                "options": {"temperature": 0}})
        r.raise_for_status()
        return r.json().get("response", "")


class OpenAICompatible(Contestant):
    def __init__(self, base_url: str, model: str, name: str, key_env: str | None = None, family: str | None = None):
        self.base_url, self.model, self.name, self.key_env = base_url.rstrip("/"), model, name, key_env
        self.local = urlparse(self.base_url).hostname in LOCAL_HOSTS
        self.family = family or model.split("-")[0].split(":")[0]

    def raw(self, prompt: str) -> str:
        import requests
        headers = {"Content-Type": "application/json"}
        if self.key_env and os.environ.get(self.key_env):
            headers["Authorization"] = f"Bearer {os.environ[self.key_env]}"
        r = requests.post(f"{self.base_url}/chat/completions", headers=headers, timeout=300,
                          json={"model": self.model, "temperature": 0,
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class Jev(Contestant):
    """Jev per the adapter contract: a choice question; the answer must carry a confidence or it is a HOLD.
    The request shape follows the contract's choice form; confirm it against Jev's own documentation."""
    name, family = "jev", "jev"

    def __init__(self):
        self.url, self.model = os.environ.get("GAAR_JEV_URL"), os.environ.get("GAAR_JEV_MODEL")
        key_env = os.environ.get("GAAR_JEV_KEY_ENV")
        if not self.url or not self.model or not key_env:
            raise NotConfigured("Jev is not configured: set GAAR_JEV_URL, GAAR_JEV_MODEL and GAAR_JEV_KEY_ENV")
        self.key = os.environ.get(key_env, "")
        self.local = urlparse(self.url).hostname in LOCAL_HOSTS

    def raw(self, prompt: str) -> str:
        import requests
        r = requests.post(self.url, timeout=300, headers={"Authorization": f"Bearer {self.key}"},
                          json={"model": self.model, "input": prompt, "choices": list(CHOICES)})
        r.raise_for_status()
        return json.dumps(r.json())


class Baseline(Contestant):
    family = "baseline"

    def __init__(self, kind: str):
        self.kind, self.name = kind, f"baseline:{kind}"

    def ask(self, case: dict) -> dict:
        if self.kind == "always-supported":
            parsed = {"answer": "SUPPORTED", "confidence": 0.9}
        elif self.kind == "always-contradicted":
            parsed = {"answer": "CONTRADICTED", "confidence": 0.9}
        else:
            parsed = _rules(case)
        return {"raw": json.dumps(parsed), "parsed": parsed, "error": None, "seconds": 0.0}


def _rules(case: dict) -> dict:
    """The deterministic checks on the case's own records."""
    from governance.investigation.change_test import reconcile_changes
    r = case["records"]
    change = r["change"]
    when = change["occurred_at"]
    package = {"scope": "arena", "as_of": when, "policy": {"incident_lookback_hours": 24, "failed_change_requires_recovery": True},
               "collection": {"complete": True, "source_ids": ["arena"], "period_start": "2000-01-01T00:00:00+00:00",
                              "period_end": "2100-01-01T00:00:00+00:00"},
               "changes": [change], "tickets": [r["ticket"]] if isinstance(r["ticket"], dict) else [],
               "privilege_grants": r["privilege_grants_for_implementer"], "freezes": r["freezes"],
               "freeze_exceptions": r["freeze_exceptions_for_this_change"], "incidents": [],
               "recoveries": r["recoveries_for_this_change"]}
    codes = {f["code"] for f in reconcile_changes(package)["findings"]}
    ticket = r["ticket"] if isinstance(r["ticket"], dict) else {}
    if ticket.get("approved_by") and ticket.get("approved_by") == change["actor_id"]:
        codes.add("SELF_APPROVAL")
    return {"answer": "CONTRADICTED" if codes else "SUPPORTED", "confidence": 1.0, "violations": sorted(codes)}


def build(spec: str) -> Contestant:
    if spec.startswith("ollama:"):
        return Ollama(spec.split(":", 1)[1])
    if spec == "colibri":
        from llm import colibri
        return OpenAICompatible(colibri.base_url(), colibri.model_name(), "colibri", key_env="COLIBRI_API_KEY", family="glm")
    if spec.startswith("mlx:"):
        return OpenAICompatible(os.environ.get("MLX_BASE_URL", "http://127.0.0.1:8080/v1"), spec[4:], spec)
    if spec.startswith("openai:"):
        base, model = spec[7:].split("|", 1)
        return OpenAICompatible(base, model, spec)
    if spec == "jev":
        return Jev()
    if spec.startswith("baseline:") and spec[9:] in ("rules", "always-supported", "always-contradicted"):
        return Baseline(spec[9:])
    raise ValueError(f"unknown contestant: {spec}")
