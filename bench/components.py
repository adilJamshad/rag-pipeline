"""Where a request's time actually goes, measured per stage.

The eval records end-to-end latency only, so a regression there says something
got slower without saying what. These are the stages, timed in isolation.
"""

import statistics as st
import time

from rfc_rag import corpus
from rfc_rag.clients import llm
from rfc_rag.db import connect
from rfc_rag.services import stages, supersession
from rfc_rag.services.search import keyword, semantic

QUESTIONS = [
    "what is the maximum length of a DNS label",
    "how does DNSSEC work",
    "what is DNS over HTTPS",
    "how are negative answers cached",
    "what is a glue record",
]


def timed(fn, runs: int = 5):
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return st.median(samples), max(samples)


def main() -> None:
    corpus.reset_cache()
    rows = []

    rows.append(("embed one question (local)",
                 *timed(lambda: llm.embed([QUESTIONS[0]]))))
    rows.append(("corpus.check (cold)",
                 *timed(lambda: (corpus.reset_cache(), corpus.check()), runs=3)))
    rows.append(("corpus.check (warm)", *timed(corpus.check, runs=50)))
    rows.append(("vector search, k=6",
                 *timed(lambda: semantic(QUESTIONS[0], 6, demote=0.05))))
    rows.append(("keyword search, k=6",
                 *timed(lambda: keyword(QUESTIONS[0], 6, mode="all"))))
    rows.append(("supersession lookup",
                 *timed(lambda: supersession.lookup(1035))))
    rows.append(("current_for chain",
                 *timed(lambda: supersession.lookup(2065))))
    rows.append(("recent_changes", *timed(supersession.recent_changes)))
    rows.append(("analyse + plan",
                 *timed(lambda: stages.plan(stages.analyse(QUESTIONS[0])), runs=200)))

    def raw_vector_only():
        vector = str(llm.embed([QUESTIONS[0]])[0])
        with connect() as conn, conn.cursor() as cur:
            cur.execute("""select id from section where embedding is not null
                            order by embedding <=> %s::vector limit 6""", (vector,))
            cur.fetchall()
    rows.append(("  of which: db round trip", *timed(raw_vector_only)))

    print(f"{'stage':<30} {'median':>9} {'worst':>9}")
    for name, median, worst in rows:
        print(f"{name:<30} {median:>7.1f}ms {worst:>7.1f}ms")

    print()
    start = time.perf_counter()
    answer = None
    from rfc_rag.services.answering import ask
    answer = ask(QUESTIONS[0])
    total = (time.perf_counter() - start) * 1000
    print(f"full request ({answer.route}): {total:.0f}ms")
    for stage, seconds in answer.trace.timings.items():
        print(f"  {stage:<22} {seconds * 1000:>7.0f}ms")


if __name__ == "__main__":
    main()
