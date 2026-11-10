import pytest

from rfc_rag.clients import _direct, llm
from rfc_rag.config import EMBED_DIM


def _live() -> bool:
    try:
        llm.embed(["ping"])
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _live(), reason="model server unreachable or rate limited")


def skip_if_throttled(exc: Exception) -> None:
    """A provider quota is not a test failure."""
    if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
        pytest.skip(f"provider rate limited: {str(exc)[:60]}")
    raise exc


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
    try:
        vectors = llm.embed(["dns resource record", "ttl"])
    except Exception as exc:
        skip_if_throttled(exc)
    assert len(vectors) == 2
    assert all(len(v) == EMBED_DIM for v in vectors)


@live
def test_complete_answers_from_given_text():
    try:
        answer = llm.complete(
            "Using only this text, how many octets may a label be? "
            "Answer with the number only.\n\nlabels          63 octets or less"
        )
    except Exception as exc:
        skip_if_throttled(exc)
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


def test_direct_retries_then_succeeds(monkeypatch):
    from rfc_rag.clients import _direct

    calls = {"n": 0}

    class Resp:
        def __init__(self, code):
            self.status_code, self.headers = code, {}

    def flaky(url, **kw):
        calls["n"] += 1
        return Resp(429) if calls["n"] < 3 else Resp(200)

    monkeypatch.setattr(_direct.httpx, "post", flaky)
    monkeypatch.setattr(_direct.time, "sleep", lambda s: None)
    assert _direct._post("/x", {}, timeout=1).status_code == 200
    assert calls["n"] == 3


def test_direct_gives_up_after_max_attempts(monkeypatch):
    from rfc_rag.clients import _direct

    def always_timeout(url, **kw):
        raise _direct.httpx.TimeoutException("slow")

    monkeypatch.setattr(_direct.httpx, "post", always_timeout)
    monkeypatch.setattr(_direct.time, "sleep", lambda s: None)
    with pytest.raises(llm.LLMError, match="failed after 5 attempts"):
        _direct._post("/x", {}, timeout=1)


def test_direct_honours_retry_after_header(monkeypatch):
    from rfc_rag.clients import _direct

    waited = []

    class Resp:
        def __init__(self, code, headers):
            self.status_code, self.headers = code, headers

    seq = [Resp(429, {"retry-after": "7"}), Resp(200, {})]
    monkeypatch.setattr(_direct.httpx, "post", lambda url, **kw: seq.pop(0))
    monkeypatch.setattr(_direct.time, "sleep", waited.append)
    _direct._post("/x", {}, timeout=1)
    assert waited == [7.0]


def test_embed_never_falls_back(monkeypatch):
    """A second backend would produce vectors in a different space."""
    from rfc_rag import config

    class Broken:
        def embed(self, texts):
            raise RuntimeError("outage")

    class Works:
        def embed(self, texts):
            return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr(config, "EMBED_BACKEND", "a")
    monkeypatch.setattr(config, "LLM_BACKEND", "a")
    monkeypatch.setattr(config, "LLM_FALLBACKS", ["b"])
    monkeypatch.setitem(llm.BACKENDS, "a", "x")
    monkeypatch.setitem(llm.BACKENDS, "b", "y")
    monkeypatch.setitem(llm._loaded, "a", Broken())
    monkeypatch.setitem(llm._loaded, "b", Works())
    with pytest.raises(RuntimeError, match="outage"):
        llm.embed(["anything"])


def test_http_errors_become_llm_errors_without_leaking_the_url():
    from rfc_rag.clients import _direct

    class Resp:
        is_success, status_code = False, 429
        text = "nope"
        def json(self):
            return [{"error": {"message": "Quota exceeded for generativelanguage.googleapis.com"}}]

    with pytest.raises(llm.LLMError) as exc:
        _direct._raise_for_status(Resp(), "/embeddings")
    assert "429" in str(exc.value)
    assert "Quota exceeded" in str(exc.value)


def test_successful_responses_pass_through():
    from rfc_rag.clients import _direct

    class Resp:
        is_success = True

    _direct._raise_for_status(Resp(), "/embeddings")


def test_embeddings_may_use_a_different_backend_from_chat(monkeypatch):
    from rfc_rag import config

    class Chat:
        def complete(self, prompt, **kw): return "from chat backend"

    class Embed:
        def embed(self, texts): return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr(config, "LLM_BACKEND", "chat")
    monkeypatch.setattr(config, "EMBED_BACKEND", "embed")
    monkeypatch.setattr(config, "LLM_FALLBACKS", [])
    monkeypatch.setitem(llm.BACKENDS, "chat", "x")
    monkeypatch.setitem(llm.BACKENDS, "embed", "y")
    monkeypatch.setitem(llm._loaded, "chat", Chat())
    monkeypatch.setitem(llm._loaded, "embed", Embed())
    assert llm.complete("q") == "from chat backend"
    assert len(llm.embed(["q"])[0]) == 384
    assert llm.last_used == "embed"
