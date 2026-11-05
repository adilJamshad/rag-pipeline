import pytest

from rfc_rag import facts
from rfc_rag.answer import _context, _normalise, _parse
from rfc_rag.search import Hit


def hit(body: str, sid: int = 1) -> Hit:
    return Hit(sid, 1035, "section-1", "1", "T", body, 0.9)


def test_fact_questions_need_both_an_rfc_and_an_intent():
    assert facts.is_fact_question("Is RFC 2065 still current?")
    assert facts.is_fact_question("What replaced RFC 2845?")
    assert not facts.is_fact_question("What is a CNAME record for?")
    assert not facts.is_fact_question("Is this still current?")
    assert not facts.is_fact_question("Tell me about RFC 1035")


def test_rfc_reference_parsing():
    assert facts.referenced("what replaced rfc-2845?") == 2845
    assert facts.referenced("RFC 1035 section 2") == 1035
    assert facts.referenced("no reference here") is None


def test_normalise_ignores_whitespace_and_edge_punctuation():
    assert _normalise("The  NSEC\n   record") == _normalise("the nsec record")
    assert _normalise("owner name.") == _normalise("  owner name  ")
    assert _normalise('"quoted",') == _normalise("quoted")


def test_normalise_keeps_internal_punctuation():
    assert _normalise("a, b") != _normalise("a b")


def test_parse_extracts_json_from_surrounding_text():
    assert _parse('chatter {"answer": "x", "used": [1]} more')["answer"] == "x"
    assert _parse("no json here") is None
    assert _parse("{broken") is None


def test_context_respects_the_token_budget():
    big = "word " * 8000
    text, kept = _context([hit(big, 1), hit(big, 2), hit(big, 3)])
    assert len(kept) == 1
    assert text.startswith("[1] ")


def test_context_always_keeps_at_least_one_section():
    huge = "word " * 50000
    _, kept = _context([hit(huge)])
    assert len(kept) == 1
