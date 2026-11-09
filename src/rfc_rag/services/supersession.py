import re

from ..db import connect
from ..models import Fact

RFC_REF = re.compile(r"\brfc[\s-]*(\d{1,5})\b", re.I)

INTENTS = [
    ("current", re.compile(r"\b(still (current|valid|in force)|current|valid|up to date|obsolete|dead)\b", re.I)),
    ("replaced", re.compile(r"\b(replac|supersed|obsolet|instead of|what should i read)\w*\b", re.I)),
    ("updated", re.compile(r"\b(update|updated by|amend|chang|modif)\w*\b", re.I)),
]


def referenced(question: str) -> int | None:
    m = RFC_REF.search(question)
    return int(m.group(1)) if m else None


def intent(question: str) -> str | None:
    for name, pattern in INTENTS:
        if pattern.search(question):
            return name
    return None


def is_fact_question(question: str) -> bool:
    return referenced(question) is not None and intent(question) is not None


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
