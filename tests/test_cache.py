"""The answer cache, with no stubs — test_api.py autouse-patches it away."""

from rfc_rag.interfaces import guards


def test_cache_key_changes_with_the_code_version(monkeypatch):
    """A wrong answer must not outlive the fix that corrects it."""
    question = "what does the newest rfc say"
    monkeypatch.setattr(guards, "CACHE_VERSION", "1")
    old = guards.cache_key(question)
    monkeypatch.setattr(guards, "CACHE_VERSION", "2")
    assert guards.cache_key(question) != old


def test_an_answer_cached_by_older_code_is_not_served(monkeypatch):
    question = "a question cached by older code"
    monkeypatch.setattr(guards, "CACHE_VERSION", "v-old")
    guards.store(question, {"answer": "stale"})
    assert guards.cached(question)["answer"] == "stale"

    monkeypatch.setattr(guards, "CACHE_VERSION", "v-new")
    assert guards.cached(question) is None


def test_purge_removes_only_other_versions(monkeypatch):
    monkeypatch.setattr(guards, "CACHE_VERSION", "v-old")
    guards.store("purge me", {"answer": "x"})
    monkeypatch.setattr(guards, "CACHE_VERSION", "v-new")
    guards.store("keep me", {"answer": "y"})

    guards.purge(before_version="v-new")

    assert guards.cached("keep me")["answer"] == "y"
    monkeypatch.setattr(guards, "CACHE_VERSION", "v-old")
    assert guards.cached("purge me") is None


def test_a_cache_hit_increments_its_counter(monkeypatch):
    from rfc_rag.db import connect

    monkeypatch.setattr(guards, "CACHE_VERSION", "v-hits")
    guards.store("counted question", {"answer": "z"})
    for _ in range(3):
        guards.cached("counted question")
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select hits from answer_cache where key = %s",
                    (guards.cache_key("counted question"),))
        assert cur.fetchone()[0] == 3
