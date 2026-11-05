import time

from . import llm
from .db import connect

BATCH = 32


def _pending(cur) -> list[tuple[int, str, str]]:
    cur.execute("""
        select id, coalesce(title, ''), body
          from section
         where embedding is null
         order by id
    """)
    return cur.fetchall()


def _text(title: str, body: str) -> str:
    return f"{title}\n\n{body}" if title else body


def run(batch: int = BATCH) -> int:
    done = 0
    with connect() as conn, conn.cursor() as cur:
        rows = _pending(cur)
        total = len(rows)
        if not total:
            return 0
        started = time.time()
        for i in range(0, total, batch):
            chunk = rows[i:i + batch]
            vectors = llm.embed([_text(t, b) for _, t, b in chunk])
            cur.executemany(
                "update section set embedding = %s::vector where id = %s",
                [(str(v), sid) for (sid, _, _), v in zip(chunk, vectors)],
            )
            conn.commit()
            done += len(chunk)
            rate = done / max(time.time() - started, 0.001)
            print(f"  {done}/{total}  {rate:.0f}/s", flush=True)
    return done


if __name__ == "__main__":
    n = run()
    print(f"embedded {n} sections" if n else "nothing to embed")
