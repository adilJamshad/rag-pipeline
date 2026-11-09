import pytest

from rfc_rag.models import Fact, Hit, Trace
from rfc_rag.services import answering, stages, supersession
from rfc_rag.services.stages import analyse, compose, normalise, plan, verify


def hit(body: str = "labels 63 octets or less", sid: int = 1, rfc: int = 1035) -> Hit:
    return Hit(sid, rfc, "section-2.3.4", "2.3.4", "Size limits", body, 0.9)


def test_analyse_extracts_references_and_intent():
    a = analyse("Is RFC 2065 still current?")
    assert a.rfc_refs == [2065]
    assert a.intent == "current"
    assert a.section_ref is None


def test_analyse_finds_section_references():
    assert analyse("RFC 1035 section 2.3.4").section_ref == "2.3.4"
    assert analyse("what does §4.1 say").section_ref == "4.1"


@pytest.mark.parametrize("question,route", [
    ("Is RFC 2065 still current?", "facts"),
    ("What replaced RFC 2845?", "facts"),
    ("What is the current DNS specification?", "topic_facts"),
    ("What does RFC 2181 say about TTL?", "passage"),
    ("What is a CNAME record?", "synthesis"),
])
def test_routing_decisions(question, route):
    assert plan(analyse(question)) == route


def test_compose_respects_the_budget_and_records_it():
    trace = Trace("q")
    big = "word " * 8000
    text, kept = compose([hit(big, 1), hit(big, 2)], trace)
    assert len(kept) == 1
    assert text.startswith("[1] ")
    assert trace.context_tokens > 0


def test_compose_always_keeps_one_section():
    _, kept = compose([hit("word " * 50000)], Trace("q"))
    assert len(kept) == 1


def test_verify_ignores_whitespace_and_edge_punctuation():
    assert verify("labels   63 octets or less.", [hit()])
    assert verify('"labels 63 octets or less",', [hit()])
    assert not verify("labels 64 octets or less", [hit()])
    assert not verify("", [hit()])


def test_normalise_keeps_internal_punctuation():
    assert normalise("a, b") != normalise("a b")


def test_parse_extracts_json_from_noise():
    assert stages.parse_response('x {"answer": "y"} z')["answer"] == "y"
    assert stages.parse_response("no json") is None
    assert stages.parse_response("{broken") is None


def test_trace_totals_its_steps():
    t = Trace("q")
    t.timings = {"a": 0.5, "b": 0.25}
    assert t.total == 0.75


def test_statuses_only_reports_documents_worth_warning_about(monkeypatch):
    clean = Fact(9999, "T", 2024, "PROPOSED STANDARD", False, [], [], [(9999, "T")])
    dirty = Fact(1035, "T", 1987, "INTERNET STANDARD", False, [], [2181], [(1035, "T")])
    monkeypatch.setattr(supersession, "lookup", lambda n: dirty if n == 1035 else clean)
    out = answering.statuses([hit(rfc=1035), hit(rfc=9999)])
    assert [f.rfc for f in out] == [1035]
