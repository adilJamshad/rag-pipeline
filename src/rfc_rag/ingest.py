from pathlib import Path

from . import fetch, index
from .db import connect
from .parse import sections

DATA = Path("data")
SEEDS = [1034, 1035]


def load_index(seeds: list[int] = SEEDS) -> tuple[set[int], set[int]]:
    rfcs = index.parse(index.download(DATA / "rfc-index.xml"))
    core = index.slice_for(rfcs, seeds)
    keep = index.closure(rfcs, core)

    rows = [
        (r.number, r.title, r.year, r.status, r.stream, r.pages, r.errata_url)
        for n in sorted(keep)
        for r in [rfcs[n]]
    ]
    links = [
        (r.number, target, kind)
        for n in sorted(keep)
        for r in [rfcs[n]]
        for kind, targets in (("obsoletes", r.obsoletes), ("updates", r.updates))
        for target in targets
        if target in keep
    ]

    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """insert into rfc (number, title, year, status, stream, pages, errata_url)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (number) do update set
                 title = excluded.title, year = excluded.year,
                 status = excluded.status, stream = excluded.stream,
                 pages = excluded.pages, errata_url = excluded.errata_url""",
            rows,
        )
        cur.executemany(
            """insert into rfc_relation (src, dst, kind) values (%s, %s, %s)
               on conflict do nothing""",
            links,
        )
        conn.commit()
    return core, keep


def load_sections(numbers: set[int]) -> int:
    total = 0
    with connect() as conn, conn.cursor() as cur:
        for n in sorted(numbers):
            parsed = sections(fetch.html(n))
            cur.executemany(
                """insert into section (rfc, anchor, number, title, body, tokens, has_pre)
                   values (%s, %s, %s, %s, %s, %s, %s)
                   on conflict (rfc, anchor) do update set
                     number = excluded.number, title = excluded.title,
                     body = excluded.body, tokens = excluded.tokens,
                     has_pre = excluded.has_pre, embedding = null""",
                [(n, s.anchor, s.number, s.title, s.body, s.tokens, s.has_pre) for s in parsed],
            )
            conn.commit()
            total += len(parsed)
            print(f"  rfc{n:<5} {len(parsed):>4} sections", flush=True)
    return total


if __name__ == "__main__":
    core, keep = load_index()
    print(f"loaded {len(keep)} RFCs ({len(core)} in the DNS core)")
    total = load_sections(core)
    print(f"parsed {total} sections")
