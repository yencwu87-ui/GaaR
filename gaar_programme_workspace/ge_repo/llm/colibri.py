"""Colibri OpenAI-compatible transport.

Colibri exposes a text-only OpenAI-compatible HTTP API (typically at http://127.0.0.1:8000/v1).
This adapter keeps the governance engine provider-neutral: the inference policy decides when to
use Colibri, while this module owns only transport, timeout and response-shape handling.
"""
from __future__ import annotations

import os
from urllib.parse import urljoin

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "glm-5.2-colibri"


def base_url() -> str:
    raw = os.environ.get("COLIBRI_BASE_URL") or DEFAULT_BASE_URL
    return raw.rstrip("/")


def model_name() -> str:
    return os.environ.get("COLIBRI_MODEL") or DEFAULT_MODEL


def api_key() -> str:
    return os.environ.get("COLIBRI_API_KEY", "")


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = api_key().strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def token_budget(explicit: int | None = None) -> int:
    """Resolve the transport generation cap.

    The inference router should normally pass an explicit budget selected from the task tier /
    control complexity plan. The environment fallback keeps direct adapter use configurable.
    """
    if explicit is not None:
        value = int(explicit)
    else:
        value = int(os.environ.get("COLIBRI_MAX_TOKENS", os.environ.get("OLLAMA_NUM_PREDICT", "2400")))
    if value < 1:
        raise ValueError("Colibri token budget must be >= 1")
    return value


def chat(system: str, user: str, *, model: str | None = None, max_tokens: int | None = None) -> str:
    """Call Colibri and return the assistant text.

    The governance validators remain responsible for deciding whether the returned text is
    admissible. This function only enforces transport-level correctness. Generation budget is
    supplied by the governed inference plan when available.
    """
    chosen = model or model_name()
    timeout_s = float(os.environ.get("COLIBRI_TIMEOUT", "120"))
    max_tokens = token_budget(max_tokens)
    payload = {
        "model": chosen,
        "stream": False,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
    }
    url = f"{base_url()}/chat/completions"
    try:
        response = requests.post(url, timeout=timeout_s, json=payload, headers=_headers())
    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            f"Colibri request timed out after {timeout_s:g}s for model '{chosen}' at {url}. "
            "Check that the Colibri service is running and the model is loaded."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            f"Cannot connect to Colibri at {base_url()}. Start `coli serve` and confirm "
            f"model '{chosen}' is available."
        ) from exc

    if not response.ok:
        detail = (response.text or "").strip().replace("\n", " ")[:500]
        raise RuntimeError(
            f"Colibri returned HTTP {response.status_code} for model '{chosen}' at {url}. "
            f"{detail or 'No response detail.'}"
        )

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise RuntimeError(
            f"Colibri returned an unexpected response for model '{chosen}' at {url}: {exc}"
        ) from exc
    if not isinstance(content, str):
        raise RuntimeError(f"Colibri returned non-text content for model '{chosen}'.")
    return content


def health() -> dict:
    """Return the Colibri health response without hiding non-2xx state."""
    timeout_s = float(os.environ.get("COLIBRI_HEALTH_TIMEOUT", "5"))
    url = f"{base_url().rsplit('/v1', 1)[0]}/health"
    try:
        response = requests.get(url, timeout=timeout_s, headers=_headers())
    except requests.RequestException as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}
    try:
        data = response.json()
    except ValueError:
        data = {"text": response.text[:500]}
    return {"ok": response.ok, "status_code": response.status_code, "url": url, "data": data}
