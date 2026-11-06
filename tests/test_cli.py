from rfc_rag.pipeline import Answer
from rfc_rag.cli import render
from rfc_rag.facts import Fact
from rfc_rag.search import Hit


def hit(obsolete: bool = False) -> Hit:
    return Hit(1, 1035, "section-2.3.4", "2.3.4", "Size limits",
               "labels          63 octets or less", 0.8, obsolete)


def test_renders_verified_quote_with_citation_and_link():
    out = render(Answer("synthesis", "63 octets.", hits=[hit()], used=[hit()],
                        quote="labels          63 octets or less", grounded=True))
    assert "63 octets." in out
    assert "> labels" in out
    assert "RFC 1035 §2.3.4 Size limits" in out
    assert "rfc-editor.org/rfc/rfc1035#section-2.3.4" in out
    assert "verified" in out


def test_marks_unverified_quotes_loudly():
    out = render(Answer("synthesis", "x", used=[hit()], quote="not in the text", grounded=False))
    assert "UNVERIFIED" in out


def test_flags_obsolete_sources():
    out = render(Answer("synthesis", "x", used=[hit(obsolete=True)], quote="labels", grounded=True))
    assert "OBSOLETE" in out


def test_refusal_shows_near_misses_and_no_answer():
    out = render(Answer("refusal", "Not covered.", hits=[hit()]))
    assert "No answer found." in out
    assert "Closest sections:" in out
    assert "0.800" in out


def test_fact_route_shows_chain_through_to_living_documents():
    fact = Fact(2065, "DNSSEC", 1997, "PROPOSED STANDARD", True, [2535], [],
                [(4033, "A"), (4034, "B")])
    out = render(Answer("facts", fact.headline, fact=fact))
    assert "RFC 2535 -> RFC 4033, RFC 4034" in out


def test_fact_route_summarises_many_updates():
    fact = Fact(1035, "DNS", 1987, "INTERNET STANDARD", False, [], list(range(1, 30)),
                [(1035, "DNS")])
    out = render(Answer("facts", fact.headline, fact=fact))
    assert "29 later RFCs updated it" in out
    assert "+23 more" in out
