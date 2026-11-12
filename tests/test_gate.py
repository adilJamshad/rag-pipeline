import json

import pytest

from rfc_rag.evaluation import gate

BASE = {"doc_r5": 0.733, "doc_r10": 0.833, "mrr": 0.441, "correct": 0.966,
        "grounded": 0.897, "cited_right": 0.655, "false_refusal_rate": 0.033,
        "refusal_accuracy": 0.700}


def test_identical_metrics_pass():
    assert gate.compare(dict(BASE), BASE) == []


def test_improvements_pass():
    better = {**BASE, "mrr": 0.600, "grounded": 1.0, "false_refusal_rate": 0.0}
    assert gate.compare(better, BASE) == []


def test_noise_within_tolerance_passes():
    assert gate.compare({**BASE, "mrr": 0.441 - 0.02}, BASE) == []


def test_a_real_drop_fails():
    failures = gate.compare({**BASE, "mrr": 0.30}, BASE)
    assert len(failures) == 1
    assert "mrr" in failures[0] and "tolerance" in failures[0]


def test_rising_false_refusals_fail():
    """Inverted metric: refusing everything must not look like success."""
    failures = gate.compare({**BASE, "false_refusal_rate": 0.40}, BASE)
    assert failures and "false_refusal_rate" in failures[0]


def test_refusing_everything_is_caught_despite_perfect_refusal_accuracy():
    gamed = {**BASE, "refusal_accuracy": 1.0, "false_refusal_rate": 0.50, "correct": 0.5}
    failures = gate.compare(gamed, BASE)
    assert any("false_refusal_rate" in f for f in failures)
    assert any("correct" in f for f in failures)


def test_missing_metrics_are_skipped_not_failed():
    assert gate.compare({"mrr": 0.441}, BASE) == []
    assert gate.compare(BASE, {"mrr": 0.441}) == []


def test_no_baseline_is_not_a_failure(capsys):
    assert gate.report(BASE, None) == 0
    assert "no baseline" in capsys.readouterr().out


def test_report_exit_codes(capsys):
    assert gate.report(dict(BASE), BASE) == 0
    assert gate.report({**BASE, "doc_r5": 0.1}, BASE) == 1
    assert "REGRESSION" in capsys.readouterr().out


def test_the_committed_baseline_is_valid():
    data = gate.load()
    assert data is not None, "eval/baseline.json is missing"
    for key in ("doc_r5", "mrr", "grounded", "correct"):
        assert 0.0 <= float(data[key]) <= 1.0


def test_save_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "BASELINE", tmp_path / "baseline.json")
    gate.save({**BASE, "n_questions": 30}, "a note")
    written = json.loads((tmp_path / "baseline.json").read_text())
    assert written["_note"] == "a note"
    assert written["mrr"] == pytest.approx(0.441)
