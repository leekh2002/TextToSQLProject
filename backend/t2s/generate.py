"""Candidate SQL generation through Ollama's chat API (spec 3 ④)."""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib import error, request

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_START = re.compile(r"\b(select|with)\b", re.IGNORECASE)


def extract_sql(text: str | None) -> str | None:
    if not text:
        return None
    fenced = _FENCE.search(text)
    body = fenced.group(1) if fenced else text
    if body.strip().upper().startswith("UNKNOWN"):
        return "UNKNOWN"
    start = _START.search(body)
    if not start:
        return None
    sql = body[start.start():].split(";", 1)[0].strip()
    return sql or None


def ollama_chat(messages, *, model, temperature, seed=None, timeout: float = 120.0) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("OLLAMA_BASE_URL is not set")
    options = {"temperature": temperature, "num_predict": 512}
    if seed is not None:
        options["seed"] = seed
    payload = {"model": model, "messages": messages, "stream": False, "options": options}
    req = request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"Ollama request failed: HTTP {exc.code}") from exc
    except OSError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    try:
        body = json.loads(raw.decode("utf-8"))
        content = body["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("unexpected Ollama chat response") from exc
    if not isinstance(content, str):
        raise RuntimeError("unexpected Ollama chat response")
    return content


def generate_candidates(message_sets, *, model, temperature, chat=ollama_chat) -> list[str | None]:
    def one(index_and_messages):
        index, messages = index_and_messages
        try:
            if index == 0:
                return chat(messages, model=model, temperature=0.0)
            return chat(messages, model=model, temperature=temperature, seed=index)
        except Exception:
            return None

    if not message_sets:
        return []
    with ThreadPoolExecutor(max_workers=len(message_sets)) as pool:
        return list(pool.map(one, enumerate(message_sets)))
