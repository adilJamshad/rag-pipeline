import pytest

from rfc_rag import config
from rfc_rag.models import Hit, Trace
from rfc_rag.services import answering


def hit(body: str = "labels 63 octets or less") -> Hit:
    return Hit(1, 1035, "section-2.3.4", "2.3.4", "Size limits", body, 0.9)


def _replies(*texts):
    seq = list(texts)
    def fake(prompt, *, max_tokens=900, model=None, temperature=0.0):
        return seq.pop(0)
    return fake


GOOD = '{"answer": "63 octets.", "used": [1], "quote": "labels 63 octets or less"}'
UNGROUNDED = '{"answer": "64 octets.", "used": [1], "quote": "labels 64 octets or less"}'
JUNK = "I am not JSON at all"


def test_no_escalation_when_the_cheap_model_is_grounded(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL_HEAVY", "big")
    monkeypatch.setattr(answering.llm, "complete", _replies(GOOD))
    raw, parsed, grounded, used, quote = answering._generate(
        "p", [hit()], Trace("q"), "small")
    assert grounded and parsed


def test_generate_reports_ungrounded_quotes():
    trace = Trace("q")
    import rfc_rag.services.answering as a
    a.llm.complete = _replies(UNGROUNDED)
    raw, parsed, grounded, used, quote = a._generate("p", [hit()], trace, "small")
    assert parsed and not grounded
    assert trace.models == ["small"]


def test_generate_handles_unparseable_output():
    import rfc_rag.services.answering as a
    a.llm.complete = _replies(JUNK)
    raw, parsed, grounded, used, quote = a._generate("p", [hit()], Trace("q"), "small")
    assert parsed is None and not grounded


def test_trace_records_every_model_used():
    import rfc_rag.services.answering as a
    trace = Trace("q")
    a.llm.complete = _replies(JUNK, GOOD)
    a._generate("p", [hit()], trace, "small")
    a._generate("p", [hit()], trace, "big")
    assert trace.models == ["small", "big"]
    assert trace.llm_calls == 2
