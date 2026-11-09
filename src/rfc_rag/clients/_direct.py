import json

import httpx

from .. import config
from .base import LLMError

name = "direct"

last_usage: dict | None = None


def _headers() -> dict[str, str]:
    key = config.api_key()
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


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0) -> str:
    body = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning_effort": "low",
    }
    r = httpx.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        json=body,
        headers=_headers(),
        timeout=600,
    )
    if "text/event-stream" in r.headers.get("content-type", ""):
        return _parse_sse(r.text).strip()

    r.raise_for_status()
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
    r = httpx.post(
        f"{config.LLM_BASE_URL}/embeddings",
        json={"model": config.EMBED_MODEL, "input": texts},
        headers=_headers(),
        timeout=300,
    )
    r.raise_for_status()
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
