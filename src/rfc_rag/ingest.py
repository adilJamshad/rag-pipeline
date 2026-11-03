from pathlib import Path

from . import index
from .db import connect

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


if __name__ == "__main__":
    core, keep = load_index()
    print(f"loaded {len(keep)} RFCs ({len(core)} in the DNS core)")
