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


def test_prune_removes_only_rows_outside_the_window():
    from rfc_rag.db import connect

    observability.record(_answer())
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from query_log")
        before = cur.fetchone()[0]

    assert observability.prune(days=3650)["query_log"] == 0

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from query_log")
        assert cur.fetchone()[0] == before


def test_prune_reports_every_table_it_touches():
    removed = observability.prune(days=3650)
    assert set(removed) == {"query_log", "chat", "answer_cache"}
    assert all(isinstance(v, int) for v in removed.values())


def test_messages_cascade_when_a_chat_is_pruned():
    from rfc_rag.db import connect
    from rfc_rag.services import chat as chat_service

    c = chat_service.create(budget=1000)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""insert into message (chat_id, position, role, content)
                       values (%s, 0, 'user', 'x')""", (str(c.id),))
        cur.execute("update chat set updated_at = now() - interval '400 days' where id = %s",
                    (str(c.id),))
        conn.commit()

    observability.prune(days=90)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) from message where chat_id = %s", (str(c.id),))
        assert cur.fetchone()[0] == 0
