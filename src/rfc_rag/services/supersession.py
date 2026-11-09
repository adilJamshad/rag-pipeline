"""What the obsoletes/updates graph knows about a document."""

from ..db import connect
from ..models import Fact


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
