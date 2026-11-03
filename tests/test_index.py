from pathlib import Path

import pytest

from rfc_rag import index

INDEX = Path("data/rfc-index.xml")
needs_index = pytest.mark.skipif(not INDEX.exists(), reason="run `uv run python -m rfc_rag.ingest` first")


def _fake() -> dict[int, index.Rfc]:
    def r(n, obs=(), upd=()):
        return index.Rfc(n, f"RFC {n}", 2000, "PROPOSED STANDARD", "IETF", 10, None,
                         list(obs), list(upd))
    return {1: r(1), 2: r(2, obs=[1]), 3: r(3, upd=[1]), 4: r(4, obs=[2]), 9: r(9)}


def test_slice_follows_inbound_links():
    got = index.slice_for(_fake(), [1])
    assert got == {1, 2, 3, 4}
    assert 9 not in got


def test_slice_stops_when_nothing_new():
    assert index.slice_for(_fake(), [9]) == {9}


def test_closure_adds_neighbours_only_once():
    assert index.closure(_fake(), {2}) == {1, 2, 4}


@needs_index
def test_real_index_parses_and_links_dns():
    rfcs = index.parse(INDEX)
    assert len(rfcs) > 9000
    assert rfcs[1035].title.startswith("Domain names")
    assert rfcs[1035].status == "INTERNET STANDARD"
    assert 1035 in rfcs[2181].updates
    assert 2535 in rfcs[4034].obsoletes


@needs_index
def test_dns_slice_contains_known_members():
    rfcs = index.parse(INDEX)
    core = index.slice_for(rfcs, [1034, 1035])
    assert {1034, 1035, 2181, 2308, 4033, 6891}.issubset(core)
    assert 9110 not in core
