"""Fill section and document vectors.

Resumable by construction: only rows with a null embedding are selected, so an
interrupted run continues where it stopped. Rate limits are waited out rather
than treated as failures, because a hosted provider will throttle a job this
size and dying at 0.7% is not a sensible response.
"""

import os
import time

from .. import corpus
from ..clients import llm
from ..clients.base import LLMError
from ..db import connect

BATCH = int(os.getenv("EMBED_BATCH", "16"))
PAUSE = float(os.getenv("EMBED_PAUSE", "0"))
MAX_WAIT = 300.0


def _text(title: str, body: str) -> str:
    return f"{title}\n\n{body}" if title else body


def _embed_with_patience(texts: list[str], label: str) -> list[list[float]]:
    wait = 5.0
    while True:
        try:
            return llm.embed(texts)
        except LLMError as exc:
            if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                raise
            print(f"  rate limited at {label}, waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, MAX_WAIT)


def _run(select: str, update: str, key: str, make_text, batch: int) -> int:
    done = 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute(select)
        rows = cur.fetchall()
        total = len(rows)
        if not total:
            return 0
        started = time.time()
        for i in range(0, total, batch):
            chunk = rows[i:i + batch]
            vectors = _embed_with_patience([make_text(r) for r in chunk],
                                           f"{done}/{total}")
            cur.executemany(update, [(str(v), r[0]) for r, v in zip(chunk, vectors)])
            conn.commit()
            done += len(chunk)
            rate = done / max(time.time() - started, 0.001)
            print(f"  {key} {done}/{total}  {rate:.0f}/s", flush=True)
            if PAUSE:
                time.sleep(PAUSE)
    return done


def run(batch: int = BATCH) -> int:
    return _run(
        "select id, coalesce(title, ''), body from section where embedding is null order by id",
        "update section set embedding = %s::vector where id = %s",
        "sections", lambda r: _text(r[1], r[2]), batch)


def documents(batch: int = BATCH) -> int:
    return _run(
        """select number, title, coalesce(abstract, '') from rfc
            where embedding is null
              and exists (select 1 from section s where s.rfc = rfc.number)
            order by number""",
        "update rfc set embedding = %s::vector where number = %s",
        "documents", lambda r: f"{r[1]}\n\n{r[2]}"[:4000], batch)


if __name__ == "__main__":
    n = run()
    corpus.stamp()
    print(f"embedded {n} sections" if n else "sections: nothing to embed")
    d = documents()
    print(f"embedded {d} documents" if d else "documents: nothing to embed")
