"""Throughput and what saturates first.

eval_run records sequential latency, which says nothing about behaviour under
concurrent load, and nothing about whether a slow number is our system or a
provider throttling us.
"""

import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from rfc_rag.clients import llm
from rfc_rag.clients.base import LLMError
from rfc_rag.services import supersession
from rfc_rag.services.search import semantic

QUESTIONS = [
    "what is the maximum length of a DNS label", "how does DNSSEC work",
    "what is DNS over HTTPS", "how are negative answers cached",
    "what is a glue record", "what is an AXFR zone transfer",
    "how do wildcards work in DNS", "what does the TTL field control",
]


def run(label, work, n, concurrency):
    latencies, errors = [], []

    def one(i):
        start = time.perf_counter()
        try:
            work(i)
        except Exception as exc:
            errors.append(type(exc).__name__)
        latencies.append((time.perf_counter() - start) * 1000)

    start = time.perf_counter()
    with ThreadPoolExecutor(concurrency) as pool:
        list(pool.map(one, range(n)))
    wall = time.perf_counter() - start

    ordered = sorted(latencies)
    pick = lambda q: ordered[min(int(len(ordered) * q), len(ordered) - 1)]
    print(f"  {label:<26} c={concurrency:<3} {n/wall:>6.1f} req/s  "
          f"p50 {pick(0.5):>7.0f}ms  p95 {pick(0.95):>7.0f}ms  "
          f"errors {len(errors)}"
          + (f" {set(errors)}" if errors else ""))


def main() -> None:
    print("=== retrieval only: no provider involved ===")
    for c in (1, 4, 8, 16):
        run("vector search", lambda i: semantic(QUESTIONS[i % len(QUESTIONS)], 6, demote=0.05),
            n=48, concurrency=c)

    print("\n=== facts route: pure SQL ===")
    for c in (1, 8, 16):
        run("supersession lookup", lambda i: supersession.lookup(1034 + (i % 2)),
            n=96, concurrency=c)

    print("\n=== embedding: in-process, CPU bound ===")
    for c in (1, 4, 8):
        run("embed one question", lambda i: llm.embed([QUESTIONS[i % len(QUESTIONS)]]),
            n=48, concurrency=c)

    if "--provider" in sys.argv:
        print("\n=== provider: the free tier is the ceiling ===")
        for c in (1, 4):
            run("chat completion", lambda i: llm.complete("Reply with: ok", max_tokens=60),
                n=12, concurrency=c)


if __name__ == "__main__":
    main()
