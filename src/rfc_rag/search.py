import re
from dataclasses import dataclass

from . import llm
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
    obsolete: bool = False

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
               ts_rank_cd(s.fts, q) as score,
               exists (select 1 from rfc_relation x
                        where x.dst = s.rfc and x.kind = 'obsoletes') as obsolete
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


def fuse(ranked: list[tuple[list[Hit], float]], k: int, rrf_k: int = 60) -> list[Hit]:
    scores: dict[int, float] = {}
    best: dict[int, Hit] = {}
    for hits, weight in ranked:
        for rank, hit in enumerate(hits, 1):
            scores[hit.section_id] = scores.get(hit.section_id, 0.0) + weight / (rrf_k + rank)
            best.setdefault(hit.section_id, hit)

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    return [Hit(**{**best[sid].__dict__, "score": score}) for sid, score in ordered]


OBSOLETE = """exists (select 1 from rfc_relation x
                      where x.dst = s.rfc and x.kind = 'obsoletes')"""


def semantic(query: str, k: int = 5, current_only: bool = False,
             demote: float = 0.0, only_rfc: int | None = None) -> list[Hit]:
    vector = llm.embed([query])[0]

    sql = f"""
        select s.id, s.rfc, s.anchor, s.number, s.title, s.body,
               1 - (s.embedding <=> %s::vector) - (case when {OBSOLETE} then %s else 0 end)
                 as score,
               {OBSOLETE} as obsolete
          from section s
         where s.embedding is not null
    """
    params: list[object] = [str(vector), demote]
    if current_only:
        sql += f" and not {OBSOLETE}"
    if only_rfc is not None:
        sql += " and s.rfc = %s"
        params.append(only_rfc)
    sql += " order by score desc limit %s"
    params.append(k)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [Hit(*row) for row in cur.fetchall()]


def hybrid(query: str, k: int = 5, current_only: bool = False, pool: int = 30,
           kw_weight: float = 1.0, vec_weight: float = 1.0, rrf_k: int = 60) -> list[Hit]:
    kw = keyword(query, pool, mode="all", current_only=current_only)
    if len(kw) < pool // 2:
        kw = keyword(query, pool, mode="any", current_only=current_only)
    vec = semantic(query, pool, current_only=current_only)

    return fuse([(kw, kw_weight), (vec, vec_weight)], k, rrf_k)
