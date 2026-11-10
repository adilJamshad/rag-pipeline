import pytest

from rfc_rag import config, corpus


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


def test_stamp_then_recorded_round_trips():
    corpus.stamp()
    assert corpus.recorded() == (config.EMBED_MODEL, config.EMBED_DIM)
