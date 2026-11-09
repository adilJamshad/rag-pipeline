from rfc_rag.models import Hit
from rfc_rag.services.search import _tsquery, fuse


def hit(sid: int, rfc: int = 1035, number: str = "1") -> Hit:
    return Hit(sid, rfc, f"section-{number}", number, "T", "body", 0.0)


def test_tsquery_joins_terms_by_mode():
    assert _tsquery("Max label LENGTH", "all") == "max & label & length"
    assert _tsquery("Max label LENGTH", "any") == "max | label | length"


def test_tsquery_drops_single_characters_and_empty():
    assert _tsquery("a DNS x", "all") == "dns"
    assert _tsquery("!!! ???", "all") == ""


def test_fuse_rewards_agreement_between_rankers():
    a = [hit(1), hit(2), hit(3)]
    b = [hit(3), hit(4), hit(5)]
    out = fuse([(a, 1.0), (b, 1.0)], k=3)
    assert out[0].section_id == 3


def test_fuse_respects_weights():
    a, b = [hit(1)], [hit(2)]
    assert fuse([(a, 1.0), (b, 5.0)], k=2)[0].section_id == 2
    assert fuse([(a, 5.0), (b, 1.0)], k=2)[0].section_id == 1


def test_fuse_keeps_first_seen_metadata_and_is_deterministic():
    a = [hit(7, rfc=1034, number="4.3.3")]
    b = [hit(7, rfc=9999, number="zzz")]
    out = fuse([(a, 1.0), (b, 1.0)], k=1)
    assert (out[0].rfc, out[0].number) == (1034, "4.3.3")


def test_hit_citation_and_url():
    h = hit(1, rfc=1035, number="2.3.4")
    assert h.cite == "RFC 1035 §2.3.4 T"
    assert h.url.endswith("rfc1035#section-2.3.4")
    part = Hit(2, 1035, "section-2.3.4.p2", "2.3.4", "T", "b", 0.0)
    assert part.url.endswith("rfc1035#section-2.3.4")
