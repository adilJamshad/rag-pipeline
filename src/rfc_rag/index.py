import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import httpx

INDEX_URL = "https://www.rfc-editor.org/rfc-index.xml"
NS = "{https://www.rfc-editor.org/rfc-index}"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


@dataclass
class Rfc:
    number: int
    title: str
    year: int | None
    status: str | None
    stream: str | None
    pages: int | None
    errata_url: str | None
    obsoletes: list[int] = field(default_factory=list)
    updates: list[int] = field(default_factory=list)


def download(path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", INDEX_URL, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            with path.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
    return path


def _num(doc_id: str | None) -> int | None:
    if doc_id and doc_id.startswith("RFC") and doc_id[3:].isdigit():
        return int(doc_id[3:])
    return None


def parse(path: Path) -> dict[int, Rfc]:
    out: dict[int, Rfc] = {}
    for entry in ET.parse(path).getroot():
        if entry.tag != NS + "rfc-entry":
            continue
        number = _num(entry.findtext(NS + "doc-id"))
        if number is None:
            continue

        def refs(name: str) -> list[int]:
            node = entry.find(NS + name)
            if node is None:
                return []
            return [n for n in (_num(d.text) for d in node.findall(NS + "doc-id")) if n]

        pages = entry.findtext(NS + "page-count")
        year = entry.findtext(NS + "date/" + NS + "year")
        errata = entry.find(NS + "errata-url")

        out[number] = Rfc(
            number=number,
            title=(entry.findtext(NS + "title") or "").strip(),
            year=int(year) if year and year.isdigit() else None,
            status=entry.findtext(NS + "current-status"),
            stream=entry.findtext(NS + "stream"),
            pages=int(pages) if pages and pages.isdigit() else None,
            errata_url=errata.text if errata is not None else None,
            obsoletes=refs("obsoletes"),
            updates=refs("updates"),
        )
    return out


def slice_for(rfcs: dict[int, Rfc], seeds: list[int], hops: int = 2) -> set[int]:
    inbound: dict[int, set[int]] = {}
    for r in rfcs.values():
        for target in r.obsoletes + r.updates:
            inbound.setdefault(target, set()).add(r.number)

    core = set(seeds)
    for _ in range(hops):
        nxt = set(core)
        for n in core:
            nxt |= inbound.get(n, set())
            if n in rfcs:
                nxt |= set(rfcs[n].obsoletes) | set(rfcs[n].updates)
        if nxt == core:
            break
        core = nxt
    return {n for n in core if n in rfcs}


def closure(rfcs: dict[int, Rfc], core: set[int]) -> set[int]:
    inbound: dict[int, set[int]] = {}
    for r in rfcs.values():
        for target in r.obsoletes + r.updates:
            inbound.setdefault(target, set()).add(r.number)

    out = set(core)
    for n in core:
        out |= inbound.get(n, set())
        out |= set(rfcs[n].obsoletes) | set(rfcs[n].updates)
    return {n for n in out if n in rfcs}
