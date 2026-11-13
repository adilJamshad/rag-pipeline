"""Backend-agnostic entry point.

`LLM_BACKEND` picks the implementation; `LLM_FALLBACKS` names backends to try
in order when the first raises. Every backend talks to the same
OpenAI-compatible endpoint, so a fallback only helps when the failure is in the
client library rather than the server.
"""

import importlib
import logging
import threading

from .. import config
from .base import LLMError

log = logging.getLogger(__name__)

BACKENDS = {"direct": "._direct", "langchain": "._langchain",
            "llamaindex": "._llamaindex", "local": "._local"}

_loaded: dict[str, object] = {}
# Per-thread for the same reason as the backends: these describe one request.
_state = threading.local()


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
    errors = []
    for name in chain():
        try:
            backend = load(name)
            result = getattr(backend, method)(*args, **kwargs)
            _state.used = name
            _state.usage = getattr(backend, "last_usage", None)
            return result
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            log.warning("llm backend %s failed on %s: %s", name, method, exc)
    raise LLMError(f"all backends failed for {method}() -> " + " | ".join(errors))


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0,
             model: str | None = None) -> str:
    """Chat is stateless, so it may fall back across backends and models."""
    return _call("complete", prompt, max_tokens=max_tokens,
                 temperature=temperature, model=model)


def embed(texts: list[str]) -> list[list[float]]:
    """Embeddings never fall back.

    Vectors from a different model occupy a different space. Comparing them
    returns plausible numbers and meaningless rankings, so a second backend
    would corrupt retrieval silently. One backend, or an error.
    """
    backend = load(config.EMBED_BACKEND)
    vectors = backend.embed(texts)
    _state.used = config.EMBED_BACKEND
    return vectors


def __getattr__(name):
    """`last_used` and `last_usage` describe the calling thread's last call."""
    if name == "last_used":
        return getattr(_state, "used", None)
    if name == "last_usage":
        return getattr(_state, "usage", None)
    raise AttributeError(name)
