"""Make the suite runnable against an empty Postgres.

Tests previously assumed a developer machine with the full corpus loaded, which
is why one of them silently overwrote the live corpus stamp. CI starts from
nothing, so the schema is applied and a small fixture corpus is seeded here.
"""

import os
from pathlib import Path

import pytest

SQL = Path(__file__).resolve().parent.parent / "sql"

# Enough shape to exercise supersession: a live base spec with updates, a dead
# document whose replacement is also dead, and the live documents at the end.
SEED = """
insert into rfc (number, title, year, status, stream, pages) values
  (1034, 'Domain names - concepts and facilities', 1987, 'INTERNET STANDARD', 'Legacy', 55),
  (1035, 'Domain names - implementation and specification', 1987, 'INTERNET STANDARD', 'Legacy', 55),
  (2065, 'Domain Name System Security Extensions', 1997, 'PROPOSED STANDARD', 'IETF', 47),
  (2181, 'Clarifications to the DNS Specification', 1997, 'PROPOSED STANDARD', 'IETF', 15),
  (2535, 'Domain Name System Security Extensions', 1999, 'PROPOSED STANDARD', 'IETF', 47),
  (4033, 'DNS Security Introduction and Requirements', 2005, 'PROPOSED STANDARD', 'IETF', 21),
  (4034, 'Resource Records for the DNS Security Extensions', 2005, 'PROPOSED STANDARD', 'IETF', 29),
  (4035, 'Protocol Modifications for the DNS Security Extensions', 2005, 'PROPOSED STANDARD', 'IETF', 53)
on conflict (number) do nothing;

insert into rfc_relation (src, dst, kind) values
  (2535, 2065, 'obsoletes'),
  (4033, 2535, 'obsoletes'), (4034, 2535, 'obsoletes'), (4035, 2535, 'obsoletes'),
  (2181, 1035, 'updates'), (2065, 1035, 'updates'), (4034, 1035, 'updates')
on conflict do nothing;

insert into section (rfc, anchor, number, title, body, tokens, has_pre) values
  (1035, 'section-2.3.4', '2.3.4', 'Size limits',
   'Various objects and parameters in the DNS have size limits.

labels          63 octets or less

names           255 octets or less', 77, false),
  (1034, 'section-3.6.2', '3.6.2', 'Aliases and canonical names',
   'A CNAME RR identifies the canonical name of an alias.', 30, false)
on conflict (rfc, anchor) do nothing;
"""


DUPLICATE = ("already exists", "duplicate")


def _apply_schema() -> None:
    """Each file in its own transaction; objects that already exist are fine.

    The migration files are not idempotent, so a developer database that
    already has them raises DuplicateTable. CI starts empty and needs them all.
    """
    import psycopg

    from rfc_rag.db import connect

    for path in sorted(SQL.glob("*.sql")) + [None]:
        statement = SEED if path is None else path.read_text()
        try:
            with connect() as conn, conn.cursor() as cur:
                cur.execute(statement)
                conn.commit()
        except psycopg.errors.Error as exc:
            if not any(word in str(exc).lower() for word in DUPLICATE):
                raise


@pytest.fixture(scope="session", autouse=True)
def database():
    """Apply schema and seed once. Harmless against an already-loaded database."""
    if os.getenv("SKIP_DB_SETUP"):
        return
    try:
        _apply_schema()
    except Exception as exc:  # a missing database is reported by the tests that need it
        pytest.skip(f"no database available: {type(exc).__name__}: {exc}",
                    allow_module_level=True)


@pytest.fixture(autouse=True)
def protect_corpus_stamp():
    """corpus_meta is live state; no test may leave it changed."""
    from rfc_rag import corpus
    from rfc_rag.db import connect

    try:
        before = corpus.recorded()
    except Exception:
        yield
        return
    yield
    after = corpus.recorded()
    if after == before:
        return
    with connect() as conn, conn.cursor() as cur:
        if before is None:
            cur.execute("delete from corpus_meta where id = 1")
        else:
            cur.execute("""insert into corpus_meta (id, embed_model, embed_dim)
                           values (1, %s, %s)
                           on conflict (id) do update set
                             embed_model = excluded.embed_model,
                             embed_dim = excluded.embed_dim""", before)
        conn.commit()
