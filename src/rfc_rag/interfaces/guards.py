"""Input validation, rate limiting and caching for the HTTP interface.

The scarce resource is the model provider's free quota, so limits are layered:
per-client to stop one caller monopolising it, and global to stop the whole
service exhausting it in an afternoon.
"""

import hashlib
import json
import os
import re
import time
from collections import defaultdict, deque

from ..db import connect

MAX_QUESTION = int(os.getenv("MAX_QUESTION_CHARS", "500"))
MIN_QUESTION = 3
PER_MINUTE = int(os.getenv("RATE_PER_MINUTE", "6"))
# Must sit below the provider's own ceiling. Measured: Groq's free tier allows
# 30 requests/minute, and six clients at PER_MINUTE each would exceed that,
# turning provider 429s into 503s for everyone. The daily caps never bind
# first - 800/day is far under what 30/minute permits.
GLOBAL_PER_MINUTE = int(os.getenv("GLOBAL_PER_MINUTE", "25"))
PER_DAY = int(os.getenv("RATE_PER_DAY", "60"))
GLOBAL_PER_DAY = int(os.getenv("GLOBAL_PER_DAY", "800"))
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "168"))

# Bump when routing, prompts or answer shape change. Without it a question
# answered wrongly keeps serving that answer for CACHE_TTL_HOURS, outliving the
# fix. Cheap to bump; the cache refills in a day.
CACHE_VERSION = os.getenv("CACHE_VERSION", "2")

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE = re.compile(r"\s+")

_minute: dict[str, deque[float]] = defaultdict(deque)
_global_minute: deque[float] = deque()
_last_sweep = 0.0
SWEEP_EVERY = 60.0


class Rejected(Exception):
    def __init__(self, status: int, detail: str, retry_after: int | None = None):
        super().__init__(detail)
        self.status, self.detail, self.retry_after = status, detail, retry_after


def clean_question(raw: str) -> str:
    text = CONTROL.sub("", raw or "")
    text = WHITESPACE.sub(" ", text).strip()
    if len(text) < MIN_QUESTION:
        raise Rejected(400, "Question is empty or too short.")
    if len(text) > MAX_QUESTION:
        raise Rejected(413, f"Question is longer than {MAX_QUESTION} characters.")
    printable = sum(c.isprintable() or c == " " for c in text)
    if printable / len(text) < 0.9:
        raise Rejected(400, "Question contains too many non-text characters.")
    return text


def _sweep(now: float) -> None:
    """Drop windows with nothing left in them.

    One entry per client IP that never expired is a slow leak: 50,000 distinct
    callers retained ~39 MB and none of it was reachable again.
    """
    global _last_sweep
    if now - _last_sweep < SWEEP_EVERY:
        return
    _last_sweep = now
    for key in [k for k, v in _minute.items() if not v or now - v[-1] > 60]:
        del _minute[key]


def provider_calls_last_minute() -> int:
    """Model-calling requests across every worker, from the durable log.

    The in-process window only sees one worker. In the cloud there are
    several, and MCP tools run in the same process but could be scaled apart,
    so the ceiling that protects the provider has to be shared.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""select count(*) from query_log
                        where at > now() - interval '1 minute'
                          and not cached and llm_calls > 0""")
        return cur.fetchone()[0]


def check_provider_budget() -> None:
    """Cross-worker guard, checked only before work that calls the model."""
    if provider_calls_last_minute() >= GLOBAL_PER_MINUTE:
        raise Rejected(503, "This demo is at its shared per-minute limit. "
                            "Try again in a moment.", retry_after=30)


def check_global_burst() -> None:
    """Keep the whole service under the provider's per-minute ceiling."""
    now = time.time()
    while _global_minute and now - _global_minute[0] > 60:
        _global_minute.popleft()
    if len(_global_minute) >= GLOBAL_PER_MINUTE:
        raise Rejected(503, "This demo is at its shared per-minute limit. "
                            "Try again in a moment.",
                       retry_after=int(60 - (now - _global_minute[0])) + 1)
    _global_minute.append(now)


def check_burst(client: str) -> None:
    """In-memory, per-process. Stops a hot loop without touching the database."""
    now = time.time()
    _sweep(now)
    window = _minute[client]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= PER_MINUTE:
        raise Rejected(429, f"Rate limit: {PER_MINUTE} questions per minute.",
                       retry_after=int(60 - (now - window[0])) + 1)
    window.append(now)


def check_quota(client: str) -> None:
    """Durable, shared across restarts and instances. Protects the model quota."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            select count(*) filter (where client = %s), count(*)
              from query_log
             where at > now() - interval '1 day' and not cached
        """, (client,))
        mine, everyone = cur.fetchone()
    if mine >= PER_DAY:
        raise Rejected(429, f"Daily limit reached: {PER_DAY} questions per day.",
                       retry_after=3600)
    if everyone >= GLOBAL_PER_DAY:
        raise Rejected(503, "The shared daily quota for this demo is exhausted. "
                            "Try again tomorrow.", retry_after=3600)


def check_rate(client: str) -> None:
    """For work that will call the model."""
    check_burst(client)
    check_global_burst()
    check_provider_budget()
    check_quota(client)


# MCP tools are mostly SQL and local CPU, measured at 432 and 1015 req/s, so
# they get their own ceiling an order of magnitude higher. Only the tools that
# reach the provider pay the provider's price.
MCP_PER_MINUTE = int(os.getenv("MCP_PER_MINUTE", "120"))
_mcp_minute: dict[str, deque[float]] = defaultdict(deque)


def check_mcp(client: str, calls_model: bool = False) -> None:
    now = time.time()
    window = _mcp_minute[client]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= MCP_PER_MINUTE:
        raise Rejected(429, f"Rate limit: {MCP_PER_MINUTE} tool calls per minute.",
                       retry_after=int(60 - (now - window[0])) + 1)
    window.append(now)
    if len(_mcp_minute) > 10_000:
        for key in [k for k, v in _mcp_minute.items() if not v or now - v[-1] > 60]:
            del _mcp_minute[key]
    if calls_model:
        check_global_burst()
        check_provider_budget()
        check_quota(client)


def cache_key(question: str) -> str:
    seed = f"{CACHE_VERSION}:{question.lower().strip()}"
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def purge(before_version: str | None = None) -> int:
    """Drop cached answers, optionally only those from older code."""
    with connect() as conn, conn.cursor() as cur:
        if before_version is None:
            cur.execute("delete from answer_cache")
        else:
            cur.execute("delete from answer_cache where version is distinct from %s",
                        (before_version,))
        removed = cur.rowcount
        conn.commit()
    return removed


def cached(question: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            update answer_cache set hits = hits + 1
             where key = %s and at > now() - make_interval(hours => %s)
            returning payload
        """, (cache_key(question), CACHE_TTL_HOURS))
        row = cur.fetchone()
        conn.commit()
    return row[0] if row else None


def store(question: str, payload: dict) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            insert into answer_cache (key, question, payload, version)
            values (%s, %s, %s, %s)
            on conflict (key) do update set payload = excluded.payload,
                                            version = excluded.version, at = now()
        """, (cache_key(question), question, json.dumps(payload), CACHE_VERSION))
        conn.commit()
