"""
Trains the calorie-burn regressor used by /api/predict/calories on ALL 10 workout types
(Cardio, HIIT, Strength, Yoga, Running, Walking, Swimming, Cycling, Dancing, Other).
Run once after prepare_data.py (or whenever the data changes):
    python train_models.py

Where the type information comes from
-------------------------------------
gym_members_exercise_tracking.csv (973 real sessions) has physiology, heart rate, duration and
calories - but only 4 workout types, and those 4 burn almost the same on average (885-926 kcal),
so it cannot teach a model how Walking differs from Running. The 687,701-session activity
dataset (already aggregated in data/activity_comparison.json) does show how activities differ
in kcal per minute. So:

  * every real gym session is treated as a "type-neutral" session (body, heart rate, duration,
    experience) and is replayed under each of the 10 workout types;
  * its calorie label is scaled by that type's relative intensity (kcal/min of the type divided
    by the mean over all types, from activity_comparison.json), and the heart-rate reserve is
    scaled to match, so a "Walking" row looks like a walk (lower heart rate) and burns less;
  * the model gets both the encoded type and its numeric intensity as features.

Train/test split is done on the REAL sessions first (so no session leaks between train and
test), then each split is expanded to the 10 types.
"""
import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(os.path.dirname(HERE), "backend")
DATA_PATH = os.path.join(HERE, "gym_members_exercise_tracking.csv")
COMPARE_PATH = os.path.join(BACKEND_DIR, "data", "activity_comparison.json")
ML_DIR = os.path.join(BACKEND_DIR, "ml")
os.makedirs(ML_DIR, exist_ok=True)

ALL_TYPES = ["Cardio", "HIIT", "Strength", "Yoga", "Running", "Walking",
             "Swimming", "Cycling", "Dancing", "Other"]

# App workout type -> activity name used in the 687k-session dataset. Cardio has no direct
# counterpart (it is generic steady-state work), so it uses the mean of the three steady
# cardio activities; Other uses the dataset-wide average (factor 1.0).
DATASET_NAME = {"HIIT": "HIIT", "Strength": "Weight Training", "Yoga": "Yoga",
                "Running": "Running", "Walking": "Walking", "Swimming": "Swimming",
                "Cycling": "Cycling", "Dancing": "Dancing"}

FEATURE_COLS = [
    "Age", "Gender", "Weight (kg)", "Height (m)", "Max_BPM", "Avg_BPM",
    "Resting_BPM", "Session_Duration (hours)", "Workout_Type", "Type_Intensity",
    "Fat_Percentage", "Workout_Frequency (days/week)", "Experience_Level", "BMI",
]


def type_factors():
    """Relative calorie intensity of each app workout type (dataset-wide mean = 1.0)."""
    with open(COMPARE_PATH) as f:
        rows = json.load(f)["by_activity_type"]
    per_min = {r["activity_type"]: r["cal_per_min"] for r in rows}
    mean = float(np.mean(list(per_min.values())))
    rel = {name: v / mean for name, v in per_min.items()}
    factors = {t: rel[n] for t, n in DATASET_NAME.items()}
    factors["Cardio"] = float(np.mean([rel["Running"], rel["Cycling"], rel["Swimming"]]))
    factors["Other"] = 1.0
    return {t: round(factors[t], 3) for t in ALL_TYPES}


def expand(real_df, factors, encoders):
    """Replay every real session under every workout type."""
    frames = []
    for t in ALL_TYPES:
        f = factors[t]
        d = real_df.copy()
        d["Calories_Burned"] = d["Calories_Burned"] * f
        # heart-rate reserve follows intensity (gently): walking looks like a walk
        hr_scale = float(np.clip(f ** 0.5, 0.65, 1.25))
        d["Avg_BPM"] = (d["Resting_BPM"] + (d["Avg_BPM"] - d["Resting_BPM"]) * hr_scale)
        d["Avg_BPM"] = np.minimum(d["Avg_BPM"], d["Max_BPM"] - 1).round(0)
        d["Workout_Type"] = encoders["Workout_Type"].transform([t] * len(d))
        d["Type_Intensity"] = f
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def main():
    df = pd.read_csv(DATA_PATH)
    factors = type_factors()

    gender_le = LabelEncoder().fit(df["Gender"])
    type_le = LabelEncoder().fit(ALL_TYPES)
    encoders = {"Gender": gender_le, "Workout_Type": type_le}
    df["Gender"] = gender_le.transform(df["Gender"])

    train_real, test_real = train_test_split(df, test_size=0.2, random_state=42)
    train, test = expand(train_real, factors, encoders), expand(test_real, factors, encoders)

    model = RandomForestRegressor(n_estimators=120, max_depth=16, min_samples_leaf=3,
                                  n_jobs=-1, random_state=42)
    model.fit(train[FEATURE_COLS], train["Calories_Burned"])
    pred = model.predict(test[FEATURE_COLS])
    mae = mean_absolute_error(test["Calories_Burned"], pred)
    print(f"Trained on {len(train)} rows = {len(train_real)} real sessions x {len(ALL_TYPES)} types")
    print(f"Overall MAE on held-out sessions: {mae:.1f} kcal (mean label {test['Calories_Burned'].mean():.0f})")
    per_type = {}
    for t in ALL_TYPES:
        m = (test["Workout_Type"] == type_le.transform([t])[0]).values
        per_type[t] = round(float(mean_absolute_error(test.loc[m, "Calories_Burned"], pred[m])), 1)
        print(f"  {t:<9} factor {factors[t]:<6} MAE {per_type[t]:>6} kcal")

    joblib.dump(
        {"model": model, "encoders": encoders, "feature_cols": FEATURE_COLS,
         "type_factors": factors, "trained_types": ALL_TYPES,
         "metrics": {"mae": round(float(mae), 1), "mae_by_type": per_type,
                     "real_sessions": int(len(df))}},
        os.path.join(ML_DIR, "calorie_model.pkl"), compress=3,
    )
    print("Saved backend/ml/calorie_model.pkl")


if __name__ == "__main__":
    main()
