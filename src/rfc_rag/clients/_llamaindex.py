"""LlamaIndex backend. Requires the `frameworks` dependency group."""

from .. import config
from .base import LLMError

name = "llamaindex"

_llm = None
_embeddings = None


def _models():
    global _llm, _embeddings
    if _llm is None:
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms.openai_like import OpenAILike

        key = config.api_key() or "unused"
        _llm = OpenAILike(model=config.LLM_MODEL, api_base=config.LLM_BASE_URL,
                          api_key=key, is_chat_model=True, temperature=0,
                          additional_kwargs={"reasoning_effort": "low"})
        _embeddings = OpenAIEmbedding(model_name=config.EMBED_MODEL,
                                      api_base=config.LLM_BASE_URL, api_key=key)
    return _llm, _embeddings


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0) -> str:
    llm, _ = _models()
    text = str(llm.complete(prompt, max_tokens=max_tokens)).strip()
    if not text:
        raise LLMError("empty content: reasoning consumed the max_tokens budget")
    return text


def embed(texts: list[str]) -> list[list[float]]:
    _, embeddings = _models()
    vectors = embeddings.get_text_embedding_batch(texts)
    bad = {len(v) for v in vectors} - {config.EMBED_DIM}
    if bad:
        raise LLMError(f"expected dim {config.EMBED_DIM}, got {bad}")
    return vectors
