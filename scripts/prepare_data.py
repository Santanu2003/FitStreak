"""
Rebuild generated reference artifacts in backend/data from the canonical source CSVs in scripts/.
The runtime does not keep duplicate raw CSV copies; scripts/ is the single source for these inputs.
"""
import csv
import json
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(HERE), "backend", "data")
os.makedirs(DATA_DIR, exist_ok=True)


def prepare_gym_members():
    df = pd.read_csv(os.path.join(HERE, "gym_members_exercise_tracking.csv"))
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"gym_members_exercise_tracking: {df.shape}")



def student_insight_extras(df):
    """Finer-grained views of the user survey that power the interactive parts of the
    User Insights page: a 1-hour-step activity curve (for the what-if slider) and how the
    stress mix changes across the four activity buckets."""
    def act_bucket(h):
        return ("< 1 hr/day" if h < 1 else "1-2 hrs/day" if h < 2
                else "2-3 hrs/day" if h < 3 else "3+ hrs/day")

    d = df.copy()
    d["Activity_Bucket"] = d["Physical_Activity_Hours_Per_Day"].apply(act_bucket)
    order = ["< 1 hr/day", "1-2 hrs/day", "2-3 hrs/day", "3+ hrs/day"]

    cap = 9  # everything from 9 hours up is one bin so no bin is tiny
    d["_bin"] = d["Physical_Activity_Hours_Per_Day"].clip(upper=cap).apply(lambda h: int(h) if h < cap else cap)
    curve = []
    for b, g in d.groupby("_bin"):
        curve.append({
            "from_hr": int(b), "label": f"{b}+" if b == cap else f"{b}-{b + 1}",
            "avg_gpa": round(float(g["GPA"].mean()), 2),
            "avg_sleep": round(float(g["Sleep_Hours_Per_Day"].mean()), 2),
            "avg_study": round(float(g["Study_Hours_Per_Day"].mean()), 2),
            "pct_high_stress": round(100 * float((g["Stress_Level"] == "High").mean()), 1),
            "count": int(len(g)),
        })

    mix = []
    for bucket in order:
        g = d[d["Activity_Bucket"] == bucket]
        n = len(g) or 1
        mix.append({"Activity_Bucket": bucket,
                    "low": round(100 * float((g["Stress_Level"] == "Low").sum()) / n, 1),
                    "moderate": round(100 * float((g["Stress_Level"] == "Moderate").sum()) / n, 1),
                    "high": round(100 * float((g["Stress_Level"] == "High").sum()) / n, 1)})
    return {"activity_curve": curve, "stress_by_bucket": mix,
            "overall_avg_sleep": round(float(df["Sleep_Hours_Per_Day"].mean()), 2),
            "overall_avg_study": round(float(df["Study_Hours_Per_Day"].mean()), 2)}


def prepare_student_lifestyle():
    df = pd.read_csv(os.path.join(HERE, "student_lifestyle_dataset.csv"))
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"student_lifestyle_dataset: {df.shape}")

    def act_bucket(h):
        if h < 1:
            return "< 1 hr/day"
        if h < 2:
            return "1-2 hrs/day"
        if h < 3:
            return "2-3 hrs/day"
        return "3+ hrs/day"

    df["Activity_Bucket"] = df["Physical_Activity_Hours_Per_Day"].apply(act_bucket)
    order = ["< 1 hr/day", "1-2 hrs/day", "2-3 hrs/day", "3+ hrs/day"]
    by_activity = df.groupby("Activity_Bucket").agg(
        avg_gpa=("GPA", "mean"),
        avg_sleep=("Sleep_Hours_Per_Day", "mean"),
        avg_study=("Study_Hours_Per_Day", "mean"),
        count=("Student_ID", "count"),
    ).reindex(order).reset_index()
    by_activity[["avg_gpa", "avg_sleep", "avg_study"]] = by_activity[
        ["avg_gpa", "avg_sleep", "avg_study"]
    ].round(2)

    stress_order = ["Low", "Moderate", "High"]
    stress_activity = (
        df.groupby("Stress_Level")["Physical_Activity_Hours_Per_Day"]
        .mean().round(2).reindex(stress_order).reset_index()
    )
    stress_activity.columns = ["stress_level", "avg_activity_hours"]

    insights = {
        "sample_size": int(len(df)),
        "activity_vs_outcomes": by_activity.to_dict(orient="records"),
        "activity_by_stress": stress_activity.to_dict(orient="records"),
        "correlation_activity_gpa": round(
            float(df["Physical_Activity_Hours_Per_Day"].corr(df["GPA"])), 3),
        "correlation_activity_sleep": round(
            float(df["Physical_Activity_Hours_Per_Day"].corr(df["Sleep_Hours_Per_Day"])), 3),
        "overall_avg_activity_hours": round(
            float(df["Physical_Activity_Hours_Per_Day"].mean()), 2),
        "overall_avg_gpa": round(float(df["GPA"].mean()), 2),
    }
    insights.update(student_insight_extras(df))
    with open(os.path.join(DATA_DIR, "student_insights.json"), "w") as f:
        json.dump(insights, f, indent=2)
    print("student_insights.json written")


def prepare_exercise_library():
    df = pd.read_csv(os.path.join(HERE, "megaGymDataset.csv"))
    df = df.drop_duplicates(subset=["Title", "BodyPart"]).reset_index(drop=True)
    df = df.drop(columns=["Unnamed: 0", "RatingDesc"])
    df["Equipment"] = df["Equipment"].fillna("None / Bodyweight")
    df["Desc"] = df["Desc"].fillna("No description available for this exercise.")
    df["Rating"] = df["Rating"].fillna(0.0)
    df.insert(0, "id", range(1, len(df) + 1))
    with open(os.path.join(DATA_DIR, "exercises.json"), "w") as f:
        json.dump(df.to_dict(orient="records"), f)
    print(f"exercise library: {df.shape}")

    def bmi_cat(b):
        if b < 18.5:
            return "Underweight"
        if b < 25:
            return "Normal"
        if b < 30:
            return "Overweight"
        return "Obese"

    gym = pd.read_csv(os.path.join(HERE, "gym_members_exercise_tracking.csv"))
    gym["BMI_Category"] = gym["BMI"].apply(bmi_cat)
    cohort = gym.groupby(["BMI_Category", "Experience_Level"]).agg(
        common_workout=("Workout_Type", lambda x: x.value_counts().idxmax()),
        avg_duration_hr=("Session_Duration (hours)", "mean"),
        avg_calories=("Calories_Burned", "mean"),
        avg_frequency=("Workout_Frequency (days/week)", "mean"),
        sample_size=("Workout_Type", "count"),
    ).reset_index()
    cohort["avg_duration_hr"] = cohort["avg_duration_hr"].round(2)
    cohort["avg_calories"] = cohort["avg_calories"].round(0)
    cohort["avg_frequency"] = cohort["avg_frequency"].round(1)
    cohort.to_json(os.path.join(DATA_DIR, "workout_cohorts.json"), orient="records")
    print(f"workout_cohorts: {cohort.shape}")


def prepare_health_benchmarks():
    df = pd.read_csv(os.path.join(HERE, "health_activity_data.csv"))
    df = df.drop_duplicates().reset_index(drop=True)

    def age_bracket(a):
        if a < 25: return "18-24"
        if a < 35: return "25-34"
        if a < 45: return "35-44"
        if a < 55: return "45-54"
        if a < 65: return "55-64"
        return "65+"

    df["Age_Bracket"] = df["Age"].apply(age_bracket)
    order = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]

    bench = df.groupby("Age_Bracket").agg(
        avg_steps=("Daily_Steps", "mean"),
        avg_exercise_hrs=("Exercise_Hours_per_Week", "mean"),
        avg_sleep=("Hours_of_Sleep", "mean"),
        avg_bmi=("BMI", "mean"),
        avg_heart_rate=("Heart_Rate", "mean"),
        avg_calories_intake=("Calories_Intake", "mean"),
        sample_size=("ID", "count"),
    ).reindex(order).reset_index()
    bench[["avg_steps", "avg_exercise_hrs", "avg_sleep", "avg_bmi", "avg_heart_rate", "avg_calories_intake"]] = bench[
        ["avg_steps", "avg_exercise_hrs", "avg_sleep", "avg_bmi", "avg_heart_rate", "avg_calories_intake"]
    ].round(1)

    raw = {}
    for bkt in order:
        sub = df[df["Age_Bracket"] == bkt]
        raw[bkt] = {
            "steps": sorted(sub["Daily_Steps"].tolist()),
            "exercise_hrs": sorted(sub["Exercise_Hours_per_Week"].tolist()),
            "sleep": sorted(sub["Hours_of_Sleep"].tolist()),
            "bmi": sorted(sub["BMI"].tolist()),
            "heart_rate": sorted(sub["Heart_Rate"].tolist()),
        }

    # Reference session intensity for the Leaderboard's "typical active person" benchmark
    # line: real kcal/min from the 973-session gym tracker, independent of any ML model.
    gym = pd.read_csv(os.path.join(HERE, "gym_members_exercise_tracking.csv"))
    session_kcal_per_min = round(
        float(gym["Calories_Burned"].mean() / (gym["Session_Duration (hours)"].mean() * 60)), 2)

    out = {"sample_size": int(len(df)), "benchmarks": bench.to_dict(orient="records"),
           "raw_by_bracket": raw, "session_kcal_per_min": session_kcal_per_min}
    with open(os.path.join(DATA_DIR, "health_benchmarks.json"), "w") as f:
        json.dump(out, f)
    print(f"health_benchmarks.json written ({len(df)} people, {session_kcal_per_min} kcal/min reference)")


def prepare_activity_comparison():
    """Requires health_fitness_dataset.csv (687k rows) — not shipped in this repo due to
    size; place your own copy in this folder to regenerate."""
    src = os.path.join(HERE, "health_fitness_dataset.csv")
    if not os.path.exists(src):
        print("Skipping activity_comparison.json — health_fitness_dataset.csv not found "
              "in scripts/ (it's ~78MB, not shipped with this repo).")
        return
    df = pd.read_csv(src)
    df["cal_per_min"] = df["calories_burned"] / df["duration_minutes"].replace(0, 1)

    by_activity = df.groupby("activity_type").agg(
        avg_calories=("calories_burned", "mean"),
        avg_duration=("duration_minutes", "mean"),
        cal_per_min=("cal_per_min", "mean"),
        count=("participant_id", "count"),
    ).round(2).reset_index().sort_values("cal_per_min", ascending=False)

    by_intensity = df.groupby("intensity").agg(
        avg_calories=("calories_burned", "mean"),
        cal_per_min=("cal_per_min", "mean"),
        count=("participant_id", "count"),
    ).round(3).reset_index()
    order = ["Low", "Medium", "High"]
    by_intensity["intensity"] = pd.Categorical(by_intensity["intensity"], categories=order, ordered=True)
    by_intensity = by_intensity.sort_values("intensity")

    out = {
        "sample_size": int(len(df)),
        "by_activity_type": by_activity.to_dict(orient="records"),
        "by_intensity": by_intensity.to_dict(orient="records"),
    }
    with open(os.path.join(DATA_DIR, "activity_comparison.json"), "w") as f:
        json.dump(out, f)
    print(f"activity_comparison.json written ({len(df)} sessions)")


def prepare_food_database():
    """daily_food_nutrition_dataset.csv has a handful of rows where the food name itself
    contains an unquoted comma (e.g. `Milk (2%, 1 cup)`), which breaks a plain pandas
    read. Re-join those rows by hand instead of silently dropping them."""
    src = os.path.join(HERE, "daily_food_nutrition_dataset.csv")
    header = None
    rows = []
    with open(src, newline="") as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0:
                header = row
                continue
            if len(row) == 13:
                row = [row[0] + "," + row[1]] + row[2:]
            if len(row) != len(header):
                continue
            rows.append(row)
    df = pd.DataFrame(rows, columns=header)

    numeric_cols = ["Calories (kcal)", "Protein (g)", "Carbohydrates (g)", "Fat (g)",
                     "Fiber (g)", "Sugars (g)", "Sodium (mg)", "Cholesterol (mg)",
                     "Water_Intake (ml)"]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c])

    df = df.drop_duplicates().reset_index(drop=True)
    # A few dozen rows are the exact same food logged under two meal types (e.g. a
    # condiment used at both lunch and dinner) — keep one canonical row per food name
    # so the search dropdown has no duplicate entries to pick from.
    df = df.drop_duplicates(subset=["Food_Item"], keep="first").reset_index(drop=True)
    df["Meal_Type"] = df["Meal_Type"].replace("Side", "Snack")

    df = df.rename(columns={
        "Calories (kcal)": "Calories", "Protein (g)": "Protein_g",
        "Carbohydrates (g)": "Carbs_g", "Fat (g)": "Fat_g", "Fiber (g)": "Fiber_g",
        "Sugars (g)": "Sugar_g", "Sodium (mg)": "Sodium_mg",
        "Cholesterol (mg)": "Cholesterol_mg", "Water_Intake (ml)": "Water_ml",
    })
    df.insert(0, "id", range(1, len(df) + 1))
    df = df[["id", "Food_Item", "Category", "Meal_Type", "Calories", "Protein_g",
              "Carbs_g", "Fat_g", "Fiber_g", "Sugar_g", "Sodium_mg", "Cholesterol_mg",
              "Water_ml"]]

    with open(os.path.join(DATA_DIR, "foods.json"), "w") as f:
        json.dump(df.to_dict(orient="records"), f)
    print(f"food database: {df.shape}")


if __name__ == "__main__":
    prepare_gym_members()
    prepare_student_lifestyle()
    prepare_exercise_library()
    prepare_health_benchmarks()
    prepare_activity_comparison()
    prepare_food_database()
    print("\nDone. backend/data/ is ready.")
