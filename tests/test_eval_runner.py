"""Tests for the eval runner core (scripts/eval_models.py).

The runner's aggregation/leaderboard/report logic is separated from the CLI and
the real LLM call via an injected `extract_fn`, so it is fully testable offline.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from eval_models import run_eval, leaderboard, format_report  # noqa: E402


CASE = {
    "id": "en_case",
    "language": "en",
    "transcripts": {"story": "I drove Uber for two years.", "availability": "mornings"},
    "expected": {
        "work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}],
        "availability": {"schedule": [], "shift_preference": "morning"},
    },
}

PERFECT_ACTUAL = {
    "work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}],
    "availability": {"schedule": [], "shift_preference": "morning"},
}


def test_run_eval_perfect_model_scores_1():
    def perfect(transcripts, model):
        return dict(PERFECT_ACTUAL)

    res = run_eval([CASE], ["m1"], perfect, runs=2)

    assert res["m1"]["accuracy_mean"] == 1.0
    assert res["m1"]["failures"] == 0
    assert res["m1"]["runs"] == 2


def test_run_eval_counts_failures_and_scores_zero():
    from services.nlp_service import ExtractionError

    def boom(transcripts, model):
        raise ExtractionError("unparseable")

    res = run_eval([CASE], ["m1"], boom, runs=1)

    assert res["m1"]["failures"] == 1
    assert res["m1"]["accuracy_mean"] == 0.0


def test_run_eval_averages_accuracy_across_cases():
    case2 = dict(CASE, id="en_case2")

    def half(transcripts, model):
        # Right category, wrong shift -> partial accuracy < 1 on every case.
        return {
            "work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}],
            "availability": {"schedule": [], "shift_preference": "night"},
        }

    res = run_eval([CASE, case2], ["m1"], half, runs=1)

    assert 0.0 < res["m1"]["accuracy_mean"] < 1.0


def test_leaderboard_orders_by_accuracy_desc():
    results = {
        "weak": {"accuracy_mean": 0.30, "latency_mean_ms": 100, "failures": 2, "runs": 1},
        "strong": {"accuracy_mean": 0.95, "latency_mean_ms": 400, "failures": 0, "runs": 1},
    }

    lb = leaderboard(results)

    assert [model for model, _ in lb] == ["strong", "weak"]


def test_format_report_is_markdown_with_models_and_leaderboard():
    def perfect(transcripts, model):
        return dict(PERFECT_ACTUAL)

    res = run_eval([CASE], ["m1"], perfect, runs=1)
    md = format_report("prod", res, [CASE])

    assert md.startswith("#")
    assert "Leaderboard" in md
    assert "m1" in md
    assert "prod" in md
