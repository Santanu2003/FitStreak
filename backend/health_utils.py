"""Population benchmarks + percentile lookups from health_activity_data.csv (1,000 people).
Purely descriptive/comparative — never a diagnosis or risk score."""
import bisect
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

with open(os.path.join(DATA_DIR, "health_benchmarks.json")) as f:
    _bench = json.load(f)

with open(os.path.join(DATA_DIR, "activity_comparison.json")) as f:
    _activity_comparison = json.load(f)



def _age_bracket(age):
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 65:
        return "55-64"
    return "65+"


def _percentile(sorted_values, value):
    """% of the population at or below `value`."""
    if not sorted_values:
        return None
    idx = bisect.bisect_right(sorted_values, value)
    return round(100 * idx / len(sorted_values), 1)


def _value_at_percentile(sorted_values, pct):
    """The value below which `pct`% of the (already sorted) population falls."""
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, round(pct / 100 * (len(sorted_values) - 1))))
    return round(sorted_values[idx], 1)


def compute_benchmark(age, daily_steps, sleep_hours, exercise_hours_per_week, bmi=None):
    bracket = _age_bracket(age)
    raw = _bench["raw_by_bracket"].get(bracket, {})
    bracket_row = next((b for b in _bench["benchmarks"] if b["Age_Bracket"] == bracket), None)
    brackets = _bench["benchmarks"]
    bracket_idx = next((i for i, b in enumerate(brackets) if b["Age_Bracket"] == bracket), None)

    your_percentiles = {
        "daily_steps": _percentile(raw.get("steps", []), daily_steps),
        "sleep_hours": _percentile(raw.get("sleep", []), sleep_hours),
        "exercise_hours_per_week": _percentile(raw.get("exercise_hrs", []), exercise_hours_per_week),
    }
    result = {
        "age_bracket": bracket,
        "age_bracket_index": bracket_idx,
        "sample_size_in_bracket": bracket_row["sample_size"] if bracket_row else 0,
        "bracket_averages": bracket_row,
        "your_percentiles": your_percentiles,
        # The value at the 75th percentile within the bracket — "what the most active
        # quarter of your age group looks like" — gives people something to aim for
        # beyond a single average number.
        "top_quartile_in_bracket": {
            "daily_steps": _value_at_percentile(raw.get("steps", []), 75),
            "sleep_hours": _value_at_percentile(raw.get("sleep", []), 75),
            "exercise_hours_per_week": _value_at_percentile(raw.get("exercise_hrs", []), 75),
        },
        "all_bracket_averages": brackets,
    }
    if bmi is not None and raw.get("bmi"):
        your_percentiles["bmi"] = _percentile(raw["bmi"], bmi)
        result["your_bmi"] = round(bmi, 1)
    return result


def get_activity_comparison():
    return _activity_comparison


def get_bracket_summary():
    return _bench["benchmarks"]


def weekly_exercise_benchmark_kcal(age=None):
    """Estimated weekly calorie burn of a 'typical active person': this age bracket's average
    exercise hours/week (from the 1,000-person health survey) times a real kcal/minute rate
    (from the 973-session gym tracker) - a reference line for the Leaderboard, not a target."""
    per_min = _bench.get("session_kcal_per_min", 12.0)
    if age is not None:
        bracket = _age_bracket(age)
        row = next((b for b in _bench["benchmarks"] if b["Age_Bracket"] == bracket), None)
    else:
        bracket, row = None, None
    if not row:
        hrs = sum(b["avg_exercise_hrs"] for b in _bench["benchmarks"]) / len(_bench["benchmarks"])
        bracket = bracket or "all ages"
    else:
        hrs = row["avg_exercise_hrs"]
    return {"age_bracket": bracket, "avg_exercise_hrs_per_week": round(hrs, 1),
            "kcal_per_min": per_min, "weekly_kcal": round(hrs * 60 * per_min)}


# ---------------------------------------------------- calorie estimation ----
# MET (metabolic equivalent) values — standard exercise-physiology reference
# values used to translate activity type + duration + body weight into an
# estimated calorie burn: kcal = MET * 3.5 * weight_kg / 200 * duration_min
_ACTIVITY_MET = {
    "cardio": 7.0,
    "hiit": 8.0,
    "strength": 6.0,
    "yoga": 3.0,
    "running": 9.8,
    "walking": 3.5,
    "swimming": 7.0,
    "cycling": 7.5,
    "dancing": 5.0,
    "other": 4.0,
}

# Mood is a light proxy for perceived exertion/intensity that day — someone
# logging "Tired"/"Stressed" typically trains a bit lighter than "Great".
_MOOD_INTENSITY = {
    "great": 1.08,
    "happy": 1.04,
    "okay": 1.0,
    "tired": 0.90,
    "stressed": 0.92,
}


def estimate_activity_calories(activity_type, duration_min, weight_kg, mood="Okay"):
    """Returns an estimated calorie burn for a logged activity, derived from
    a MET lookup for the activity type, session duration, the person's body
    weight, and a small mood-based intensity adjustment. Descriptive
    estimate only — not a substitute for a heart-rate-based measurement."""
    met = _ACTIVITY_MET.get((activity_type or "").strip().lower(), _ACTIVITY_MET["other"])
    intensity = _MOOD_INTENSITY.get((mood or "Okay").strip().lower(), 1.0)
    weight_kg = weight_kg or 70.0
    duration_min = max(0.0, duration_min or 0.0)
    calories = met * intensity * 3.5 * weight_kg / 200.0 * duration_min
    return round(calories, 1)
