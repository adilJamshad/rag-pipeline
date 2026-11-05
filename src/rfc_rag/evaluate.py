import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .answer import ask
from .search import Hit, hybrid, keyword, semantic

EVAL = Path("eval")


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (EVAL / f"{name}.jsonl").open()]


@dataclass
class Retrieval:
    name: str
    n: int
    doc1: float
    doc5: float
    doc10: float
    mrr: float

    def __str__(self) -> str:
        return (f"{self.name:<22} n={self.n:<4} doc@1 {self.doc1:.2f}  doc@5 {self.doc5:.2f}  "
                f"doc@10 {self.doc10:.2f}  MRR {self.mrr:.3f}")


def retrieval(name: str, retrieve: Callable[[str, int], list[Hit]], k: int = 10) -> Retrieval:
    questions = load("answerable")
    ranks = []
    for q in questions:
        rank = None
        for i, h in enumerate(retrieve(q["question"], k), 1):
            if h.rfc == q["rfc"]:
                rank = i
                break
        ranks.append(rank)
    n = len(ranks)
    at = lambda cut: sum(1 for r in ranks if r and r <= cut) / n
    return Retrieval(name, n, at(1), at(5), at(10), sum(1 / r for r in ranks if r) / n)


def answers() -> dict:
    rows = load("answerable")
    started = time.time()
    results = [(q, ask(q["question"])) for q in rows]

    answered = [(q, a) for q, a in results if a.route != "refusal"]
    correct = [(q, a) for q, a in answered if q["expect"].lower() in a.text.lower()]
    grounded = [a for _, a in answered if a.grounded]
    right_doc = [(q, a) for q, a in answered if any(h.rfc == q["rfc"] for h in a.used)]

    negatives = load("unanswerable")
    refused = [(q, ask(q["question"])) for q in negatives]
    correctly_refused = [q for q, a in refused if a.route == "refusal"]

    return {
        "n": len(rows),
        "answered": len(answered),
        "correct": len(correct),
        "grounded": len(grounded),
        "cited_right_doc": len(right_doc),
        "false_refusals": [q["question"] for q, a in results if a.route == "refusal"],
        "wrong": [(q["question"], q["expect"], a.text[:70]) for q, a in answered
                  if q["expect"].lower() not in a.text.lower()],
        "neg_n": len(negatives),
        "neg_refused": len(correctly_refused),
        "neg_answered": [q["question"] for q, a in refused if a.route != "refusal"],
        "seconds": time.time() - started,
    }


if __name__ == "__main__":
    print("=== retrieval (gold = the authoritative RFC, named from the domain) ===")
    for name, fn in {
        "keyword (all)": lambda q, k: keyword(q, k, mode="all"),
        "semantic": lambda q, k: semantic(q, k, demote=0.05),
        "hybrid": lambda q, k: hybrid(q, k),
    }.items():
        print(retrieval(name, fn))

    print()
    print("=== answers ===")
    r = answers()
    print(f"  answerable           {r['n']}")
    print(f"  answered             {r['answered']}/{r['n']}")
    print(f"  CORRECT              {r['correct']}/{r['answered']}")
    print(f"  grounded quote       {r['grounded']}/{r['answered']}")
    print(f"  cited the right RFC  {r['cited_right_doc']}/{r['answered']}")
    print(f"  false refusals       {len(r['false_refusals'])}")
    for q in r["false_refusals"]:
        print(f"      {q}")
    print(f"  wrong answers        {len(r['wrong'])}")
    for q, want, got in r["wrong"]:
        print(f"      {q[:46]:<48} want '{want}'  got: {got}")
    print()
    print(f"  unanswerable refused {r['neg_refused']}/{r['neg_n']}")
    for q in r["neg_answered"]:
        print(f"      answered anyway: {q}")
    print(f"  {r['seconds']:.0f}s")
