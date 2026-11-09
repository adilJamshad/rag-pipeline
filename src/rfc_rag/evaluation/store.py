"""Persist each evaluation run so changes can be compared, not remembered."""

import json
import subprocess

from .. import config
from ..db import connect


def _git() -> tuple[str | None, bool]:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=5).stdout.strip())
        return sha or None, dirty
    except Exception:
        return None, False


def _corpus(cur) -> tuple[int, int]:
    cur.execute("select count(distinct rfc), count(*) from section")
    return cur.fetchone()


def save(metrics: dict, per_question: list[dict], label: str | None = None,
         retrieval: str = "semantic") -> int:
    sha, dirty = _git()
    headline = {k: metrics.get(k) for k in (
        "doc_r1", "doc_r5", "doc_r10", "mrr", "answer_rate", "correct", "grounded",
        "cited_right", "false_refusal_rate", "refusal_accuracy",
        "p50_ms", "p95_ms", "tokens_in", "tokens_out", "llm_calls", "n_questions")}

    with connect() as conn, conn.cursor() as cur:
        docs, sections = _corpus(cur)
        cur.execute("""
            insert into eval_run (
                git_sha, dirty, label, retrieval, llm_model, embed_model, backend,
                corpus_docs, corpus_sections, n_questions,
                doc_r1, doc_r5, doc_r10, mrr,
                answer_rate, correct, grounded, cited_right,
                false_refusal_rate, refusal_accuracy,
                p50_ms, p95_ms, tokens_in, tokens_out, llm_calls, extra
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            returning id
        """, (
            sha, dirty, label, retrieval, config.LLM_MODEL, config.EMBED_MODEL,
            config.LLM_BACKEND, docs, sections, headline["n_questions"],
            headline["doc_r1"], headline["doc_r5"], headline["doc_r10"], headline["mrr"],
            headline["answer_rate"], headline["correct"], headline["grounded"],
            headline["cited_right"], headline["false_refusal_rate"],
            headline["refusal_accuracy"], headline["p50_ms"], headline["p95_ms"],
            headline["tokens_in"], headline["tokens_out"], headline["llm_calls"],
            json.dumps({k: v for k, v in metrics.items() if k not in headline}),
        ))
        run_id = cur.fetchone()[0]
        if per_question:
            cur.executemany("""
                insert into eval_result (run_id, question_id, question, kind, gold_rank,
                                         route, correct, grounded, cited_right, total_ms)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, [(run_id, q["id"], q.get("question"), q.get("kind"), q.get("gold_rank"),
                   q.get("route"), q.get("correct"), q.get("grounded"),
                   q.get("cited_right"), q.get("total_ms")) for q in per_question])
        conn.commit()
    return run_id


def history(limit: int = 10) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select id, at, git_sha, dirty, label, retrieval, n_questions,
                   doc_r5, doc_r10, mrr, correct, grounded, refusal_accuracy, p50_ms
              from eval_run order by at desc limit %s
        """, (limit,))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def regressions(run_id: int, baseline_id: int) -> list[dict]:
    """Questions that were right in the baseline and wrong now."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select n.question_id, n.question, b.gold_rank, n.gold_rank,
                   b.correct, n.correct, b.grounded, n.grounded
              from eval_result n
              join eval_result b on b.question_id = n.question_id and b.run_id = %s
             where n.run_id = %s
               and (coalesce(b.correct, false) and not coalesce(n.correct, false)
                    or coalesce(b.grounded, false) and not coalesce(n.grounded, false)
                    or (b.gold_rank is not null and n.gold_rank is null))
        """, (baseline_id, run_id))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
