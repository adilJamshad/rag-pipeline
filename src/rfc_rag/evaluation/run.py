import json
import statistics as st
import time
from pathlib import Path
from typing import Callable

from ..clients import llm
from ..models import Hit, RetrievalScore
from ..services.answering import ask
from ..services.search import hybrid, keyword, semantic
from . import store

EVAL = Path("eval")


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (EVAL / f"{name}.jsonl").open()]


def _gold_rank(hits: list[Hit], rfc: int) -> int | None:
    for i, h in enumerate(hits, 1):
        if h.rfc == rfc:
            return i
    return None


def retrieval(name: str, retrieve: Callable[[str, int], list[Hit]],
              k: int = 10) -> tuple[RetrievalScore, dict[str, int | None]]:
    questions = load("answerable")
    ranks = {q["id"]: _gold_rank(retrieve(q["question"], k), q["rfc"]) for q in questions}
    values = list(ranks.values())
    n = len(values)
    at = lambda cut: sum(1 for r in values if r and r <= cut) / n
    score = RetrievalScore(name, n, at(1), at(5), at(10),
                           sum(1 / r for r in values if r) / n)
    return score, ranks


def answers(ranks: dict[str, int | None]) -> tuple[dict, list[dict]]:
    rows = load("answerable")
    negatives = load("unanswerable")
    per_question, tokens_in, tokens_out, calls = [], 0, 0, 0

    for q in rows:
        started = time.time()
        a = ask(q["question"])
        elapsed_ms = int((time.time() - started) * 1000)
        usage = llm.last_usage or {}
        tokens_in += usage.get("prompt_tokens") or 0
        tokens_out += usage.get("completion_tokens") or 0
        calls += a.trace.llm_calls
        answered = a.route != "refusal"
        per_question.append({
            "id": q["id"], "question": q["question"], "kind": "answerable",
            "gold_rank": ranks.get(q["id"]), "route": a.route,
            "correct": answered and q["expect"].lower() in a.text.lower(),
            "grounded": a.grounded if answered else None,
            "cited_right": answered and any(h.rfc == q["rfc"] for h in a.used),
            "total_ms": elapsed_ms,
        })

    for q in negatives:
        started = time.time()
        a = ask(q["question"])
        calls += a.trace.llm_calls
        per_question.append({
            "id": q["id"], "question": q["question"], "kind": "unanswerable",
            "gold_rank": None, "route": a.route,
            "correct": a.route == "refusal", "grounded": None, "cited_right": None,
            "total_ms": int((time.time() - started) * 1000),
        })

    pos = [p for p in per_question if p["kind"] == "answerable"]
    neg = [p for p in per_question if p["kind"] == "unanswerable"]
    answered = [p for p in pos if p["route"] != "refusal"]
    latencies = sorted(p["total_ms"] for p in pos)
    pct = lambda q: latencies[min(int(len(latencies) * q), len(latencies) - 1)] if latencies else 0

    metrics = {
        "n_questions": len(pos),
        "answer_rate": len(answered) / len(pos),
        "correct": sum(1 for p in answered if p["correct"]) / max(len(answered), 1),
        "grounded": sum(1 for p in answered if p["grounded"]) / max(len(answered), 1),
        "cited_right": sum(1 for p in answered if p["cited_right"]) / max(len(answered), 1),
        "false_refusal_rate": sum(1 for p in pos if p["route"] == "refusal") / len(pos),
        "refusal_accuracy": sum(1 for p in neg if p["correct"]) / max(len(neg), 1),
        "p50_ms": pct(0.5), "p95_ms": pct(0.95),
        "tokens_in": tokens_in, "tokens_out": tokens_out, "llm_calls": calls,
        "mean_ms": int(st.mean(latencies)) if latencies else 0,
        "n_unanswerable": len(neg),
    }
    return metrics, per_question


def main(label: str | None = None, save: bool = True,
         return_metrics: bool = False):
    print("=== retrieval (gold = the authoritative RFC, named from the domain) ===")
    scores = {}
    for name, fn in {
        "keyword (all)": lambda q, k: keyword(q, k, mode="all"),
        "semantic": lambda q, k: semantic(q, k, demote=0.05),
        "hybrid": lambda q, k: hybrid(q, k),
    }.items():
        score, ranks = retrieval(name, fn)
        scores[name] = (score, ranks)
        print(score)

    shipped, ranks = scores["semantic"]

    print()
    print("=== answers ===")
    metrics, per_question = answers(ranks)
    metrics |= {"doc_r1": shipped.doc1, "doc_r5": shipped.doc5,
                "doc_r10": shipped.doc10, "mrr": shipped.mrr,
                "retrieval_comparison": {n: vars(s) for n, (s, _) in scores.items()}}

    for key in ("answer_rate", "correct", "grounded", "cited_right",
                "false_refusal_rate", "refusal_accuracy"):
        print(f"  {key:<20} {metrics[key]:.2f}")
    print(f"  {'p50 / p95 ms':<20} {metrics['p50_ms']} / {metrics['p95_ms']}")
    print(f"  {'tokens in / out':<20} {metrics['tokens_in']} / {metrics['tokens_out']}")
    print(f"  {'llm calls':<20} {metrics['llm_calls']}")

    failures = [p for p in per_question if not p["correct"]]
    if failures:
        print()
        print("  failures:")
        for p in failures:
            why = "answered anyway" if p["kind"] == "unanswerable" else f"route={p['route']}"
            print(f"    {p['id']:<12} {why:<18} {p['question'][:48]}")

    if not save:
        return metrics if return_metrics else None

    run_id = store.save(metrics, per_question, label=label)
    print()
    print(f"saved as run {run_id}")

    past = store.history(limit=2)
    if len(past) > 1:
        prev = past[1]
        print(f"vs run {prev['id']} ({prev['git_sha']}):")
        for key, now in (("doc_r5", shipped.doc5), ("mrr", shipped.mrr),
                         ("correct", metrics["correct"]), ("grounded", metrics["grounded"])):
            before = float(prev[key]) if prev[key] is not None else 0.0
            delta = now - before
            arrow = "+" if delta > 0 else ""
            print(f"  {key:<10} {before:.3f} -> {now:.3f}  ({arrow}{delta:.3f})")
        broke = store.regressions(run_id, prev["id"])
        for r in broke:
            print(f"  REGRESSED  {r['question_id']}  {r['question'][:50]}")
    return metrics if return_metrics else run_id


if __name__ == "__main__":
    import sys
    main(label=" ".join(sys.argv[1:]) or None)
