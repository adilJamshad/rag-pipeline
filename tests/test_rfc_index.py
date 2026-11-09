from pathlib import Path

import pytest

from rfc_rag.models import Rfc

from rfc_rag.ingest import rfc_index as index

INDEX = Path("data/rfc-index.xml")
needs_index = pytest.mark.skipif(not INDEX.exists(), reason="run `uv run python -m rfc_rag.ingest` first")


def rfc(n, title="Something", obsoletes=(), updates=(), keywords=(), wg=None):
    return Rfc(n, title, 2000, "PROPOSED STANDARD", "IETF", 10, None,
                     keywords=list(keywords), abstract="", wg=wg,
                     obsoletes=list(obsoletes), updates=list(updates))


def _fake() -> dict[int, index.Rfc]:
    return {1: rfc(1), 2: rfc(2, obsoletes=[1]), 3: rfc(3, updates=[1]),
            4: rfc(4, obsoletes=[2]), 9: rfc(9)}


def test_slice_follows_inbound_links():
    got = index.slice_for(_fake(), [1])
    assert got == {1, 2, 3, 4}
    assert 9 not in got


def test_slice_stops_when_nothing_new():
    assert index.slice_for(_fake(), [9]) == {9}


def test_closure_adds_neighbours_only_once():
    assert index.closure(_fake(), {2}) == {1, 2, 4}


def test_topic_selection_uses_working_group():
    assert index.is_dns(rfc(1, title="Opaque Title", wg="dnsop"))
    assert not index.is_dns(rfc(1, title="Opaque Title", wg="httpbis"))


def test_topic_selection_uses_keywords():
    assert index.is_dns(rfc(1, title="Opaque Title", keywords=["DoH", "HTTP"]))
    assert not index.is_dns(rfc(1, title="Opaque Title", keywords=["HTTP", "TCP"]))


def test_topic_selection_matches_plural_titles():
    assert index.is_dns(rfc(1034, title="Domain names - concepts and facilities"))
    assert index.is_dns(rfc(1, title="Name servers and resolvers"))


def test_topic_selection_skips_joke_rfcs():
    assert not index.is_dns(rfc(1, title="The DNS protocol, an April Fool proposal"))


@needs_index
def test_real_index_parses_and_links_dns():
    rfcs = index.parse(INDEX)
    assert len(rfcs) > 9000
    assert rfcs[1035].title.startswith("Domain names")
    assert 1035 in rfcs[2181].updates
    assert 2535 in rfcs[4034].obsoletes
    assert "DoH" in rfcs[8484].keywords


@needs_index
def test_topic_corpus_includes_modern_dns_rfcs():
    corpus = index.by_topic(index.parse(INDEX))
    for number in (1034, 1035, 5155, 6698, 6762, 6763, 7858, 7871, 8484, 8914, 9250, 9460):
        assert number in corpus, f"RFC {number} missing from the topic corpus"
    assert 9110 not in corpus
