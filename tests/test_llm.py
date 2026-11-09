import pytest

from rfc_rag.clients import llm
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
    assert llm._parse_sse(raw) == "Hello"


def test_parse_sse_raises_on_error_event():
    raw = 'data: {"error":{"message":"context exceeded"}}\n'
    with pytest.raises(llm.LLMError, match="context exceeded"):
        llm._parse_sse(raw)


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
