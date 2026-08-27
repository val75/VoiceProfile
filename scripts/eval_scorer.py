"""Scorer for the LLM extraction eval.

Compares a golden `expected` block against an LLM `actual` extraction and returns
per-field-group scores plus an overall accuracy. Pure stdlib, no side effects, so
it is fully unit-testable offline (see tests/test_eval_scorer.py). The scoring
contract is documented in scripts/eval_data/golden_set.json's `_about`.
"""


def _duration_months(duration, unit):
    """Convert a (duration, unit) pair to whole months, or None if not year/month.

    Weeks don't map cleanly to months, so cross-unit equivalence is only defined
    within the year/month family (the common case: '1 year' == '12 months').
    """
    if unit == "years":
        return duration * 12
    if unit == "months":
        return duration
    return None


def _durations_equivalent(dur_a, unit_a, dur_b, unit_b):
    """True if the two pairs represent the same real length (exact, or year<->month)."""
    if dur_a == dur_b and unit_a == unit_b:
        return True
    ma, mb = _duration_months(dur_a, unit_a), _duration_months(dur_b, unit_b)
    return ma is not None and mb is not None and ma == mb


def _score_work(expected_entries, actual_entries):
    """Greedy-match expected work entries to actual by category, then score duration/unit.

    Duration and unit are scored only when present in the expected entry, so
    omitted-duration cases test whether the entry exists, not a specific length.
    """
    remaining = list(actual_entries)
    category_matched = 0
    duration_scored = duration_correct = 0
    duration_unit_scored = duration_unit_correct = 0

    for exp in expected_entries:
        match = None
        for act in remaining:
            if act.get("category") == exp.get("category"):
                match = act
                break
        if match is None:
            continue
        remaining.remove(match)
        category_matched += 1

        # A unit-equivalent pair (e.g. 12 months == 1 year) counts as correct on
        # BOTH duration and unit: same real length, both integer-persistable.
        pair_equiv = (
            "duration" in exp and "duration_unit" in exp
            and "duration" in match and "duration_unit" in match
            and _durations_equivalent(
                match["duration"], match["duration_unit"],
                exp["duration"], exp["duration_unit"],
            )
        )

        if "duration" in exp:
            duration_scored += 1
            if match.get("duration") == exp["duration"] or pair_equiv:
                duration_correct += 1
        if "duration_unit" in exp:
            duration_unit_scored += 1
            if match.get("duration_unit") == exp["duration_unit"] or pair_equiv:
                duration_unit_correct += 1

    return {
        "category_expected": len(expected_entries),
        "category_matched": category_matched,
        "missed_entries": len(expected_entries) - category_matched,
        "extra_entries": len(remaining),
        "duration_scored": duration_scored,
        "duration_correct": duration_correct,
        "duration_unit_scored": duration_unit_scored,
        "duration_unit_correct": duration_unit_correct,
    }


def _score_schedule(expected_sched, actual_sched):
    """Set-F1 on days; exact start/end on days present in both (when hours expected)."""
    exp_by_day = {e["day"]: e for e in expected_sched if "day" in e}
    act_by_day = {e["day"]: e for e in actual_sched if "day" in e}
    exp_days, act_days = set(exp_by_day), set(act_by_day)
    tp = len(exp_days & act_days)

    if not exp_days and not act_days:
        day_f1 = 1.0
    else:
        precision = tp / len(act_days) if act_days else 0.0
        recall = tp / len(exp_days) if exp_days else 0.0
        day_f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    hours_scored = hours_correct = 0
    for day in exp_days & act_days:
        exp = exp_by_day[day]
        if "start" in exp or "end" in exp:
            hours_scored += 1
            act = act_by_day[day]
            if act.get("start") == exp.get("start") and act.get("end") == exp.get("end"):
                hours_correct += 1

    return {
        "day_f1": day_f1,
        "hours_scored": hours_scored,
        "hours_correct": hours_correct,
    }


def score_case(expected, actual):
    """Score one extraction. Returns a dict of per-group scores plus `accuracy` in [0, 1]."""
    exp_av = expected.get("availability", {})
    act_av = actual.get("availability", {}) if isinstance(actual.get("availability"), dict) else {}

    work = _score_work(
        expected.get("work_experience", []),
        actual.get("work_experience", []) or [],
    )

    schedule = _score_schedule(exp_av.get("schedule", []), act_av.get("schedule", []) or [])

    shift = {"scored": 0, "correct": 0}
    if "shift_preference" in exp_av:
        shift["scored"] = 1
        shift["correct"] = int(act_av.get("shift_preference") == exp_av["shift_preference"])

    notes = {"scored": 0, "correct": 0}
    if "notes_contains" in exp_av:
        notes["scored"] = 1
        haystack = (act_av.get("notes") or "").lower()
        notes["correct"] = int(all(str(sub).lower() in haystack for sub in exp_av["notes_contains"]))

    # Overall accuracy: earned points over total scorable points. Each false-positive
    # work entry adds an unearned point, so a failed merge lowers the score.
    earned = (
        work["category_matched"]
        + work["duration_correct"]
        + work["duration_unit_correct"]
        + schedule["hours_correct"]
        + shift["correct"]
        + notes["correct"]
    )
    total = (
        work["category_expected"]
        + work["extra_entries"]
        + work["duration_scored"]
        + work["duration_unit_scored"]
        + schedule["hours_scored"]
        + shift["scored"]
        + notes["scored"]
    )
    if "schedule" in exp_av:
        earned += schedule["day_f1"]
        total += 1

    accuracy = earned / total if total else 1.0

    return {
        "work": work,
        "schedule": schedule,
        "shift": shift,
        "notes": notes,
        "accuracy": accuracy,
    }
