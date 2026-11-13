"""MCP server over streamable HTTP, mounted into the same app as the REST API.

Deliberately exposes facts and retrieval, not synthesis. A client connecting
here already has a model; asking ours to summarise so theirs can paraphrase the
summary loses information at both steps and spends the provider budget to do
it. The caller gets verified sections and does its own reasoning.

Consequence: every tool here costs zero provider calls, so its rate limit is an
order of magnitude looser than the REST API's.
"""

import logging

from mcp.server.mcpserver import Context, MCPServer

from ..models import Fact, Hit
from ..services import supersession
from ..services.search import semantic
from . import guards

log = logging.getLogger(__name__)

mcp = MCPServer(
    "rfc-rag",
    instructions=(
        "Answers about IETF DNS specifications, grounded in the published RFC "
        "corpus. Use rfc_search to find relevant text, rfc_section for the exact "
        "wording of a numbered section, and rfc_status before relying on any RFC "
        "— 71 of the 417 documents here have been replaced, and many more have "
        "been amended by later RFCs."
    ),
)

DEMOTE = 0.05
MAX_K = 8


def _client(ctx: Context | None) -> str:
    """Identify the caller for rate limiting."""
    if ctx is None:
        return "unknown"
    try:
        headers = ctx.headers or {}
    except Exception:
        return "unknown"
    forwarded = headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip()
            or headers.get("x-real-ip", "")
            or "unknown")


def _hit(h: Hit) -> dict:
    return {"rfc": h.rfc, "section": h.number, "title": h.title,
            "url": h.url, "score": round(h.score, 4),
            "obsolete_document": h.obsolete, "text": h.body}


def _fact(f: Fact) -> dict:
    return {"rfc": f.rfc, "title": f.title, "year": f.year, "status": f.status,
            "obsolete": f.obsolete,
            "replaced_by": f.obsoleted_by or None,
            "read_instead": [n for n, _ in f.current] if f.obsolete else None,
            "updated_by": f.updated_by or None,
            "updated_by_count": len(f.updated_by),
            "summary": f.headline,
            "url": f.url}


@mcp.tool()
def rfc_status(number: int, ctx: Context = None) -> dict:
    """Check whether an RFC is still current, what replaced it, and which later
    RFCs amended it.

    Answers from the published IETF supersession graph, so the result is a
    lookup rather than a model's recollection. Call this before citing any RFC:
    a document can be decades out of date while still reading as authoritative,
    and one that was never replaced may still have been amended many times
    (RFC 1035 has 29 such amendments).
    """
    guards.check_mcp(_client(ctx))
    fact = supersession.lookup(number)
    if not fact:
        return {"error": f"RFC {number} is not in this corpus (DNS-related RFCs only)."}
    return _fact(fact)


@mcp.tool()
def rfc_search(query: str, k: int = 4, current_only: bool = False,
               ctx: Context = None) -> dict:
    """Search the DNS RFC corpus and return the most relevant sections, each
    with its RFC number, section number, URL and full text.

    Use this before answering any question about what a DNS specification says,
    rather than recalling it. Results carry the publication status of their
    document, so an answer can note when its source has been superseded. Set
    current_only to exclude documents that have been replaced.
    """
    guards.check_mcp(_client(ctx))
    k = max(1, min(int(k), MAX_K))
    hits = semantic(query, k, demote=DEMOTE, current_only=current_only)
    if not hits:
        return {"query": query, "sections": [],
                "note": "Nothing matched. This corpus covers DNS RFCs only."}
    return {"query": query, "sections": [_hit(h) for h in hits],
            "note": "Check rfc_status before relying on any document listed here."}


@mcp.tool()
def rfc_section(number: int, section: str, ctx: Context = None) -> dict:
    """Fetch the exact text of one numbered section of an RFC, for example
    section 2.3.4 of RFC 1035.

    Returns an error rather than a nearby section when the one asked for does
    not exist, so a precise citation is never answered with an approximate one.
    """
    guards.check_mcp(_client(ctx))
    hits = supersession.section(number, section)
    if not hits:
        return {"error": f"RFC {number} has no section {section} in this corpus."}
    fact = supersession.lookup(number)
    return {"rfc": number, "section": section,
            "sections": [_hit(h) for h in hits],
            "document_status": fact.headline if fact else None}


def http_app(path: str = "/mcp"):
    """Streamable HTTP app, stateless so it survives being scaled across workers."""
    return mcp.streamable_http_app(streamable_http_path=path, stateless_http=True)
