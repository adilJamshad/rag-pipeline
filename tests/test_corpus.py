import pytest

from rfc_rag import config, corpus
from rfc_rag.db import connect


@pytest.fixture
def preserve_stamp():
    """corpus_meta is single-row state the running system depends on.

    A test that writes it must put it back, or it silently tells the next
    query that the stored vectors came from a model that did not make them.
    """
    before = corpus.recorded()
    yield
    with connect() as conn, conn.cursor() as cur:
        if before is None:
            cur.execute("delete from corpus_meta where id = 1")
        else:
            cur.execute("""insert into corpus_meta (id, embed_model, embed_dim)
                           values (1, %s, %s)
                           on conflict (id) do update set
                             embed_model = excluded.embed_model,
                             embed_dim = excluded.embed_dim""", before)
        conn.commit()


def test_check_passes_when_the_stamp_matches(monkeypatch):
    monkeypatch.setattr(corpus, "recorded", lambda: (config.EMBED_MODEL, config.EMBED_DIM))
    corpus.check()


def test_check_rejects_a_different_model(monkeypatch):
    monkeypatch.setattr(corpus, "recorded", lambda: ("bge-small-en-v1.5-bf16", 384))
    monkeypatch.setattr(config, "EMBED_MODEL", "gemini-embedding-001")
    monkeypatch.setattr(config, "EMBED_DIM", 384)
    with pytest.raises(corpus.EmbeddingMismatch, match="not comparable"):
        corpus.check()


def test_check_rejects_a_different_dimension(monkeypatch):
    monkeypatch.setattr(corpus, "recorded", lambda: ("gemini-embedding-001", 768))
    monkeypatch.setattr(config, "EMBED_MODEL", "gemini-embedding-001")
    monkeypatch.setattr(config, "EMBED_DIM", 384)
    with pytest.raises(corpus.EmbeddingMismatch):
        corpus.check()


def test_check_warns_but_allows_an_unstamped_corpus(monkeypatch):
    monkeypatch.setattr(corpus, "recorded", lambda: None)
    corpus.check()


def test_stamp_then_recorded_round_trips(preserve_stamp):
    corpus.stamp()
    assert corpus.recorded() == (config.EMBED_MODEL, config.EMBED_DIM)
