"""What the obsoletes/updates graph knows about a document."""

from ..db import connect
from ..models import Change, Fact, Hit


def lookup(number: int) -> Fact | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select number, title, year, status, is_obsolete,
                   coalesce(obsoleted_by, '{}'), coalesce(updated_by, '{}')
              from rfc_status where number = %s
        """, (number,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("select rfc, title from current_for(%s)", (number,))
        current = [(r[0], r[1]) for r in cur.fetchall()]
    return Fact(*row, current=current)


def recent_changes(limit: int = 8) -> list[Change]:
    """Most recent edges of the graph, newest first.

    Aggregate across the corpus, so it belongs to no single document - which is
    why a question like "what changed last?" has no answer on the facts route.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select x.kind, x.src, s.title, s.year, x.dst, d.title
              from rfc_relation x
              join rfc s on s.number = x.src
              join rfc d on d.number = x.dst
             where s.year is not null
             order by s.year desc, x.src desc
             limit %s
        """, (limit,))
        return [Change(*row) for row in cur.fetchall()]


def newest(limit: int = 6) -> list[Fact]:
    """Most recently published documents, newest first.

    Date ordering, not similarity: "the last RFC" is a constraint embeddings
    cannot represent, so it must be answered by the column that holds it.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select number from rfc
             where year is not null
               and exists (select 1 from section s where s.rfc = rfc.number)
             order by year desc, number desc
             limit %s
        """, (limit,))
        numbers = [r[0] for r in cur.fetchall()]
    return [f for f in (lookup(n) for n in numbers) if f]


def section(rfc: int, number: str) -> list[Hit]:
    """Exactly the section asked for, or nothing."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select s.id, s.rfc, s.anchor, s.number, s.title, s.body, 1.0,
                   exists (select 1 from rfc_relation x
                            where x.dst = s.rfc and x.kind = 'obsoletes')
              from section s
             where s.rfc = %s and s.number = %s
             order by s.anchor
        """, (rfc, number))
        return [Hit(*row) for row in cur.fetchall()]
