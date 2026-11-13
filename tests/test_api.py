import pytest
from fastapi.testclient import TestClient

from rfc_rag.clients.base import LLMError
from rfc_rag.interfaces import api, guards
from rfc_rag.models import Answer, Fact, Hit, Trace

client = TestClient(api.app, raise_server_exceptions=False)


def fake_connect(row):
    """Stand in for a psycopg connection, where both levels are context managers."""
    class Cur:
        def execute(self, *a, **k): pass
        def fetchone(self): return row
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Conn:
        def cursor(self): return Cur()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    return lambda: Conn()


def _answer() -> Answer:
    hit = Hit(1, 1035, "section-2.3.4", "2.3.4", "Size limits", "labels 63 octets", 0.81)
    other = Hit(2, 2181, "section-11", "11", "Name syntax", "names are limited", 0.70)
    trace = Trace("q")
    trace.models, trace.llm_calls = ["cheap"], 1
    fact = Fact(1035, "DNS", 1987, "INTERNET STANDARD", False, [], [2181], [(1035, "DNS")])
    return Answer("synthesis", "63 octets.", trace, hits=[hit, other], used=[hit],
                  quote="labels 63 octets", grounded=True, status=[fact])


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    monkeypatch.setattr(guards, "cached", lambda q: None)
    monkeypatch.setattr(guards, "store", lambda q, p: None)
    monkeypatch.setattr(guards, "check_rate", lambda c: None)
    monkeypatch.setattr(api, "_tag", lambda c, a: None)
    guards._minute.clear()


def test_ask_names_every_rfc_researched(monkeypatch):
    monkeypatch.setattr(api, "ask", lambda q: _answer())
    body = client.post("/ask", json={"question": "max label length?"}).json()
    assert [s["rfc"] for s in body["sources"]] == [1035, 2181]
    assert body["sources"][0]["used_in_answer"] is True
    assert body["sources"][1]["used_in_answer"] is False
    assert body["verified"] is True


def test_sources_mark_which_section_was_quoted(monkeypatch):
    monkeypatch.setattr(api, "ask", lambda q: _answer())
    body = client.post("/ask", json={"question": "max label length?"}).json()
    quoted = [s for s in body["sources"][0]["sections"] if s["quoted"]]
    assert [s["section"] for s in quoted] == ["2.3.4"]


def test_sources_carry_supersession_status(monkeypatch):
    monkeypatch.setattr(api, "ask", lambda q: _answer())
    body = client.post("/ask", json={"question": "max label length?"}).json()
    status = body["sources"][0]["status"]
    assert status["updated_by_count"] == 1
    assert "updated it" in status["warning"]


def test_provider_throttling_becomes_503_not_500(monkeypatch):
    def throttled(q):
        raise LLMError("direct: 429 Too Many Requests for https://secret.example/v1")

    monkeypatch.setattr(api, "ask", throttled)
    r = client.post("/ask", json={"question": "anything at all"})
    assert r.status_code == 503
    assert r.headers["retry-after"] == "60"
    assert "secret.example" not in r.text


def test_unhandled_errors_do_not_leak_internals(monkeypatch):
    def boom(q):
        raise RuntimeError("postgres://user:password@host/db")

    monkeypatch.setattr(api, "ask", boom)
    r = client.post("/ask", json={"question": "anything at all"})
    assert r.status_code == 500
    assert "password" not in r.text


@pytest.mark.parametrize("question,status", [
    ("hi", 400),
    ("a" * 600, 413),
    ("  ", 400),
])
def test_input_validation(question, status):
    assert client.post("/ask", json={"question": question}).status_code == status


def test_burst_limit_trips_within_the_window(monkeypatch):
    monkeypatch.setattr(guards, "PER_MINUTE", 3)
    guards._minute.clear()
    for _ in range(3):
        guards.check_burst("1.2.3.4")
    with pytest.raises(guards.Rejected) as exc:
        guards.check_burst("1.2.3.4")
    assert exc.value.status == 429
    assert 0 < exc.value.retry_after <= 61


def test_burst_limit_is_per_client(monkeypatch):
    monkeypatch.setattr(guards, "PER_MINUTE", 2)
    guards._minute.clear()
    guards.check_burst("a")
    guards.check_burst("a")
    guards.check_burst("b")          # different client, unaffected


def test_burst_window_slides(monkeypatch):
    monkeypatch.setattr(guards, "PER_MINUTE", 1)
    guards._minute.clear()
    guards.check_burst("c")
    guards._minute["c"][0] -= 61     # pretend that call was a minute ago
    guards.check_burst("c")          # allowed again


def test_quota_rejects_a_heavy_client(monkeypatch):
    monkeypatch.setattr(guards, "connect", fake_connect((guards.PER_DAY, 1)))
    with pytest.raises(guards.Rejected) as exc:
        guards.check_quota("busy")
    assert exc.value.status == 429
    assert "Daily limit" in exc.value.detail


def test_quota_rejects_when_the_shared_budget_is_gone(monkeypatch):
    monkeypatch.setattr(guards, "connect", fake_connect((0, guards.GLOBAL_PER_DAY)))
    with pytest.raises(guards.Rejected) as exc:
        guards.check_quota("anyone")
    assert exc.value.status == 503


def test_clean_question_normalises_whitespace_and_control_chars():
    assert guards.clean_question("  what\x00 is\n\n a   label?  ") == "what is a label?"


def test_rfc_endpoint_needs_no_model():
    body = client.get("/rfc/2065").json()
    assert body["obsolete"] is True
    assert 4033 in [r["rfc"] for r in body["read_instead"]]


def test_unknown_rfc_is_404():
    assert client.get("/rfc/99999").status_code == 404


def test_the_ui_is_served_at_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>RFC Chat</title>" in r.text


def test_the_ui_ships_with_the_package():
    from rfc_rag.interfaces.api import UI
    assert UI.exists(), "static/index.html missing from the package"


def test_cache_key_changes_with_the_code_version(monkeypatch):
    """A wrong answer must not outlive the fix that corrects it."""
    question = "what does the newest rfc say"
    monkeypatch.setattr(guards, "CACHE_VERSION", "1")
    old = guards.cache_key(question)
    monkeypatch.setattr(guards, "CACHE_VERSION", "2")
    assert guards.cache_key(question) != old


def test_a_cached_answer_from_an_older_version_is_not_served(monkeypatch):
    question = "a question cached by older code"
    monkeypatch.setattr(guards, "CACHE_VERSION", "1")
    guards.store(question, {"answer": "stale"})
    assert guards.cached(question)["answer"] == "stale"

    monkeypatch.setattr(guards, "CACHE_VERSION", "2")
    assert guards.cached(question) is None


def test_purge_removes_entries_from_other_versions(monkeypatch):
    monkeypatch.setattr(guards, "CACHE_VERSION", "old")
    guards.store("purge me", {"answer": "x"})
    monkeypatch.setattr(guards, "CACHE_VERSION", "new")
    guards.store("keep me", {"answer": "y"})
    guards.purge(before_version="new")
    assert guards.cached("keep me") is not None
    monkeypatch.setattr(guards, "CACHE_VERSION", "old")
    assert guards.cached("purge me") is None
