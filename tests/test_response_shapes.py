"""The model mostly returns {answer, used, quote}. Mostly is not always.

A wrong type used to reach code that indexed it or called .strip() on it, and
the caller got a 500. A malformed answer is a refusal.
"""

import pytest

from rfc_rag.models import Hit, Trace
from rfc_rag.services import answering, stages


def hit() -> Hit:
    return Hit(1, 1035, "section-1", "1", "T", "body text", 0.9)


@pytest.mark.parametrize("raw", [
    '{"answer":"x","used":"1","quote":"q"}',
    '{"answer":"x","used":["a",2],"quote":"q"}',
    '{"answer":"x","used":[1],"quote":99}',
    '{"answer":"x","used":[true,2],"quote":"q"}',
    '{"answer":"x","used":null,"quote":null}',
    '{"answer":"x"}',
])
def test_recoverable_shapes_still_answer(raw, monkeypatch):
    monkeypatch.setattr(answering.llm, "complete", lambda *a, **k: raw)
    _, parsed, _, used, quote = answering._generate("p", [hit()], Trace("q"), "m")
    assert parsed is not None
    assert isinstance(parsed["used"], list)
    assert all(isinstance(i, int) for i in parsed["used"])
    assert isinstance(quote, str)
    assert used


@pytest.mark.parametrize("raw", [
    '{"answer":42,"used":[1],"quote":"q"}',
    '{"answer":{"a":1},"used":[1],"quote":"q"}',
    '{"answer":"   ","used":[1],"quote":"q"}',
    '{"answer":null}',
    '{}',
    'not json at all',
    '{"answer":"x","used":[1]',
])
def test_unusable_shapes_become_a_refusal_not_a_crash(raw, monkeypatch):
    monkeypatch.setattr(answering.llm, "complete", lambda *a, **k: raw)
    _, parsed, grounded, _, _ = answering._generate("p", [hit()], Trace("q"), "m")
    assert parsed is None
    assert grounded is False


def test_booleans_are_not_accepted_as_indexes():
    """True == 1 in Python, so a bool would silently select section 1."""
    cleaned = stages.clean_response({"answer": "x", "used": [True, 2], "quote": "q"})
    assert cleaned["used"] == [2]


def test_out_of_range_indexes_are_dropped_by_the_caller(monkeypatch):
    monkeypatch.setattr(answering.llm, "complete",
                        lambda *a, **k: '{"answer":"x","used":[1,99,-5],"quote":"body text"}')
    _, _, _, used, _ = answering._generate("p", [hit()], Trace("q"), "m")
    assert len(used) == 1


def test_clean_response_rejects_non_dicts():
    for value in (None, [], "string", 42):
        assert stages.clean_response(value) is None
