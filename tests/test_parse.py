from rfc_rag import parse
from rfc_rag.parse import Section, sections

LEGACY = """<pre>
<span class="h2"><a class="selflink" id="section-1" href="#section-1">1</a>. Introduction</span>

   Intro body here.

<span class="h3"><a class="selflink" id="section-1.1" href="#section-1.1">1.1</a>. Size limits</span>

   labels          63 octets or less

<span class="h2"><a class="selflink" id="section-2" href="#section-2">2</a>. Status of this memo</span>

   Boilerplate that must be dropped.
</pre>"""

MODERN = """<section id="section-1">
<h2 id="name-intro"><a href="#section-1" class="section-number selfRef">1. </a><a href="#name-intro" class="section-name selfRef">Intro</a></h2>
<p>Parent prose.</p>
<div>
  <section id="section-1.1">
  <h3 id="name-sub"><a href="#section-1.1" class="section-number selfRef">1.1. </a><a href="#name-sub" class="section-name selfRef">Sub</a></h3>
  <p>Child prose only.</p>
  <pre>+---+</pre>
  </section>
</div>
</section>"""


def test_legacy_splits_on_heading_anchors():
    got = sections(LEGACY)
    assert [s.number for s in got] == ["1", "1.1"]
    assert got[0].anchor == "section-1"
    assert "63 octets" in got[1].body


def test_legacy_drops_boilerplate_sections():
    assert all("Boilerplate" not in s.body for s in sections(LEGACY))


def test_modern_does_not_duplicate_nested_sections():
    got = sections(MODERN)
    bodies = {s.anchor: s.body for s in got}
    assert bodies["section-1"] == "Parent prose."
    assert "Child prose only." in bodies["section-1.1"]
    assert "Child prose only." not in bodies["section-1"]


def test_modern_flags_pre_blocks():
    by_anchor = {s.anchor: s for s in sections(MODERN)}
    assert by_anchor["section-1.1"].has_pre
    assert not by_anchor["section-1"].has_pre


def test_oversized_sections_split_on_paragraphs():
    body = "\n\n".join(["x" * 2000] * 5)
    got = parse._split_oversized(Section("section-9", "9", "Big", body, False))
    assert len(got) > 1
    assert [s.anchor for s in got] == [f"section-9.p{i}" for i in range(1, len(got) + 1)]
    assert all(s.tokens <= parse.MAX_TOKENS for s in got)
    assert all(s.number == "9" for s in got)


def test_unsplittable_paragraph_is_left_alone():
    one = Section("section-9", "9", "Big", "y" * 9000, False)
    assert parse._split_oversized(one) == [one]


def test_unstructured_document_falls_back_to_chunking():
    doc = "<pre>" + "\n\n".join(["para " + "z" * 2000] * 4) + "</pre>"
    got = sections(doc)
    assert len(got) > 1
    assert all(s.anchor.startswith("body.p") for s in got)
    assert all(s.tokens <= parse.MAX_TOKENS for s in got)


def test_unstructured_fallback_not_used_when_anchors_exist():
    assert all(s.anchor != "body" for s in sections(LEGACY))
