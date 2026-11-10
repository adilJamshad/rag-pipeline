"""Local embeddings via fastembed (ONNX, CPU, no server).

Embeddings are a coordinate system the corpus depends on, so running them
in-process removes the two failure modes a hosted embedder has: a rate limit
that stalls ingestion, and an outage that makes every query fail.

Chat is not implemented here — it is stateless and belongs on a hosted model.
"""

import threading

from .. import config
from .base import LLMError

name = "local"

_model = None
_lock = threading.Lock()

MODELS = {
    "bge-small-en-v1.5": "BAAI/bge-small-en-v1.5",
    "BAAI/bge-small-en-v1.5": "BAAI/bge-small-en-v1.5",
}


def _load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    from fastembed import TextEmbedding
                except ImportError as exc:
                    raise LLMError(f"fastembed is not installed: {exc}") from exc
                repo = MODELS.get(config.EMBED_MODEL, config.EMBED_MODEL)
                _model = TextEmbedding(repo)
    return _model


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0,
             model: str | None = None) -> str:
    raise LLMError("the local backend provides embeddings only; set LLM_BACKEND "
                   "to a chat-capable backend")


def embed(texts: list[str]) -> list[list[float]]:
    vectors = [v.tolist() for v in _load().embed(texts)]
    bad = {len(v) for v in vectors} - {config.EMBED_DIM}
    if bad:
        raise LLMError(f"expected dim {config.EMBED_DIM}, got {bad}")
    return vectors
