"""Persist one row per question, and report over them.

Recording must never break answering: every failure here is swallowed and
logged, never raised.
"""

import json
import logging
import os

from .db import connect
from .models import Answer

log = logging.getLogger(__name__)

ENABLED = os.getenv("QUERY_LOG", "1") not in ("0", "false", "no")


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
    )


def record(answer: Answer, error: str | None = None) -> int | None:
    if not ENABLED:
        return None
    try:
        from .clients import llm

        trace = answer.trace
        usage = llm.last_usage or {}
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""
                insert into query_log (
                    question, route, answered, grounded, backend, llm_calls,
                    total_ms, timings, context_tokens, prompt_tokens,
                    completion_tokens, retrieved, cited, topic_rfc, answer, quote, error
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                returning id
            """, (
                trace.question or answer.text[:200],
                answer.route,
                answer.route != "refusal" and error is None,
                answer.grounded,
                llm.last_used,
                trace.llm_calls,
                int(trace.total * 1000),
                json.dumps(trace.timings),
                trace.context_tokens or None,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                trace.retrieved or None,
                [h.rfc for h in answer.used] or None,
                trace.topic_rfc,
                answer.text[:4000],
                answer.quote,
                error,
            ))
            row = cur.fetchone()
            conn.commit()
            if row:
                trace.log_id = row[0]
            return row[0] if row else None
    except Exception as exc:
        log.warning("could not record query: %s: %s", type(exc).__name__, exc)
        return None


def report(days: int = 30) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select count(*), count(*) filter (where answered),
                   count(*) filter (where route = 'refusal'),
                   count(*) filter (where grounded is false),
                   sum(llm_calls), sum(coalesce(prompt_tokens, 0)),
                   sum(coalesce(completion_tokens, 0))
              from query_log where at > now() - make_interval(days => %s)
        """, (days,))
        total, answered, refused, ungrounded, calls, pt, ct = cur.fetchone()

        cur.execute("""
            select route, count(*),
                   percentile_disc(0.5) within group (order by total_ms),
                   percentile_disc(0.95) within group (order by total_ms),
                   sum(llm_calls)
              from query_log where at > now() - make_interval(days => %s)
             group by route order by count(*) desc
        """, (days,))
        routes = [{"route": r, "n": n, "p50_ms": p50, "p95_ms": p95, "llm_calls": lc}
                  for r, n, p50, p95, lc in cur.fetchall()]

        cur.execute("""
            select question, route, total_ms, grounded
              from query_log
             where grounded is false or error is not null or route = 'refusal'
             order by at desc limit 10
        """)
        attention = [{"question": q, "route": r, "ms": ms, "grounded": g}
                     for q, r, ms, g in cur.fetchall()]

    return {
        "total": total or 0, "answered": answered or 0, "refused": refused or 0,
        "ungrounded": ungrounded or 0, "llm_calls": calls or 0,
        "prompt_tokens": pt or 0, "completion_tokens": ct or 0,
        "routes": routes, "attention": attention,
    }
