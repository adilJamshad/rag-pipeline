import re
from dataclasses import dataclass

from .db import connect

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*")


@dataclass
class Hit:
    section_id: int
    rfc: int
    anchor: str
    number: str | None
    title: str
    body: str
    score: float

    @property
    def cite(self) -> str:
        where = f"§{self.number}" if self.number else ""
        return f"RFC {self.rfc} {where} {self.title}".strip()

    @property
    def url(self) -> str:
        return f"https://www.rfc-editor.org/rfc/rfc{self.rfc}#{self.anchor.split('.p')[0]}"


def _tsquery(text: str, mode: str) -> str:
    words = [w.lower() for w in WORD.findall(text) if len(w) > 1]
    if not words:
        return ""
    joiner = " & " if mode == "all" else " | "
    return joiner.join(words)


def keyword(query: str, k: int = 5, mode: str = "any", current_only: bool = False) -> list[Hit]:
    tsq = _tsquery(query, mode)
    if not tsq:
        return []

    sql = """
        select s.id, s.rfc, s.anchor, s.number, s.title, s.body,
               ts_rank_cd(s.fts, q) as score
          from section s, to_tsquery('english', %s) q
         where s.fts @@ q
    """
    params: list[object] = [tsq]
    if current_only:
        sql += """ and not exists (select 1 from rfc_relation x
                                    where x.dst = s.rfc and x.kind = 'obsoletes')"""
    sql += " order by score desc, s.rfc, s.anchor limit %s"
    params.append(k)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [Hit(*row) for row in cur.fetchall()]
