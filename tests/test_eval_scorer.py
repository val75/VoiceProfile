"""Tests for the eval scorer (scripts/eval_scorer.py).

The scorer compares a golden `expected` block against an LLM `actual` extraction
and returns per-field-group scores plus the diffs behind them. These tests pin the
scoring contract described in scripts/eval_data/golden_set.json's `_about`.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from eval_scorer import score_case  # noqa: E402


# --- work_experience: greedy match by category, then duration/unit exact ---

def test_perfect_work_experience_scores_full():
    expected = {"work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}]}
    actual = {"work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}]}

    r = score_case(expected, actual)

    assert r["work"]["category_matched"] == 1
    assert r["work"]["category_expected"] == 1
    assert r["work"]["duration_correct"] == 1
    assert r["work"]["duration_unit_correct"] == 1
    assert r["work"]["extra_entries"] == 0
    assert r["work"]["missed_entries"] == 0


def test_wrong_category_is_a_miss_not_a_match():
    expected = {"work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}]}
    actual = {"work_experience": [{"category": "warehouse", "duration": 2, "duration_unit": "years"}]}

    r = score_case(expected, actual)

    assert r["work"]["category_matched"] == 0
    assert r["work"]["missed_entries"] == 1
    assert r["work"]["extra_entries"] == 1
    # duration is only scored on matched pairs; nothing matched here
    assert r["work"]["duration_scored"] == 0


def test_matched_category_wrong_duration_scores_partial():
    expected = {"work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}]}
    actual = {"work_experience": [{"category": "driving", "duration": 3, "duration_unit": "years"}]}

    r = score_case(expected, actual)

    assert r["work"]["category_matched"] == 1
    assert r["work"]["duration_correct"] == 0
    assert r["work"]["duration_unit_correct"] == 1


def test_equivalent_duration_different_unit_scores_full():
    # 12 months == 1 year: same real length, both integer-persistable -> full credit.
    expected = {"work_experience": [{"category": "food_service", "duration": 1, "duration_unit": "years"}]}
    actual = {"work_experience": [{"category": "food_service", "duration": 12, "duration_unit": "months"}]}

    r = score_case(expected, actual)

    assert r["work"]["duration_correct"] == 1
    assert r["work"]["duration_unit_correct"] == 1


def test_equivalent_duration_two_years_as_24_months():
    expected = {"work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}]}
    actual = {"work_experience": [{"category": "driving", "duration": 24, "duration_unit": "months"}]}

    r = score_case(expected, actual)

    assert r["work"]["duration_correct"] == 1
    assert r["work"]["duration_unit_correct"] == 1


def test_non_equivalent_cross_unit_still_wrong():
    # 1 year != 6 months: different real length -> not equivalent.
    expected = {"work_experience": [{"category": "cleaning", "duration": 1, "duration_unit": "years"}]}
    actual = {"work_experience": [{"category": "cleaning", "duration": 6, "duration_unit": "months"}]}

    r = score_case(expected, actual)

    assert r["work"]["duration_correct"] == 0
    assert r["work"]["duration_unit_correct"] == 0


def test_omitted_duration_in_expected_is_not_scored():
    # en_no_duration case: only the presence of the entry matters.
    expected = {"work_experience": [{"category": "warehouse"}]}
    actual = {"work_experience": [{"category": "warehouse", "duration": 1, "duration_unit": "years"}]}

    r = score_case(expected, actual)

    assert r["work"]["category_matched"] == 1
    assert r["work"]["duration_scored"] == 0  # expected omitted duration -> not scored


def test_failed_merge_produces_extra_entry():
    # Model emits the same category twice instead of merging -> one match + one false positive.
    expected = {"work_experience": [{"category": "driving", "duration": 3, "duration_unit": "years"}]}
    actual = {"work_experience": [
        {"category": "driving", "duration": 3, "duration_unit": "years"},
        {"category": "driving", "duration": 3, "duration_unit": "years"},
    ]}

    r = score_case(expected, actual)

    assert r["work"]["category_matched"] == 1
    assert r["work"]["extra_entries"] == 1


# --- availability.schedule: set F1 on days, exact start/end on matched days ---

def test_schedule_days_perfect_f1():
    expected = {"availability": {"schedule": [
        {"day": "friday", "start": "09:00", "end": "17:00"},
        {"day": "saturday", "start": "09:00", "end": "17:00"},
    ]}}
    actual = dict(expected)

    r = score_case(expected, actual)

    assert r["schedule"]["day_f1"] == 1.0
    assert r["schedule"]["hours_correct"] == 2
    assert r["schedule"]["hours_scored"] == 2


def test_schedule_missing_day_lowers_recall():
    expected = {"availability": {"schedule": [
        {"day": "monday", "start": "08:00", "end": "16:00"},
        {"day": "tuesday", "start": "08:00", "end": "16:00"},
    ]}}
    actual = {"availability": {"schedule": [
        {"day": "monday", "start": "08:00", "end": "16:00"},
    ]}}

    r = score_case(expected, actual)

    # recall 1/2, precision 1/1 -> F1 = 2*0.5*1/(0.5+1) = 0.666...
    assert round(r["schedule"]["day_f1"], 3) == 0.667


def test_schedule_wrong_hours_on_matched_day():
    expected = {"availability": {"schedule": [{"day": "saturday", "start": "10:00", "end": "18:00"}]}}
    actual = {"availability": {"schedule": [{"day": "saturday", "start": "10:00", "end": "17:00"}]}}

    r = score_case(expected, actual)

    assert r["schedule"]["day_f1"] == 1.0
    assert r["schedule"]["hours_correct"] == 0
    assert r["schedule"]["hours_scored"] == 1


def test_day_without_hours_is_not_hour_scored():
    # en_year_and_half weekend case: days present, no start/end expected.
    expected = {"availability": {"schedule": [{"day": "saturday"}, {"day": "sunday"}]}}
    actual = {"availability": {"schedule": [{"day": "saturday"}, {"day": "sunday"}]}}

    r = score_case(expected, actual)

    assert r["schedule"]["day_f1"] == 1.0
    assert r["schedule"]["hours_scored"] == 0


# --- shift_preference: exact match when expected ---

def test_shift_preference_exact_match():
    expected = {"availability": {"shift_preference": "morning"}}
    actual = {"availability": {"shift_preference": "morning"}}

    r = score_case(expected, actual)

    assert r["shift"]["scored"] == 1
    assert r["shift"]["correct"] == 1


def test_shift_preference_wrong():
    expected = {"availability": {"shift_preference": "night"}}
    actual = {"availability": {"shift_preference": "morning"}}

    r = score_case(expected, actual)

    assert r["shift"]["scored"] == 1
    assert r["shift"]["correct"] == 0


# --- day-less hours: notes_contains substrings ---

def test_notes_contains_all_substrings_present():
    expected = {"availability": {"notes_contains": ["9", "5"]}}
    actual = {"availability": {"notes": "available 9 in the morning to 5 in the afternoon"}}

    r = score_case(expected, actual)

    assert r["notes"]["scored"] == 1
    assert r["notes"]["correct"] == 1


def test_notes_missing_substring_fails():
    expected = {"availability": {"notes_contains": ["10", "6"]}}
    actual = {"availability": {"notes": "available from 10 onwards"}}

    r = score_case(expected, actual)

    assert r["notes"]["scored"] == 1
    assert r["notes"]["correct"] == 0


# --- overall accuracy + sanity check that a wrong extraction is caught ---

def test_overall_accuracy_is_1_for_perfect_extraction():
    expected = {
        "work_experience": [{"category": "driving", "duration": 2, "duration_unit": "years"}],
        "availability": {"schedule": [{"day": "monday", "start": "08:00", "end": "16:00"}]},
    }
    actual = expected

    r = score_case(expected, actual)

    assert r["accuracy"] == 1.0


def test_uber_painting_failure_is_caught():
    # The known failure: model collapses two jobs into one / drops the painting entry.
    expected = {"work_experience": [
        {"category": "driving", "duration": 2, "duration_unit": "years"},
        {"category": "construction", "duration": 1, "duration_unit": "years"},
    ], "availability": {"schedule": [], "notes_contains": ["9", "5"]}}
    actual = {"work_experience": [
        {"category": "driving", "duration": 2, "duration_unit": "years"},
    ], "availability": {"notes": "9 to 5"}}

    r = score_case(expected, actual)

    assert r["work"]["missed_entries"] == 1  # painting dropped
    assert r["accuracy"] < 1.0  # scorer flags the failure
