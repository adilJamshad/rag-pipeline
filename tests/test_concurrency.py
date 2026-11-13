"""Regressions for bugs that only appear when requests overlap.

FastAPI runs sync endpoints in a threadpool, so module-level state and
read-then-write sequences are shared between in-flight requests.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from rfc_rag import corpus, observability
from rfc_rag.clients import _direct, llm
from rfc_rag.db import connect
from rfc_rag.interfaces import api, guards
from rfc_rag.models import Answer, Trace
from rfc_rag.services import chat


def _answer(text: str) -> Answer:
    trace = Trace(text)
    trace.route = "facts"
    return Answer("facts", text, trace)


def test_concurrent_sends_to_one_chat_do_not_collide(monkeypatch):
    monkeypatch.setattr(chat, "ask", lambda q: _answer("ok"))
    monkeypatch.setattr(chat.llm, "last_usage", {"prompt_tokens": 1, "completion_tokens": 1})
    c = chat.create(budget=1_000_000)
    errors = []

    def send(i):
        try:
            chat.send(str(c.id), f"question {i}", lambda a: [])
        except Exception as exc:
            errors.append(type(exc).__name__)

    with ThreadPoolExecutor(6) as pool:
        list(pool.map(send, range(6)))

    assert errors == []
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*), count(distinct position) from message where chat_id = %s",
                    (str(c.id),))
        total, distinct = cur.fetchone()
    assert total == distinct == 12


def test_token_usage_does_not_leak_between_threads():
    seen = []

    def worker(tag):
        _direct._set_last_usage({"prompt_tokens": tag})
        time.sleep(0.01)
        seen.append((tag, _direct.last_usage["prompt_tokens"]))

    with ThreadPoolExecutor(6) as pool:
        list(pool.map(worker, range(6)))
    assert all(sent == read for sent, read in seen)


def test_last_used_is_per_thread():
    results = {}

    def worker(name):
        llm._state.used = name
        time.sleep(0.01)
        results[name] = llm.last_used

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(worker, ["a", "b", "c", "d"]))
    assert results == {"a": "a", "b": "b", "c": "c", "d": "d"}


def test_each_request_tags_its_own_log_row():
    first, second = _answer("first question"), _answer("second question")
    observability.record(first)
    observability.record(second)
    api._tag("client-one", first)
    api._tag("client-two", second)

    with connect() as conn, conn.cursor() as cur:
        cur.execute("select id, client from query_log where id = any(%s)",
                    ([first.trace.log_id, second.trace.log_id],))
        got = dict(cur.fetchall())
    assert got[first.trace.log_id] == "client-one"
    assert got[second.trace.log_id] == "client-two"


def test_tagging_without_a_log_row_is_a_no_op():
    api._tag("nobody", _answer("never recorded"))


def test_rate_limit_windows_are_evicted():
    guards._minute.clear()
    guards._last_sweep = 0.0
    for i in range(500):
        guards.check_burst(f"10.0.{i // 256}.{i % 256}")
    assert len(guards._minute) == 500

    for window in guards._minute.values():
        if window:
            window[-1] -= 120
    guards._last_sweep = 0.0
    guards.check_burst("fresh")
    assert len(guards._minute) == 1


def test_sweeping_keeps_active_windows():
    guards._minute.clear()
    guards._last_sweep = 0.0
    guards.check_burst("active")
    guards._last_sweep = 0.0
    guards.check_burst("active")
    assert "active" in guards._minute


def test_stamp_check_is_cached_and_invalidated():
    corpus.reset_cache()
    corpus.check()
    calls = {"n": 0}
    real = corpus.recorded

    def counting():
        calls["n"] += 1
        return real()

    corpus.recorded = counting
    try:
        for _ in range(50):
            corpus.check()
        assert calls["n"] == 0, "cached check still queried the database"
        corpus.reset_cache()
        corpus.check()
        assert calls["n"] == 1, "reset_cache did not force a re-read"
    finally:
        corpus.recorded = real
        corpus.reset_cache()
