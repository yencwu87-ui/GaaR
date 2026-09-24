#!/usr/bin/env python3
"""Readiness check for the two local LLM services used by the governance workbench."""
from __future__ import annotations

import os
import sys

import requests


def check_ollama() -> tuple[bool, str]:
    base = (os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"
    try:
        response = requests.get(f"{base}/api/tags", timeout=5)
        response.raise_for_status()
        models = {m.get("name") for m in (response.json().get("models") or [])}
    except Exception as exc:
        return False, f"Ollama unavailable at {base}: {type(exc).__name__}: {exc}"
    if model not in models:
        return False, f"Ollama is up but model '{model}' is not installed. Available: {sorted(x for x in models if x)}"
    return True, f"Ollama OK — {base} — model {model}"


def check_colibri() -> tuple[bool, str]:
    base = (os.environ.get("COLIBRI_BASE_URL") or "http://127.0.0.1:8000/v1").rstrip("/")
    health = base.rsplit("/v1", 1)[0] + "/health"
    model = os.environ.get("COLIBRI_MODEL") or "glm-5.2-colibri"
    headers = {}
    key = os.environ.get("COLIBRI_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = requests.get(health, timeout=5, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        return False, f"Colibri unavailable at {health}: {type(exc).__name__}: {exc}"
    try:
        response = requests.get(f"{base}/models", timeout=5, headers=headers)
        response.raise_for_status()
        rows = response.json().get("data") or response.json().get("models") or []
        models = {x.get("id") or x.get("name") for x in rows if isinstance(x, dict)}
    except Exception as exc:
        return False, f"Colibri health is up but /v1/models failed: {type(exc).__name__}: {exc}"
    if models and model not in models:
        return False, f"Colibri is up but model '{model}' was not advertised. Available: {sorted(x for x in models if x)}"
    return True, f"Colibri OK — {base} — model {model}"


def main() -> int:
    checks = [check_ollama()]
    if os.environ.get("WB_COLIBRI_ENABLED", "0") == "1" or os.environ.get("COLIBRI_BASE_URL"):
        checks.append(check_colibri())
    ok = True
    for passed, message in checks:
        print(("[PASS] " if passed else "[FAIL] ") + message)
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
