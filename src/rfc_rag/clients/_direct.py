import json
import logging
import random
import time

import httpx

from .. import config
from .base import LLMError

name = "direct"

last_usage: dict | None = None
log = logging.getLogger(__name__)

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
BASE_DELAY = 1.0


def _post(path: str, body: dict, timeout: float, base: str | None = None,
          key: str | None = None) -> httpx.Response:
    """POST with backoff on the statuses a hosted provider actually returns."""
    base = base or config.LLM_BASE_URL
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            r = httpx.post(f"{base}{path}", json=body,
                           headers=_headers(key), timeout=timeout)
            if r.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS - 1:
                delay = float(r.headers.get("retry-after") or 0) or (
                    BASE_DELAY * 2 ** attempt + random.uniform(0, 0.5))
                log.warning("%s -> %s, retrying in %.1fs (attempt %d/%d)",
                            path, r.status_code, delay, attempt + 1, MAX_ATTEMPTS)
                time.sleep(delay)
                continue
            return r
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            if attempt == MAX_ATTEMPTS - 1:
                break
            delay = BASE_DELAY * 2 ** attempt + random.uniform(0, 0.5)
            log.warning("%s -> %s, retrying in %.1fs (attempt %d/%d)",
                        path, type(exc).__name__, delay, attempt + 1, MAX_ATTEMPTS)
            time.sleep(delay)
    raise LLMError(f"{path} failed after {MAX_ATTEMPTS} attempts: {last}")


def _headers(key: str | None = None) -> dict[str, str]:
    key = config.api_key() if key is None else key
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _parse_sse(text: str) -> str:
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        if "error" in chunk:
            raise LLMError(chunk["error"].get("message", payload))
        for choice in chunk.get("choices", []):
            out.append(choice.get("delta", {}).get("content") or "")
    return "".join(out)


def _raise_for_status(r: httpx.Response, path: str) -> None:
    """Convert transport errors into LLMError, as the backend contract requires.

    The provider URL and key stay out of the message; callers surface this to
    users, and `429` is kept so throttling can be told apart from a real fault.
    """
    if r.is_success:
        return
    detail = ""
    try:
        body = r.json()
        body = body[0] if isinstance(body, list) and body else body
        detail = str(body.get("error", {}).get("message", ""))[:200]
    except Exception:
        detail = r.text[:200]
    raise LLMError(f"{path} returned {r.status_code}: {detail}")


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0,
             model: str | None = None) -> str:
    body = {
        "model": model or config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning_effort": "low",
    }
    r = _post("/chat/completions", body, timeout=600)
    if "text/event-stream" in r.headers.get("content-type", ""):
        return _parse_sse(r.text).strip()

    _raise_for_status(r, "/chat/completions")
    data = r.json()
    if "error" in data:
        raise LLMError(str(data["error"]))
    global last_usage
    last_usage = data.get("usage")
    message = data["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content and message.get("reasoning_content"):
        raise LLMError("empty content: reasoning consumed the max_tokens budget")
    return content


def embed(texts: list[str]) -> list[list[float]]:
    body: dict = {"model": config.EMBED_MODEL, "input": texts}
    if config.EMBED_DIMENSIONS:
        body["dimensions"] = config.EMBED_DIMENSIONS
    r = _post("/embeddings", body, timeout=300,
              base=config.EMBED_BASE_URL, key=config.embed_api_key())
    _raise_for_status(r, "/embeddings")
    data = r.json()
    if "error" in data:
        raise LLMError(str(data["error"]))
    global last_usage
    last_usage = data.get("usage")
    vectors = [d["embedding"] for d in data["data"]]
    bad = {len(v) for v in vectors} - {config.EMBED_DIM}
    if bad:
        raise LLMError(f"expected dim {config.EMBED_DIM}, got {bad}")
    return vectors
