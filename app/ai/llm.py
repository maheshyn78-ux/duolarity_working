"""Thin client for a local open-source LLM served by Ollama (https://ollama.com).

Works with any Ollama model (qwen2.5, llama3.1, mistral, gemma2, phi3 ...). If Ollama isn't running the
rest of the app keeps working with the rule-based engine; AI features degrade gracefully.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)
_status_cache: dict[str, Any] = {"at": 0.0, "value": None}


class LLMUnavailable(Exception):
    pass


def _base() -> str:
    return get_settings().ollama_base_url.rstrip("/")


def status(force: bool = False) -> dict[str, Any]:
    s = get_settings()
    if s.ai_provider.lower() != "ollama":
        return {"enabled": False, "available": False, "provider": s.ai_provider, "model": None, "detail": "AI disabled (AI_PROVIDER)"}
    if not force and _status_cache["value"] and time.time() - _status_cache["at"] < 10:
        return _status_cache["value"]
    out: dict[str, Any] = {"enabled": True, "available": False, "provider": "ollama", "model": s.ollama_model, "base_url": s.ollama_base_url}
    try:
        r = httpx.get(f"{_base()}/api/tags", timeout=3)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        want = s.ollama_model
        have = any(n == want or n.split(":")[0] == want.split(":")[0] and (":" not in want or n == want) for n in names)
        out["installed_models"] = names
        out["available"] = have
        out["detail"] = "ready" if have else f"Ollama is running but model '{want}' is not pulled. Run: ollama pull {want}"
    except Exception as e:
        out["detail"] = f"Ollama not reachable at {s.ollama_base_url} ({type(e).__name__}). Start it with: ollama serve"
    _status_cache.update(at=time.time(), value=out)
    return out


def is_available() -> bool:
    return bool(status().get("available"))


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float = 0.0, max_tokens: int | None = None) -> str:
    s = get_settings()
    if not is_available():
        raise LLMUnavailable(status().get("detail", "LLM unavailable"))
    options: dict[str, Any] = {"temperature": temperature, "num_ctx": s.ollama_num_ctx}
    if max_tokens:
        options["num_predict"] = max_tokens
    payload: dict[str, Any] = {"model": s.ollama_model, "messages": messages, "stream": False, "options": options}
    if json_mode:
        payload["format"] = "json"
    try:
        r = httpx.post(f"{_base()}/api/chat", json=payload, timeout=s.ollama_timeout_seconds)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except httpx.HTTPError as e:
        _status_cache["value"] = None
        raise LLMUnavailable(f"Ollama request failed: {e}") from e


def chat_json(messages: list[dict], max_tokens: int | None = None) -> Any:
    raw = chat(messages, json_mode=True, max_tokens=max_tokens)
    return loads_lenient(raw)


def loads_lenient(raw: str) -> Any:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"[\[{].*[\]}]", raw, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # truncated array: salvage complete objects
    objs = re.findall(r"\{[^{}]*\}", raw)
    out = []
    for o in objs:
        try:
            out.append(json.loads(o))
        except json.JSONDecodeError:
            continue
    if out:
        return {"transactions": out}
    raise ValueError("model did not return valid JSON")
