import json
import sys
from pathlib import Path

from .db import connect

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


def passages() -> list[dict]:
    from passages import PASSAGES

    out, missing = [], []
    with connect() as conn, conn.cursor() as cur:
        for i, (question, gold) in enumerate(PASSAGES, 1):
            resolved = []
            for rfc, number in gold:
                cur.execute(
                    "select anchor from section where rfc = %s and number = %s", (rfc, number)
                )
                anchors = [r[0] for r in cur.fetchall()]
                if not anchors:
                    missing.append((question, rfc, number))
                    continue
                resolved.append({"rfc": rfc, "number": number, "anchors": anchors})
            if resolved:
                out.append({
                    "id": f"passage-{i:02d}", "question": question,
                    "kind": "passage", "gold": resolved,
                })
    if missing:
        raise SystemExit(f"gold sections not found in the corpus: {missing}")
    return out


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, rows in (("facts", facts()), ("passages", passages())):
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids)), f"duplicate ids in {name}"
        with (OUT / f"{name}.jsonl").open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"{name}: {len(rows)} questions")
