"""Loads trained models + static datasets, and exposes prediction/lookup helpers."""
import json
import os
import joblib
import numpy as np
import pandas as pd
from config import ACTIVITY_TYPES, EXPERIENCE_LABELS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ML_DIR = os.path.join(BASE_DIR, "ml")

# ---------- Load once at import time ----------
_calorie_bundle = joblib.load(os.path.join(ML_DIR, "calorie_model.pkl"))
_calorie_model = _calorie_bundle["model"]
_calorie_encoders = _calorie_bundle["encoders"]
_calorie_features = _calorie_bundle["feature_cols"]

with open(os.path.join(DATA_DIR, "exercises.json")) as f:
    _exercises = json.load(f)

with open(os.path.join(DATA_DIR, "workout_cohorts.json")) as f:
    _cohorts = json.load(f)

with open(os.path.join(DATA_DIR, "student_insights.json")) as f:
    _student_insights = json.load(f)

# The calorie model is trained on all of these (see scripts/train_models.py): the 4 types in
# the gym-session dataset plus Running/Walking/Swimming/Cycling/Dancing/Other, whose relative
# calorie intensity comes from the 687,701-session activity dataset.
ACTIVITY_TYPES = list(_calorie_bundle.get("trained_types") or ACTIVITY_TYPES)
WORKOUT_TYPES = ACTIVITY_TYPES
_TYPE_FACTORS = _calorie_bundle.get("type_factors", {})
MODEL_METRICS = _calorie_bundle.get("metrics", {})
MODEL_METADATA = {
    "algorithm": type(_calorie_model).__name__,
    "training_rows": MODEL_METRICS.get("real_sessions"),
    "metrics": MODEL_METRICS,
    "trained_types": ACTIVITY_TYPES,
    "feature_count": len(_calorie_features),
    "features": list(_calorie_features),
}
BODY_PARTS = sorted({e["BodyPart"] for e in _exercises})
EQUIPMENT_TYPES = sorted({e["Equipment"] for e in _exercises})
LEVELS = [EXPERIENCE_LABELS[i] for i in (1, 2, 3)]


def _bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


def estimate_body_fat_percentage(age, gender, bmi):
    """Deurenberg et al. (1991) formula — BF% = 1.20×BMI + 0.23×age − 10.8×sex − 5.4,
    sex=1 for male/0 for female. Used so the predictor never has to ask someone for a
    body-fat number they'd otherwise have to guess or measure with calipers."""
    sex = 1.0 if (gender or "").lower().startswith("m") else (
        0.0 if (gender or "").lower().startswith("f") else 0.5)
    bf = 1.20 * bmi + 0.23 * age - 10.8 * sex - 5.4
    return round(max(3.0, min(60.0, bf)), 1)


def predict_calories(payload):
    """payload keys: age, gender, weight_kg, height_cm, workout_type, duration_min,
    avg_bpm, max_bpm, resting_bpm, frequency, experience_level.
    fat_percentage is not a client input - it's estimated here (see
    estimate_body_fat_percentage) from age/gender/BMI so nobody has to know their own
    body-fat number to use the predictor. Every workout type is scored as itself; the
    model was trained on all of them."""
    height_m = payload["height_cm"] / 100.0
    bmi = round(payload["weight_kg"] / (height_m ** 2), 1)
    fat_percentage = estimate_body_fat_percentage(payload["age"], payload["gender"], bmi)

    workout_type = payload["workout_type"] if payload["workout_type"] in ACTIVITY_TYPES else "Other"
    gender_enc = _calorie_encoders["Gender"].transform([payload["gender"]])[0] \
        if payload["gender"] in _calorie_encoders["Gender"].classes_ else 0
    workout_enc = _calorie_encoders["Workout_Type"].transform([workout_type])[0]
    factor = float(_TYPE_FACTORS.get(workout_type, 1.0))

    row = {
        "Age": payload["age"],
        "Gender": gender_enc,
        "Weight (kg)": payload["weight_kg"],
        "Height (m)": height_m,
        "Max_BPM": payload["max_bpm"],
        "Avg_BPM": payload["avg_bpm"],
        "Resting_BPM": payload["resting_bpm"],
        "Session_Duration (hours)": payload["duration_min"] / 60.0,
        "Workout_Type": workout_enc,
        "Type_Intensity": factor,
        "Fat_Percentage": fat_percentage,
        "Workout_Frequency (days/week)": payload["frequency"],
        "Experience_Level": payload["experience_level"],
        "BMI": bmi,
    }
    X = pd.DataFrame([row])[_calorie_features]
    pred = float(_calorie_model.predict(X)[0])
    return {
        "predicted_calories": round(pred, 1),
        "bmi": bmi,
        "bmi_category": _bmi_category(bmi),
        "estimated_fat_percentage": fat_percentage,
        "model_workout_type": workout_type,     # always the type the person picked
        "type_intensity": round(factor, 2),     # kcal/min relative to the average activity
        "trained_types": ACTIVITY_TYPES,
    }


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Order the other workout types are rotated in after the one the person picked. It alternates
# hard / easy and changes modality day to day, and it covers every type ("Other" is left out
# because it has no session of its own to prescribe).
_COMPANION_ORDER = ["Strength", "Running", "Yoga", "Cycling", "HIIT", "Swimming",
                    "Dancing", "Walking", "Cardio"]

# Longest sensible session for the hardest types, by experience level (1-3).
_DURATION_CAPS = {"HIIT": {1: 25, 2: 35, 3: 45}, "Running": {1: 30, 2: 45, 3: 60},
                  "Strength": {1: 45, 2: 60, 3: 75}}

# Sessions for the types that have no matching exercise in the gym library.
_SESSION_TEMPLATES = {
    "Running": {
        1: [("Brisk 5-min walk warm-up", "Legs"), ("Run 2 min / walk 1 min, repeat", "Cardio"),
            ("Cool-down walk + calf stretch", "Calves")],
        2: [("Easy 5-min jog warm-up", "Legs"), ("Steady run at conversational pace", "Cardio"),
            ("Cool-down walk + hamstring stretch", "Hamstrings")],
        3: [("Easy jog + 4 strides", "Legs"), ("Tempo run, comfortably hard", "Cardio"),
            ("Cool-down jog + hip mobility", "Glutes")],
    },
    "Walking": {
        1: [("Easy-pace walk", "Legs"), ("Add 5 brisk minutes in the middle", "Cardio")],
        2: [("Brisk walk, arms swinging", "Cardio"), ("Hill or stair section", "Quadriceps")],
        3: [("Power walk with hills", "Cardio"), ("Weighted-vest or backpack finish", "Glutes")],
    },
    "Swimming": {
        1: [("Easy laps, rest at each wall", "Full body"), ("Kickboard legs", "Quadriceps")],
        2: [("Steady freestyle laps", "Full body"), ("Pull-buoy arm set", "Lats")],
        3: [("Freestyle intervals", "Full body"), ("Mixed-stroke cool-down", "Shoulders")],
    },
    "Cycling": {
        1: [("Easy spin, flat route", "Quadriceps"), ("Cadence drills", "Calves")],
        2: [("Steady endurance ride", "Quadriceps"), ("Short hill efforts", "Glutes")],
        3: [("Threshold intervals", "Quadriceps"), ("Easy spin cool-down", "Calves")],
    },
    "Dancing": {
        1: [("Warm-up groove", "Full body"), ("Follow-along dance video", "Cardio")],
        2: [("Full-song dance blocks", "Full body"), ("Freestyle finisher", "Cardio")],
        3: [("High-energy dance cardio", "Full body"), ("Choreography practice", "Cardio")],
    },
    "Other": {
        1: [("Your chosen activity, easy effort", "Full body")],
        2: [("Your chosen activity, steady effort", "Full body")],
        3: [("Your chosen activity, hard effort", "Full body")],
    },
}

# Which body parts each successive Strength day works, so a week isn't three chest days.
_STRENGTH_FOCUS = [["Chest", "Shoulders", "Triceps"], ["Quadriceps", "Hamstrings", "Glutes"],
                   ["Lats", "Middle Back", "Biceps"], ["Abdominals", "Lower Back", "Calves"]]


def _unique_by_rating(items):
    seen, out = set(), []
    for e in sorted(items, key=lambda e: (-e["Rating"], e["Title"])):
        if e["Title"] not in seen:
            seen.add(e["Title"])
            out.append(e)
    return out


def _library(types, level_name):
    """Exercises of the given library Types, preferring the person's level (falling back to
    all levels when a category has none at that level, e.g. Expert stretching)."""
    same_type = [e for e in _exercises if e["Type"] in types]
    at_level = [e for e in same_type if e["Level"] == level_name]
    return _unique_by_rating(at_level or same_type)


def _pick_session(w_type, level, level_name, used, strength_day):
    """Concrete exercises for one training day, never repeating one already used this week."""
    def take(pool, n, key=None):
        chosen = []
        for e in pool:
            if e["Title"] in used or (key and any(c["BodyPart"] == e["BodyPart"] for c in chosen)):
                continue
            chosen.append(e)
            used.add(e["Title"])
            if len(chosen) == n:
                break
        return [{"Title": e["Title"], "BodyPart": e["BodyPart"]} for e in chosen]

    if w_type == "Strength":
        pool = _library({"Strength", "Powerlifting", "Olympic Weightlifting"}, level_name)
        out = []
        for part in _STRENGTH_FOCUS[strength_day % len(_STRENGTH_FOCUS)]:
            out += take([e for e in pool if e["BodyPart"] == part], 1)
        return out
    if w_type == "HIIT":
        return take(_library({"Plyometrics"}, level_name), 3, key=True)
    if w_type == "Cardio":
        return take(_library({"Cardio"}, level_name), 3, key=True)
    if w_type == "Yoga":
        return take(_library({"Stretching"}, level_name), 3, key=True)
    template = _SESSION_TEMPLATES.get(w_type, _SESSION_TEMPLATES["Other"])[level]
    return [{"Title": t, "BodyPart": b} for t, b in template]


def build_weekly_plan(experience_level, frequency, duration_min, primary_workout_type,
                      kcal_for=None):
    """A 7-day schedule: `frequency` training days spread evenly across the week. Days rotate
    through the workout types - the one the person picked first, then the others in
    _COMPANION_ORDER - so every type can appear (which ones depends on how many days a week).
    Each training day gets exercises that fit its type, with no repeats across the week, a
    duration suited to the type and level, and (when `kcal_for(type, minutes)` is given) an
    estimated calorie burn from the trained model. Rest days fill the remaining slots."""
    n_days = max(1, min(7, int((frequency or 3) + 0.5)))
    step = 7 / n_days
    train_days = sorted({int(i * step + 0.5) % 7 for i in range(n_days)})
    while len(train_days) < n_days:
        for d in range(7):
            if d not in train_days:
                train_days.append(d)
                break
    train_days = sorted(train_days[:n_days])

    level = min(max(int(experience_level or 1), 1), 3)
    level_name = LEVELS[level - 1]
    primary = primary_workout_type if primary_workout_type in ACTIVITY_TYPES else "Cardio"
    rotation = [primary] + [t for t in _COMPANION_ORDER if t != primary]

    plan, used, strength_days = [], set(), 0
    for day_idx in range(7):
        if day_idx not in train_days:
            plan.append({"day": _DAY_NAMES[day_idx], "type": "Rest", "duration_min": 0,
                         "exercises": [], "est_kcal": 0})
            continue
        w_type = rotation[train_days.index(day_idx) % len(rotation)]
        minutes = int(min(duration_min, _DURATION_CAPS.get(w_type, {}).get(level, duration_min)))
        exercises = _pick_session(w_type, level, level_name, used, strength_days)
        if w_type == "Strength":
            strength_days += 1
        plan.append({
            "day": _DAY_NAMES[day_idx], "type": w_type, "duration_min": minutes,
            "exercises": exercises,
            "est_kcal": round(kcal_for(w_type, minutes)) if kcal_for else None,
        })
    return plan


def recommend_workout(bmi, experience_level, workout_type=None, frequency=None,
                      duration_min=None, body=None):
    """`frequency` / `duration_min` (what the person typed in the predictor) override the
    cohort averages when given. `body` (age, gender, weight_kg, height_cm, avg_bpm, max_bpm,
    resting_bpm) lets every training day carry a model-estimated calorie burn."""
    category = _bmi_category(bmi)
    match = [c for c in _cohorts
             if c["BMI_Category"] == category and c["Experience_Level"] == experience_level]
    cohort = match[0] if match else None

    primary_type = workout_type or (cohort["common_workout"] if cohort else "Cardio")
    frequency = frequency or (cohort["avg_frequency"] if cohort else 3)
    duration_min = duration_min or (round(cohort["avg_duration_hr"] * 60) if cohort else 40)

    kcal_for = None
    if body:
        def kcal_for(w_type, minutes):
            return predict_calories({**body, "workout_type": w_type, "duration_min": minutes,
                                     "frequency": frequency,
                                     "experience_level": experience_level})["predicted_calories"]

    weekly_plan = build_weekly_plan(experience_level, frequency, duration_min, primary_type,
                                    kcal_for)
    training = [d for d in weekly_plan if d["type"] != "Rest"]
    return {
        "bmi_category": category,
        "cohort_insight": cohort,
        "weekly_plan": weekly_plan,
        "training_days": len(training),
        "week_total_kcal": sum(d["est_kcal"] or 0 for d in training) if body else None,
        "types_in_plan": [d["type"] for d in training],
    }


def search_exercises(search=None, body_part=None, equipment=None, level=None, ex_type=None,
                      page=1, per_page=12):
    results = _exercises
    if search:
        s = search.lower()
        results = [e for e in results if s in e["Title"].lower()]
    if body_part:
        results = [e for e in results if e["BodyPart"] == body_part]
    if equipment:
        results = [e for e in results if e["Equipment"] == equipment]
    if level:
        results = [e for e in results if e["Level"] == level]
    if ex_type:
        results = [e for e in results if e["Type"] == ex_type]

    total = len(results)
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "results": results[start:end],
    }


def get_student_insights():
    return _student_insights


def filter_options():
    return {
        "workout_types": WORKOUT_TYPES,
        "activity_types": ACTIVITY_TYPES,
        "body_parts": BODY_PARTS,
        "equipment": EQUIPMENT_TYPES,
        "levels": LEVELS,
        "exercise_types": sorted({e["Type"] for e in _exercises}),
    }
