import pytest

from rfc_rag.clients import _direct, llm
from rfc_rag.config import EMBED_DIM


def _live() -> bool:
    try:
        llm.embed(["ping"])
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="local model server not running")


def test_parse_sse_concatenates_deltas():
    raw = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n'
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n'
        "data: [DONE]\n"
    )
    assert _direct._parse_sse(raw) == "Hello"


def test_parse_sse_raises_on_error_event():
    raw = 'data: {"error":{"message":"context exceeded"}}\n'
    with pytest.raises(llm.LLMError, match="context exceeded"):
        _direct._parse_sse(raw)


@live
def test_embed_returns_expected_dimension():
    vectors = llm.embed(["dns resource record", "ttl"])
    assert len(vectors) == 2
    assert all(len(v) == EMBED_DIM for v in vectors)


@live
def test_complete_answers_from_given_text():
    answer = llm.complete(
        "Using only this text, how many octets may a label be? Answer with the number only.\n\n"
        "labels          63 octets or less"
    )
    assert "63" in answer


def test_unknown_backend_is_rejected():
    with pytest.raises(llm.LLMError, match="unknown backend"):
        llm.load("nope")


def test_chain_is_backend_then_fallbacks(monkeypatch):
    from rfc_rag import config
    monkeypatch.setattr(config, "LLM_BACKEND", "direct")
    monkeypatch.setattr(config, "LLM_FALLBACKS", ["langchain", "llamaindex"])
    assert llm.chain() == ["direct", "langchain", "llamaindex"]


def test_fallback_runs_the_next_backend(monkeypatch):
    from rfc_rag import config

    class Broken:
        name = "broken"
        def complete(self, prompt, **kw):
            raise RuntimeError("outage")

    class Works:
        name = "works"
        def complete(self, prompt, **kw):
            return "fallback answer"

    monkeypatch.setattr(config, "LLM_BACKEND", "a")
    monkeypatch.setattr(config, "LLM_FALLBACKS", ["b"])
    monkeypatch.setitem(llm.BACKENDS, "a", "x")
    monkeypatch.setitem(llm.BACKENDS, "b", "y")
    monkeypatch.setitem(llm._loaded, "a", Broken())
    monkeypatch.setitem(llm._loaded, "b", Works())
    assert llm.complete("q") == "fallback answer"
    assert llm.last_used == "b"


def test_all_backends_failing_raises_with_every_reason(monkeypatch):
    from rfc_rag import config

    class Broken:
        def complete(self, prompt, **kw):
            raise RuntimeError("outage")

    monkeypatch.setattr(config, "LLM_BACKEND", "a")
    monkeypatch.setattr(config, "LLM_FALLBACKS", [])
    monkeypatch.setitem(llm.BACKENDS, "a", "x")
    monkeypatch.setitem(llm._loaded, "a", Broken())
    with pytest.raises(llm.LLMError, match="all backends failed"):
        llm.complete("q")
