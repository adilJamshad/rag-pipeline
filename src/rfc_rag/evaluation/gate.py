"""Fail a build when quality drops.

The baseline lives in the repository rather than the database, because CI
starts from an empty one and because a baseline that moves silently is not a
baseline. Updating it is a visible commit.
"""

import json
import sys
from pathlib import Path

BASELINE = Path("eval/baseline.json")

# Metrics where higher is better, with how far each may fall before it is a
# regression rather than noise. Retrieval is deterministic given the corpus, so
# its tolerance is tight; generation varies between runs, so its is not.
WATCHED = {
    "doc_r1": 0.05,
    "doc_r5": 0.05,
    "doc_r10": 0.05,
    "mrr": 0.03,
    "correct": 0.07,
    "grounded": 0.10,
    "cited_right": 0.10,
    "refusal_accuracy": 0.15,
}

# Lower is better here.
INVERTED = {"false_refusal_rate": 0.07}


def load() -> dict | None:
    if not BASELINE.exists():
        return None
    return json.loads(BASELINE.read_text())


def save(metrics: dict, note: str = "") -> None:
    payload = {k: metrics[k] for k in (*WATCHED, *INVERTED) if k in metrics}
    payload["_note"] = note
    payload["_n_questions"] = metrics.get("n_questions")
    BASELINE.parent.mkdir(exist_ok=True)
    BASELINE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def compare(metrics: dict, baseline: dict) -> list[str]:
    failures = []
    for key, tolerance in WATCHED.items():
        if key not in baseline or key not in metrics:
            continue
        before, now = float(baseline[key]), float(metrics[key])
        if now < before - tolerance:
            failures.append(f"{key}: {before:.3f} -> {now:.3f} "
                            f"(down {before - now:.3f}, tolerance {tolerance})")
    for key, tolerance in INVERTED.items():
        if key not in baseline or key not in metrics:
            continue
        before, now = float(baseline[key]), float(metrics[key])
        if now > before + tolerance:
            failures.append(f"{key}: {before:.3f} -> {now:.3f} "
                            f"(up {now - before:.3f}, tolerance {tolerance})")
    return failures


def report(metrics: dict, baseline: dict | None) -> int:
    if baseline is None:
        print("no baseline — run with --save-baseline to create one")
        return 0

    print(f"{'metric':<20} {'baseline':>9} {'now':>9} {'delta':>9}")
    for key in (*WATCHED, *INVERTED):
        if key not in baseline or key not in metrics:
            continue
        before, now = float(baseline[key]), float(metrics[key])
        print(f"  {key:<18} {before:>9.3f} {now:>9.3f} {now - before:>+9.3f}")

    failures = compare(metrics, baseline)
    if not failures:
        print("\nno regression")
        return 0
    print("\nREGRESSION:")
    for line in failures:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    from .run import main as run_eval

    save_mode = "--save-baseline" in sys.argv
    note = next((a for a in sys.argv[1:] if not a.startswith("--")), "")
    metrics = run_eval(label=note or None, return_metrics=True)

    if save_mode:
        save(metrics, note)
        print(f"\nbaseline written to {BASELINE}")
        raise SystemExit(0)
    raise SystemExit(report(metrics, load()))
