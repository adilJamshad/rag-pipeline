import json
import sys
from pathlib import Path

from ..clients import llm
from ..db import connect

OUT = Path("eval")
sys.path.insert(0, str(OUT))


def facts() -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select number, is_obsolete, obsoleted_by, update_count, updated_by
              from rfc_status
             where exists (select 1 from section s where s.rfc = rfc_status.number)
             order by number
        """)
        rows = cur.fetchall()

    out = []
    for number, obsolete, obsoleted_by, update_count, updated_by in rows:
        for field, question, answer in [
            ("current", f"Is RFC {number} still current?", not obsolete),
            ("replaced", f"Has RFC {number} been replaced?", obsolete),
            ("obsoleted_by", f"What replaced RFC {number}?", sorted(obsoleted_by or [])),
            ("updated_by", f"What updates RFC {number}?", sorted(updated_by or [])),
            ("update_count", f"How many RFCs have updated RFC {number}?", update_count),
        ]:
            out.append({
                "id": f"fact-{number}-{field}", "question": question,
                "kind": "facts", "field": field, "rfc": number, "answer": answer,
            })
    return out


def _best_sections(cur, rfc: int, question: str, limit: int = 3) -> list[dict]:
    vector = str(llm.embed([question])[0])
    cur.execute("""
        select anchor, number, title
          from section
         where rfc = %s and embedding is not null
         order by embedding <=> %s::vector
         limit %s
    """, (rfc, vector, limit))
    return [{"rfc": rfc, "anchor": a, "number": n, "title": t} for a, n, t in cur.fetchall()]


def answerable() -> tuple[list[dict], list[str]]:
    from questions import ANSWERABLE

    out, problems = [], []
    with connect() as conn, conn.cursor() as cur:
        for i, (question, rfc, expect) in enumerate(ANSWERABLE, 1):
            cur.execute("select count(*) from section where rfc = %s", (rfc,))
            if not cur.fetchone()[0]:
                problems.append(f"RFC {rfc} absent from corpus -> {question}")
                continue
            out.append({
                "id": f"q-{i:02d}", "question": question, "kind": "answerable",
                "rfc": rfc, "expect": expect, "gold": _best_sections(cur, rfc, question),
            })
    return out, problems


def unanswerable() -> list[dict]:
    from questions import UNANSWERABLE

    return [{"id": f"neg-{i:02d}", "question": q, "kind": "unanswerable"}
            for i, q in enumerate(UNANSWERABLE, 1)]


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    rows, problems = answerable()
    for name, data in (("facts", facts()), ("answerable", rows), ("unanswerable", unanswerable())):
        ids = [r["id"] for r in data]
        assert len(ids) == len(set(ids)), f"duplicate ids in {name}"
        with (OUT / f"{name}.jsonl").open("w") as fh:
            for r in data:
                fh.write(json.dumps(r) + "\n")
        print(f"{name}: {len(data)}")
    for p in problems:
        print(f"  GAP: {p}")
