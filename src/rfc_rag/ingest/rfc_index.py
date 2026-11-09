import re
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from ..models import Rfc

INDEX_URL = "https://www.rfc-editor.org/rfc-index.xml"
NS = "{https://www.rfc-editor.org/rfc-index}"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


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

        kw_node = entry.find(NS + "keywords")
        abs_node = entry.find(NS + "abstract")

        out[number] = Rfc(
            number=number,
            title=(entry.findtext(NS + "title") or "").strip(),
            year=int(year) if year and year.isdigit() else None,
            status=entry.findtext(NS + "current-status"),
            stream=entry.findtext(NS + "stream"),
            pages=int(pages) if pages and pages.isdigit() else None,
            errata_url=errata.text if errata is not None else None,
            keywords=[(k.text or "").strip() for k in kw_node] if kw_node is not None else [],
            abstract=" ".join((t.text or "") for t in abs_node) if abs_node is not None else "",
            wg=entry.findtext(NS + "wg_acronym"),
            obsoletes=refs("obsoletes"),
            updates=refs("updates"),
        )
    return out


DNS_WORKING_GROUPS = {
    "dnsop", "dnsext", "dnssec", "dnsind", "dnssd", "doh", "dprive", "dane",
    "add", "deleg", "dbound", "dnsce", "namedroppers",
}

DNS_KEYWORDS = {
    "dns", "dnssec", "domain name system", "domain name", "domain names",
    "resolver", "name server", "nameserver", "zone", "doh", "dot", "doq",
    "nsec", "nsec3", "dnskey", "rrsig", "tsig", "edns", "mdns", "dns-sd",
    "resource record", "qname", "rcode", "tlsa", "dane",
}

TITLE_HINTS = re.compile(
    r"\b(dns|dnssec|domain names?|name servers?|nameservers?|resolvers?|zone transfers?|"
    r"resource records?|nsec3?|dnskey|rrsig|tsig|edns|mdns|dnssd)\b", re.I)

EXCLUDE_TITLE = re.compile(r"\b(april fool|april 1)\b", re.I)


def is_dns(r: Rfc) -> bool:
    if EXCLUDE_TITLE.search(r.title):
        return False
    if r.wg and r.wg.lower() in DNS_WORKING_GROUPS:
        return True
    if any(k.strip().lower() in DNS_KEYWORDS for k in r.keywords):
        return True
    return bool(TITLE_HINTS.search(r.title))


def by_topic(rfcs: dict[int, Rfc]) -> set[int]:
    return {n for n, r in rfcs.items() if is_dns(r)}


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
