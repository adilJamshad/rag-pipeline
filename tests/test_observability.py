import pytest

from rfc_rag import observability
from rfc_rag.models import Answer, Hit, Trace


def _answer(route: str = "synthesis", grounded: bool = True) -> Answer:
    trace = Trace("what is a label?")
    trace.route = route
    trace.timings = {"analyse": 0.001, "gather": 0.04, "generate": 2.5}
    trace.llm_calls = 1
    trace.context_tokens = 900
    trace.retrieved = ["1035/section-2.3.4"]
    hit = Hit(1, 1035, "section-2.3.4", "2.3.4", "Size limits", "labels 63 octets", 0.8)
    return Answer(route, "63 octets.", trace, hits=[hit], used=[hit],
                  quote="labels 63 octets", grounded=grounded)


def test_record_writes_a_row_and_returns_its_id():
    row_id = observability.record(_answer())
    assert isinstance(row_id, int)


def test_record_is_disabled_by_the_env_flag(monkeypatch):
    monkeypatch.setattr(observability, "ENABLED", False)
    assert observability.record(_answer()) is None


def test_record_never_raises_when_the_database_is_unreachable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(observability, "connect", boom)
    assert observability.record(_answer()) is None


def test_record_marks_refusals_as_unanswered():
    observability.record(_answer(route="refusal"))
    r = observability.report(days=1)
    assert r["refused"] >= 1


def test_report_has_the_expected_shape():
    observability.record(_answer())
    r = observability.report(days=1)
    for key in ("total", "answered", "refused", "ungrounded", "llm_calls",
                "prompt_tokens", "completion_tokens", "routes", "attention"):
        assert key in r
    assert r["total"] >= 1
    assert all({"route", "n", "p50_ms", "p95_ms", "llm_calls"} <= set(x) for x in r["routes"])


def test_ungrounded_answers_surface_in_attention():
    observability.record(_answer(grounded=False))
    assert any(a["grounded"] is False for a in observability.report(days=1)["attention"])
