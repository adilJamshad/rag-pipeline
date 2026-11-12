"""What the obsoletes/updates graph knows about a document."""

from ..db import connect
from ..models import Change, Fact


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
