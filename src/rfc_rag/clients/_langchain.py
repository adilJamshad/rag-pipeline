"""LangChain backend. Requires the `frameworks` dependency group."""

from .. import config
from .base import LLMError

name = "langchain"

_chat = None
_embeddings = None


def _models():
    global _chat, _embeddings
    if _chat is None:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        key = config.api_key() or "unused"
        _chat = ChatOpenAI(model=config.LLM_MODEL, base_url=config.LLM_BASE_URL,
                           api_key=key, temperature=0)
        _embeddings = OpenAIEmbeddings(model=config.EMBED_MODEL,
                                       base_url=config.LLM_BASE_URL, api_key=key,
                                       check_embedding_ctx_length=False)
    return _chat, _embeddings


def complete(prompt: str, *, max_tokens: int = 800, temperature: float = 0.0,
             model: str | None = None) -> str:
    chat, _ = _models()
    message = chat.invoke(
        prompt,
        model=model or config.LLM_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body={"reasoning_effort": "low"},
    )
    text = (message.content or "").strip()
    if not text:
        raise LLMError("empty content: reasoning consumed the max_tokens budget")
    return text


def embed(texts: list[str]) -> list[list[float]]:
    _, embeddings = _models()
    vectors = embeddings.embed_documents(texts)
    bad = {len(v) for v in vectors} - {config.EMBED_DIM}
    if bad:
        raise LLMError(f"expected dim {config.EMBED_DIM}, got {bad}")
    return vectors
