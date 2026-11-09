import html
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import Section

LEGACY_HEADING = re.compile(
    r'<span class="h\d+"><a class="selflink" id="(section-[\d.]+)"[^>]*>([\d.]+)</a>\.?\s*(.*?)</span>',
    re.S,
)
TAG = re.compile(r"<[^>]+>")
BLANKS = re.compile(r"\n{3,}")

SKIP_TITLES = re.compile(
    r"^(status of th|copyright|table of contents|full copyright|intellectual property|"
    r"author.s address|editor.s address|index$|notices$)",
    re.I,
)
SKIP_ANCHORS = ("section-boilerplate", "section-toc")


def _clean(raw: str) -> str:
    return BLANKS.sub("\n\n", html.unescape(TAG.sub("", raw))).strip()


def _keep(anchor: str, title: str) -> bool:
    return not anchor.startswith(SKIP_ANCHORS) and not SKIP_TITLES.match(title.strip())


def _legacy(doc: str) -> list[Section]:
    marks = list(LEGACY_HEADING.finditer(doc))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(doc)
        raw = doc[m.end():end]
        title = _clean(m.group(3))
        if not _keep(m.group(1), title):
            continue
        body = _clean(raw)
        if body:
            out.append(Section(m.group(1), m.group(2), title, body, "<pre" in raw))
    return out


def _modern(doc: str) -> list[Section]:
    tree = HTMLParser(doc)
    out = []
    for node in tree.css("section[id^='section-']"):
        anchor = node.attributes.get("id", "")
        head = node.css_first("h1,h2,h3,h4,h5,h6")
        number, title = None, ""
        if head is not None:
            num = head.css_first("a.section-number")
            name = head.css_first("a.section-name")
            number = num.text().strip().rstrip(".") if num else None
            title = (name.text() if name else head.text()).strip()
        if not _keep(anchor, title):
            continue

        parts, has_pre = [], False
        for child in node.iter():
            if child.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                continue
            if child.tag == "section" or child.css_first("section[id^='section-']"):
                break
            if child.tag in ("pre", "artwork", "sourcecode") or child.css_first("pre"):
                has_pre = True
            parts.append(child.text())
        body = BLANKS.sub("\n\n", "\n".join(parts)).strip()
        if body:
            out.append(Section(anchor, number, title, body, has_pre))
    return out


MAX_TOKENS = 1200


def _split_oversized(section: Section) -> list[Section]:
    if section.tokens <= MAX_TOKENS:
        return [section]

    budget = MAX_TOKENS * 4
    parts, current = [], ""
    for para in section.body.split("\n\n"):
        if current and len(current) + len(para) > budget:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)

    if len(parts) == 1:
        return [section]
    return [
        Section(f"{section.anchor}.p{i}", section.number, section.title, body, section.has_pre)
        for i, body in enumerate(parts, 1)
    ]


def _unstructured(doc: str) -> list[Section]:
    tree = HTMLParser(doc)
    blocks = tree.css("pre") or ([tree.body] if tree.body else [])
    body = BLANKS.sub("\n\n", "\n".join(b.text() for b in blocks)).strip()
    if not body:
        return []
    return [Section("body", None, "", body, bool(tree.css("pre")))]


def sections(doc: str) -> list[Section]:
    found = _modern(doc) if "<section id=\"section-" in doc else _legacy(doc)
    if not found:
        found = _unstructured(doc)
    return [part for s in found for part in _split_oversized(s)]
