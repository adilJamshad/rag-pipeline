"""Backend-agnostic entry point.

`LLM_BACKEND` picks the implementation; `LLM_FALLBACKS` names backends to try
in order when the first raises. Every backend talks to the same
OpenAI-compatible endpoint, so a fallback only helps when the failure is in the
client library rather than the server.
"""

import importlib
import logging

from .. import config
from .base import LLMError

log = logging.getLogger(__name__)

BACKENDS = {"direct": "._direct", "langchain": "._langchain", "llamaindex": "._llamaindex"}

_loaded: dict[str, object] = {}
last_used: str | None = None
last_usage: dict | None = None


def load(name: str):
    if name not in BACKENDS:
        raise LLMError(f"unknown backend {name!r}, expected one of {sorted(BACKENDS)}")
    if name not in _loaded:
        try:
            _loaded[name] = importlib.import_module(BACKENDS[name], __package__)
        except ImportError as exc:
            raise LLMError(f"backend {name!r} is not installed: {exc}") from exc
    return _loaded[name]


def chain() -> list[str]:
    return [config.LLM_BACKEND, *config.LLM_FALLBACKS]


def _call(method: str, *args, **kwargs):
    global last_used, last_usage
    errors = []
    for name in chain():
        try:
            backend = load(name)
            result = getattr(backend, method)(*args, **kwargs)
            last_used = name
            globals()["last_usage"] = getattr(backend, "last_usage", None)
            return result
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            log.warning("llm backend %s failed on %s: %s", name, method, exc)
    raise LLMError(f"all backends failed for {method}() -> " + " | ".join(errors))


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0) -> str:
    return _call("complete", prompt, max_tokens=max_tokens, temperature=temperature)


def embed(texts: list[str]) -> list[list[float]]:
    return _call("embed", texts)
