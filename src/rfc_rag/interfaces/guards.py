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
PER_DAY = int(os.getenv("RATE_PER_DAY", "60"))
GLOBAL_PER_DAY = int(os.getenv("GLOBAL_PER_DAY", "800"))
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "168"))

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE = re.compile(r"\s+")

_minute: dict[str, deque[float]] = defaultdict(deque)


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


def check_burst(client: str) -> None:
    """In-memory, per-process. Stops a hot loop without touching the database."""
    now = time.time()
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
    check_burst(client)
    check_quota(client)


def cache_key(question: str) -> str:
    return hashlib.sha256(question.lower().strip().encode()).hexdigest()[:32]


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
            insert into answer_cache (key, question, payload) values (%s, %s, %s)
            on conflict (key) do update set payload = excluded.payload, at = now()
        """, (cache_key(question), question, json.dumps(payload)))
        conn.commit()
