"""The embedding model is part of the corpus, not a runtime setting.

Vectors from one model cannot be compared with vectors from another, so the
model that produced them is recorded alongside them and checked before the
first query.
"""

import logging

from . import config
from .db import connect

log = logging.getLogger(__name__)


class EmbeddingMismatch(RuntimeError):
    pass


def stamp() -> None:
    """Record which model produced the vectors currently in the database."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            insert into corpus_meta (id, embed_model, embed_dim, embed_base, embedded_at)
            values (1, %s, %s, %s, now())
            on conflict (id) do update set
              embed_model = excluded.embed_model, embed_dim = excluded.embed_dim,
              embed_base = excluded.embed_base, embedded_at = now()
        """, (config.EMBED_MODEL, config.EMBED_DIM, config.EMBED_BASE_URL))
        conn.commit()


def recorded() -> tuple[str, int] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select embed_model, embed_dim from corpus_meta where id = 1")
        return cur.fetchone()


def check() -> None:
    """Fail loudly when the configured embedder is not the one in the database."""
    found = recorded()
    if found is None:
        log.warning("corpus has no embedding stamp; run the embeddings job to set one")
        return
    model, dim = found
    if model != config.EMBED_MODEL or dim != config.EMBED_DIM:
        raise EmbeddingMismatch(
            f"corpus was embedded with {model} ({dim}d) but EMBED_MODEL is "
            f"{config.EMBED_MODEL} ({config.EMBED_DIM}d). Vectors from different "
            f"models are not comparable — re-run the embeddings job, or set "
            f"EMBED_MODEL back to {model}."
        )
