import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .search import Hit, keyword

EVAL = Path("eval")


@dataclass
class Result:
    name: str
    n: int
    recall1: float
    recall5: float
    recall10: float
    mrr: float

    def __str__(self) -> str:
        return (f"{self.name:<24} n={self.n:<4} "
                f"R@1 {self.recall1:.2f}  R@5 {self.recall5:.2f}  "
                f"R@10 {self.recall10:.2f}  MRR {self.mrr:.3f}")


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (EVAL / f"{name}.jsonl").open()]


def _rank_of_gold(hits: list[Hit], gold: list[dict]) -> int | None:
    wanted = {(g["rfc"], g["number"]) for g in gold}
    for i, h in enumerate(hits, 1):
        if (h.rfc, h.number) in wanted:
            return i
    return None


def score(name: str, retrieve: Callable[[str, int], list[Hit]], k: int = 10) -> Result:
    questions = load("passages")
    ranks = [_rank_of_gold(retrieve(q["question"], k), q["gold"]) for q in questions]
    n = len(ranks)
    at = lambda cut: sum(1 for r in ranks if r and r <= cut) / n
    mrr = sum(1 / r for r in ranks if r) / n
    return Result(name, n, at(1), at(5), at(10), mrr)


def misses(retrieve: Callable[[str, int], list[Hit]], k: int = 10) -> list[tuple[str, list[dict], list[Hit]]]:
    out = []
    for q in load("passages"):
        hits = retrieve(q["question"], k)
        if _rank_of_gold(hits, q["gold"]) is None:
            out.append((q["question"], q["gold"], hits[:3]))
    return out


if __name__ == "__main__":
    print(score("keyword (any)", lambda q, k: keyword(q, k, mode="any")))
    print(score("keyword (all)", lambda q, k: keyword(q, k, mode="all")))
    print()
    print("misses (keyword any):")
    for question, gold, hits in misses(lambda q, k: keyword(q, k, mode="any")):
        want = ", ".join(f"RFC {g['rfc']} §{g['number']}" for g in gold)
        got = hits[0].cite if hits else "nothing"
        print(f"  {question[:52]:<54} want {want:<28} got {got[:40]}")
