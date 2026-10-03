"""FitStreak backend — Flask API + static frontend server."""
import os
import sqlite3
from datetime import datetime, date

from flask import Flask, request, jsonify, session, send_from_directory

import db as db_module
import models
import ml_utils
import health_utils
import goals
import nutrition_utils
import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
app.config["SECRET_KEY"] = os.environ.get("FITSTREAK_SECRET", "dev-secret-change-me")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # always revalidate JS/CSS so an old cached copy is never served
if os.environ.get("FITSTREAK_COOKIE_SECURE") == "1":
    # Deployed behind HTTPS (Vercel/Render): only send the login cookie over HTTPS.
    app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db_module.init_db()


# ---------------------------------------------------------------- helpers --
def current_user_row():
    uid = session.get("user_id")
    if not uid:
        return None
    return models.get_user_by_id(uid)


def require_login():
    user_row = current_user_row()
    if not user_row:
        return None, (jsonify({"error": "Not authenticated. Please log in."}), 401)
    return user_row, None


def parse_float(value, field, errors):
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"'{field}' must be a number.")
        return None


def parse_date_arg(name):
    """Reads ?name=YYYY-MM-DD (default: today). Returns (date, None) or (None, error response)."""
    raw = request.args.get(name)
    try:
        return (datetime.strptime(raw, "%Y-%m-%d").date() if raw else date.today()), None
    except ValueError:
        return None, (jsonify({"error": f"{name} must be in YYYY-MM-DD format."}), 400)


# ------------------------------------------------------------------- auth --
@app.route("/api/health", methods=["GET"])
def health_route():
    return jsonify({"ok": True})


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    errors = []
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name:
        errors.append("Name is required.")
    if not email or "@" not in email:
        errors.append("A valid email is required.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")

    age = parse_float(data.get("age"), "age", errors)
    height_cm = parse_float(data.get("height_cm"), "height_cm", errors)
    weight_kg = parse_float(data.get("weight_kg"), "weight_kg", errors)
    gender = data.get("gender") or "Other"
    try:
        experience_level = max(1, min(3, int(data.get("experience_level") or 1)))
    except (TypeError, ValueError):
        experience_level = 1

    if age is not None and not 13 <= age <= 100: errors.append("age must be between 13 and 100.")
    if height_cm is not None and not 100 <= height_cm <= 230: errors.append("height_cm must be between 100 and 230.")
    if weight_kg is not None and not 30 <= weight_kg <= 250: errors.append("weight_kg must be between 30 and 250.")
    if gender not in ("Female", "Male", "Other"): errors.append("gender must be Female, Male or Other.")
    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    if models.get_user_by_email(email):
        return jsonify({"error": "An account with that email already exists."}), 409

    try:
        user_id = models.create_user(
            name=name, email=email, password=password, age=int(age), gender=gender,
            height_cm=height_cm, weight_kg=weight_kg, experience_level=experience_level,
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 409

    session["user_id"] = user_id
    user_row = models.get_user_by_id(user_id)
    return jsonify({"user": models.user_public_dict(user_row)}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user_row = models.get_user_by_email(email)
    if not user_row or not models.verify_password(user_row, password):
        return jsonify({"error": "Invalid email or password."}), 401

    session["user_id"] = user_row["id"]
    return jsonify({"user": models.user_public_dict(user_row)})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def me():
    user_row, err = require_login()
    if err:
        return err
    return jsonify({"user": models.user_public_dict(user_row)})


@app.route("/api/config", methods=["GET"])
def app_config():
    """Frontend configuration: one canonical vocabulary instead of duplicated lists."""
    return jsonify({
        "activity_types": config.ACTIVITY_TYPES,
        "meal_types": config.MEAL_TYPES,
        "moods": config.MOODS,
        "experience_levels": [{"value": k, "label": v} for k, v in config.EXPERIENCE_LABELS.items()],
        "goals": config.GOALS,
        "age_brackets": config.AGE_BRACKETS,
        "datasets": {
            "exercise_count": len(ml_utils._exercises),
            "student_sample_size": int(ml_utils._student_insights.get("sample_size", 0)),
            "health_sample_size": int(health_utils._bench.get("sample_size", 0)),
            "activity_comparison_sample_size": int(health_utils._activity_comparison.get("sample_size", 0)),
            "food_count": len(nutrition_utils._foods),
            "general_food_count": len(nutrition_utils._foods) - sum(1 for f in nutrition_utils._foods if int(f.get("id", 0)) >= nutrition_utils.INDIAN_ID_START),
            "indian_food_count": sum(1 for f in nutrition_utils._foods if int(f.get("id", 0)) >= nutrition_utils.INDIAN_ID_START),
        },
        "model": ml_utils.MODEL_METADATA,
    })


@app.route("/api/user/summary", methods=["GET"])
def user_summary():
    user_row, err = require_login()
    if err:
        return err
    end_date, bad = parse_date_arg("date")
    if bad:
        return bad
    return jsonify(models.unified_user_summary(user_row["id"], end_date.isoformat()))


# --------------------------------------------------------------- activity --
@app.route("/api/activity", methods=["POST"])
def log_activity():
    user_row, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    errors = []
    activity_type = (data.get("activity_type") or "").strip()
    if not activity_type:
        errors.append("activity_type is required.")
    elif activity_type not in ml_utils.ACTIVITY_TYPES:
        errors.append(f"activity_type must be one of: {', '.join(ml_utils.ACTIVITY_TYPES)}.")

    duration_min = parse_float(data.get("duration_min"), "duration_min", errors)
    try:
        steps = int(data.get("steps") or 0)
    except (TypeError, ValueError):
        errors.append("steps must be a whole number.")
        steps = 0
    mood = data.get("mood") or "Okay"
    if duration_min is not None and not 1 <= duration_min <= 600: errors.append("duration_min must be between 1 and 600.")
    if steps < 0 or steps > 100000: errors.append("steps must be between 0 and 100000.")
    if mood not in config.MOODS: errors.append(f"mood must be one of: {', '.join(config.MOODS)}.")

    log_date_raw = data.get("date")
    try:
        log_date = datetime.strptime(log_date_raw, "%Y-%m-%d").date() if log_date_raw else date.today()
    except ValueError:
        errors.append("date must be in YYYY-MM-DD format.")
        log_date = date.today()

    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    # Calories are always derived from activity type, duration, mood and the
    # user's own body weight — never taken as raw user input.
    calories_burned = health_utils.estimate_activity_calories(
        activity_type=activity_type, duration_min=duration_min,
        weight_kg=user_row["weight_kg"], mood=mood,
    )

    entry, was_update = models.upsert_activity_log(
        user_id=user_row["id"], log_date=log_date.isoformat(), activity_type=activity_type,
        duration_min=duration_min, calories_burned=calories_burned, steps=steps, mood=mood,
    )
    status = 200 if was_update else 201
    return jsonify({"log": entry, "updated": was_update}), status


@app.route("/api/activity/estimate-calories", methods=["GET"])
def estimate_activity_calories_route():
    user_row, err = require_login()
    if err:
        return err
    activity_type = request.args.get("activity_type", "")
    duration_min = request.args.get("duration_min", type=float) or 0.0
    mood = request.args.get("mood", "Okay")
    calories = health_utils.estimate_activity_calories(
        activity_type=activity_type, duration_min=duration_min,
        weight_kg=user_row["weight_kg"], mood=mood,
    )
    return jsonify({"estimated_calories": calories})


@app.route("/api/activity/history", methods=["GET"])
def activity_history():
    user_row, err = require_login()
    if err:
        return err
    logs = models.get_logs_for_user(user_row["id"])
    total = {"sessions": len(logs), "minutes": round(sum(l["duration_min"] for l in logs), 1),
             "calories": round(sum(l["calories_burned"] for l in logs), 1),
             "steps": sum(l["steps"] for l in logs),
             "active_days": len({l["log_date"] for l in logs})}
    return jsonify({"logs": logs, "summary": total})


@app.route("/api/activity/<int:log_id>", methods=["DELETE"])
def delete_activity(log_id):
    user_row, err = require_login()
    if err:
        return err
    ok = models.delete_activity_log(log_id, user_row["id"])
    if not ok:
        return jsonify({"error": "Log not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/food", methods=["POST"])
def log_food():
    user_row, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    errors = []
    meal = (data.get("meal") or "").strip()
    if not meal:
        errors.append("meal is required.")
    elif meal not in nutrition_utils.MEAL_TYPES:
        errors.append(f"meal must be one of: {', '.join(nutrition_utils.MEAL_TYPES)}.")
    food_name = (data.get("food_name") or "").strip()
    if not food_name:
        errors.append("food_name is required.")
    elif len(food_name) > 120:
        errors.append("food_name is too long (120 characters max).")

    servings = parse_float(data.get("servings"), "servings", errors)
    calories = parse_float(data.get("calories"), "calories", errors)
    protein_g = parse_float(data.get("protein_g"), "protein_g", errors)
    carbs_g = parse_float(data.get("carbs_g"), "carbs_g", errors)
    fat_g = parse_float(data.get("fat_g"), "fat_g", errors)

    log_date_raw = data.get("date")
    try:
        log_date = datetime.strptime(log_date_raw, "%Y-%m-%d").date() if log_date_raw else date.today()
    except ValueError:
        errors.append("date must be in YYYY-MM-DD format.")
        log_date = date.today()

    if not errors:
        errors.extend(nutrition_utils.check_entry_numbers(
            servings, calories, protein_g, carbs_g, fat_g))

    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    entry, was_update = models.upsert_food_log(
        user_id=user_row["id"], log_date=log_date.isoformat(), meal=meal,
        food_name=food_name, servings=servings, calories=calories,
        protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g,
    )
    saved_custom = None
    if data.get("save_custom") is True and nutrition_utils.get_food_by_name(food_name) is None:
        saved_custom = models.upsert_custom_food(
            user_row["id"], food_name, servings, calories, protein_g, carbs_g, fat_g)
    status = 200 if was_update else 201
    return jsonify({"entry": entry, "updated": was_update, "saved_custom_food": saved_custom}), status


@app.route("/api/food", methods=["GET"])
def food_log_for_date():
    user_row, err = require_login()
    if err:
        return err
    log_date_raw = request.args.get("date")
    try:
        log_date = datetime.strptime(log_date_raw, "%Y-%m-%d").date() if log_date_raw else date.today()
    except ValueError:
        return jsonify({"error": "date must be in YYYY-MM-DD format."}), 400
    entries = models.get_food_logs_for_date(user_row["id"], log_date.isoformat())
    return jsonify({"entries": entries, "date": log_date.isoformat()})


@app.route("/api/food/<int:food_id>", methods=["DELETE"])
def delete_food(food_id):
    user_row, err = require_login()
    if err:
        return err
    ok = models.delete_food_log(food_id, user_row["id"])
    if not ok:
        return jsonify({"error": "Entry not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/food/macros", methods=["GET"])
def food_macros_route():
    user_row, err = require_login()
    if err:
        return err
    log_date_raw = request.args.get("date")
    try:
        log_date = datetime.strptime(log_date_raw, "%Y-%m-%d").date() if log_date_raw else date.today()
    except ValueError:
        return jsonify({"error": "date must be in YYYY-MM-DD format."}), 400
    return jsonify(models.macros_for_date(user_row["id"], log_date.isoformat()))


@app.route("/api/weight", methods=["POST"])
def log_weight():
    user_row, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    errors = []
    weight_kg = parse_float(data.get("weight_kg"), "weight_kg", errors)
    if weight_kg is not None and not (20 <= weight_kg <= 400):
        errors.append("weight_kg must be between 20 and 400.")

    log_date_raw = data.get("date")
    try:
        log_date = datetime.strptime(log_date_raw, "%Y-%m-%d").date() if log_date_raw else date.today()
    except ValueError:
        errors.append("date must be in YYYY-MM-DD format.")
        log_date = date.today()

    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    entry, was_update = models.upsert_weight_log(
        user_id=user_row["id"], log_date=log_date.isoformat(), weight_kg=weight_kg,
    )
    status = 200 if was_update else 201
    return jsonify({"entry": entry, "updated": was_update}), status


@app.route("/api/weight/history", methods=["GET"])
def weight_history():
    user_row, err = require_login()
    if err:
        return err
    return jsonify({
        "logs": models.get_weight_logs_for_user(user_row["id"]),
        "bmi_history": models.bmi_history(user_row["id"]),
    })


@app.route("/api/weight/<int:log_id>", methods=["DELETE"])
def delete_weight(log_id):
    user_row, err = require_login()
    if err:
        return err
    ok = models.delete_weight_log(log_id, user_row["id"])
    if not ok:
        return jsonify({"error": "Log not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/dashboard/summary", methods=["GET"])
def dashboard_summary_route():
    user_row, err = require_login()
    if err:
        return err
    return jsonify(models.dashboard_summary(user_row["id"]))


# ---------------------------------------------------------------- predict --
@app.route("/api/predict/profile", methods=["GET"])
def predict_profile_route():
    user_row, err = require_login()
    if err:
        return err
    recent = models.recent_activity_metrics(user_row["id"], 28)
    return jsonify({"profile": models.user_public_dict(user_row), "recent_28_days": recent,
                    "model": ml_utils.MODEL_METADATA})


@app.route("/api/predict/calories", methods=["POST"])
def predict_calories_route():
    data = request.get_json(silent=True) or {}
    user_row = current_user_row()
    if user_row:
        data = {"age": user_row["age"], "gender": user_row["gender"],
                "weight_kg": user_row["weight_kg"], "height_cm": user_row["height_cm"],
                "experience_level": user_row["experience_level"], **data}
    required = ["age", "gender", "weight_kg", "height_cm", "workout_type", "duration_min",
                "avg_bpm", "max_bpm", "resting_bpm", "frequency", "experience_level"]
    missing = [f for f in required if data.get(f) in (None, "")]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    if data["workout_type"] not in ml_utils.ACTIVITY_TYPES:
        return jsonify({"error": "workout_type must be one of: "
                                 f"{', '.join(ml_utils.ACTIVITY_TYPES)}."}), 400

    try:
        payload = {
            "age": float(data["age"]),
            "gender": data["gender"],
            "weight_kg": float(data["weight_kg"]),
            "height_cm": float(data["height_cm"]),
            "workout_type": data["workout_type"],
            "duration_min": float(data["duration_min"]),
            "avg_bpm": float(data["avg_bpm"]),
            "max_bpm": float(data["max_bpm"]),
            "resting_bpm": float(data["resting_bpm"]),
            "frequency": float(data["frequency"]),
            "experience_level": int(data["experience_level"]),
        }
    except (TypeError, ValueError):
        return jsonify({"error": "One or more fields have an invalid number format."}), 400

    bounds = [("age", 13, 100), ("weight_kg", 30, 250), ("height_cm", 100, 230),
              ("duration_min", 5, 240), ("avg_bpm", 40, 220), ("max_bpm", 60, 230),
              ("resting_bpm", 30, 120), ("frequency", 1, 7)]
    for field, lo, hi in bounds:
        if not lo <= payload[field] <= hi:
            return jsonify({"error": f"{field} must be between {lo} and {hi}."}), 400
    if payload["max_bpm"] < payload["avg_bpm"] or payload["avg_bpm"] < payload["resting_bpm"]:
        return jsonify({"error": "Heart-rate values must satisfy resting ≤ average ≤ max."}), 400
    result = ml_utils.predict_calories(payload)
    return jsonify(result)


@app.route("/api/predict/estimate-fat", methods=["GET"])
def estimate_fat_route():
    """Live preview for the Predict form: body fat % is never typed in by hand — it's
    derived from age/gender/BMI (see ml_utils.estimate_body_fat_percentage)."""
    age = request.args.get("age", type=float)
    height_cm = request.args.get("height_cm", type=float)
    weight_kg = request.args.get("weight_kg", type=float)
    gender = request.args.get("gender", "")
    if not age or not height_cm or not weight_kg:
        return jsonify({"error": "age, height_cm and weight_kg are required."}), 400
    bmi = round(weight_kg / ((height_cm / 100.0) ** 2), 1)
    fat = ml_utils.estimate_body_fat_percentage(age, gender, bmi)
    return jsonify({"estimated_fat_percentage": fat, "bmi": bmi})


@app.route("/api/recommend/workout", methods=["GET"])
def recommend_workout_route():
    """bmi + experience_level are required. Optional: workout_type, frequency, duration_min
    (override the cohort averages) and age/gender/weight_kg/height_cm/avg_bpm/max_bpm/
    resting_bpm (all seven together let each training day carry a model calorie estimate)."""
    bmi = request.args.get("bmi", type=float)
    experience_level = request.args.get("experience_level", type=int)
    workout_type = request.args.get("workout_type")
    if bmi is None or experience_level is None:
        return jsonify({"error": "bmi and experience_level query params are required."}), 400
    if workout_type and workout_type not in ml_utils.ACTIVITY_TYPES:
        return jsonify({"error": "workout_type must be one of: "
                                 f"{', '.join(ml_utils.ACTIVITY_TYPES)}."}), 400

    frequency = request.args.get("frequency", type=float)
    duration_min = request.args.get("duration_min", type=float)
    body = None
    numeric = {k: request.args.get(k, type=float) for k in
               ("age", "weight_kg", "height_cm", "avg_bpm", "max_bpm", "resting_bpm")}
    gender = request.args.get("gender")
    if gender and all(v is not None for v in numeric.values()) and numeric["height_cm"] > 0:
        body = {**numeric, "gender": gender}
    return jsonify(ml_utils.recommend_workout(
        bmi, experience_level, workout_type,
        frequency=frequency if frequency and frequency > 0 else None,
        duration_min=duration_min if duration_min and duration_min > 0 else None,
        body=body))


@app.route("/api/exercises", methods=["GET"])
def exercises_route():
    result = ml_utils.search_exercises(
        search=request.args.get("search"),
        body_part=request.args.get("body_part"),
        equipment=request.args.get("equipment"),
        level=request.args.get("level"),
        ex_type=request.args.get("type"),
        page=request.args.get("page", default=1, type=int),
        per_page=request.args.get("per_page", default=12, type=int),
    )
    return jsonify(result)


@app.route("/api/exercises/options", methods=["GET"])
def exercise_options_route():
    return jsonify(ml_utils.filter_options())


@app.route("/api/insights/student", methods=["GET"])
def student_insights_route():
    data = dict(ml_utils.get_student_insights())
    user_row = current_user_row()
    if user_row:
        data["your_stats"] = models.personal_activity_summary(user_row["id"])
    return jsonify(data)


@app.route("/api/foods", methods=["GET"])
def foods_search_route():
    search = request.args.get("search", "")
    limit = request.args.get("limit", default=12, type=int)
    # Logged-in users get the shared custom-food library first; anonymous callers
    # only see the built-in datasets.
    user_row = current_user_row()
    custom = models.get_custom_foods(user_row["id"]) if user_row else []
    return jsonify({"results": nutrition_utils.search_foods(search, limit, extra_foods=custom)})


@app.route("/api/custom-foods", methods=["GET"])
def list_custom_foods():
    user_row, err = require_login()
    if err:
        return err
    return jsonify({"foods": models.get_custom_foods(user_row["id"])})


@app.route("/api/custom-foods", methods=["POST"])
def create_custom_food():
    user_row, err = require_login()
    if err:
        return err
    return save_custom_food_route(user_row["id"])


@app.route("/api/custom-foods/<int:food_id>", methods=["PUT", "PATCH"])
def update_custom_food(food_id):
    user_row, err = require_login()
    if err:
        return err
    return save_custom_food_route(user_row["id"], food_id)


def save_custom_food_route(user_id, food_id=None):
    data = request.get_json(silent=True) or {}
    errors = []
    food_name = " ".join(str(data.get("food_name") or "").split()).strip()
    if not food_name:
        errors.append("food_name is required.")
    elif len(food_name) > 120:
        errors.append("food_name is too long (120 characters max).")

    calories = parse_float(data.get("calories"), "calories", errors)
    protein_g = parse_float(data.get("protein_g"), "protein_g", errors)
    carbs_g = parse_float(data.get("carbs_g"), "carbs_g", errors)
    fat_g = parse_float(data.get("fat_g"), "fat_g", errors)
    if not errors:
        errors.extend(nutrition_utils.check_entry_numbers(1, calories, protein_g, carbs_g, fat_g))
        if nutrition_utils.get_food_by_name(food_name) is not None:
            errors.append("That name already exists in the built-in Food Database. Choose a different name to avoid duplicate foods.")

    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    saved, status = models.save_custom_food(
        user_id, food_name, calories, protein_g, carbs_g, fat_g, food_id=food_id
    )
    if status == "not_found":
        return jsonify({"error": "Saved food not found."}), 404
    if status == "duplicate":
        return jsonify({"error": "A custom food with that name already exists in the shared Food Database. Search for it and use the existing entry."}), 409
    return jsonify({"food": saved, "created": status == "created", "updated": status == "updated"}), 201 if status == "created" else 200


@app.route("/api/custom-foods/<int:food_id>", methods=["DELETE"])
def delete_custom_food(food_id):
    user_row, err = require_login()
    if err:
        return err
    if not models.delete_custom_food(food_id, user_row["id"]):
        return jsonify({"error": "Saved food not found."}), 404
    return jsonify({"ok": True})


@app.route("/api/health-benchmark/personal", methods=["GET"])
def health_benchmark_personal_route():
    user_row, err = require_login()
    if err:
        return err
    recent = models.recent_activity_metrics(user_row["id"], 7)
    weights = models.get_weight_logs_for_user(user_row["id"])
    current_weight = models._weight_on(user_row, weights, date.today().isoformat())
    bmi = models._bmi(user_row["height_cm"], current_weight)
    # Sleep is intentionally not fabricated: the app does not collect sleep logs yet.
    return jsonify({"age": user_row["age"], "daily_steps": round(recent["steps"] / 7),
                    "exercise_hours_per_week": round(recent["minutes"] / 60, 1),
                    "bmi": bmi, "sleep_logged": False, "window_days": 7,
                    "source": "your FitStreak activity logs"})


@app.route("/api/health-benchmark", methods=["POST"])
def health_benchmark_route():
    data = request.get_json(silent=True) or {}
    errors = []
    age = parse_float(data.get("age"), "age", errors)
    daily_steps = parse_float(data.get("daily_steps"), "daily_steps", errors)
    sleep_hours = parse_float(data.get("sleep_hours"), "sleep_hours", errors)
    exercise_hours = parse_float(data.get("exercise_hours_per_week"), "exercise_hours_per_week", errors)
    bmi = parse_float(data.get("bmi"), "bmi", errors) if data.get("bmi") not in (None, "") else None
    if errors:
        return jsonify({"error": " ".join(errors)}), 400
    return jsonify(health_utils.compute_benchmark(age, daily_steps, sleep_hours, exercise_hours, bmi=bmi))


@app.route("/api/health-benchmark/summary", methods=["GET"])
def health_benchmark_summary_route():
    return jsonify({"benchmarks": health_utils.get_bracket_summary()})


@app.route("/api/insights/activity-comparison", methods=["GET"])
def activity_comparison_route():
    data = dict(health_utils.get_activity_comparison())
    data["dynamic_source"] = "backend/data/activity_comparison.json"
    return jsonify(data)


@app.route("/api/leaderboard", methods=["GET"])
def leaderboard_route():
    period = request.args.get("period", "week")
    if period not in ("all", "week", "month"):
        return jsonify({"error": "period must be 'all', 'week' or 'month'."}), 400
    board = models.leaderboard(period=period)
    user_row = current_user_row()
    current = next((r for r in board if user_row and r.get("user_id") == user_row["id"]), None)
    benchmark = None
    if period in ("week", "month"):
        weekly = health_utils.weekly_exercise_benchmark_kcal(user_row["age"] if user_row else None)
        benchmark = {**weekly, "weekly_kcal": weekly["weekly_kcal"] * (1 if period == "week" else 30 / 7)}
        benchmark["weekly_kcal"] = round(benchmark["weekly_kcal"])
    return jsonify({
        "leaderboard": board, "period": period,
        "your_rank": current["rank"] if current else None,
        "your_row": current,
        "community": models.leaderboard_community_stats(board, period),
        "benchmark": benchmark,
    })


@app.route("/api/goal", methods=["GET"])
def get_goal():
    user_row, err = require_login()
    if err:
        return err
    log_date, bad = parse_date_arg("date")
    if bad:
        return bad
    return jsonify({**models.get_goal_status(user_row["id"], log_date.isoformat()),
                    "options": goals.GOAL_LABELS, "selected": user_row["goal"]})


@app.route("/api/goal", methods=["POST"])
def set_goal():
    user_row, err = require_login()
    if err:
        return err
    goal = (request.get_json(silent=True) or {}).get("goal")
    if goal not in goals.GOAL_OFFSETS:
        return jsonify({"error": f"goal must be one of: {', '.join(goals.GOAL_OFFSETS)}."}), 400
    if goal == "lose" and user_row["age"] < goals.MIN_LOSE_AGE:
        return jsonify({"error": "Weight-loss targets aren't offered under 18 — "
                                 "choose maintain or gain, and talk to a doctor or coach."}), 400
    models.set_user_goal(user_row["id"], goal)
    return jsonify({**models.get_goal_status(user_row["id"]), "options": goals.GOAL_LABELS,
                    "selected": goal})


@app.route("/api/nutrition/day", methods=["GET"])
def nutrition_day_route():
    """Whole-day summary for any date: eaten, exercise burn, net, target, macros, the day's
    meals and workouts, and whether the day ended in a surplus or a deficit."""
    user_row, err = require_login()
    if err:
        return err
    log_date, bad = parse_date_arg("date")
    if bad:
        return bad
    return jsonify(models.nutrition_day(user_row["id"], log_date.isoformat()))


@app.route("/api/nutrition/history", methods=["GET"])
def nutrition_history_route():
    """The last `days` days (default 7, max 90) ending at `end` (default today)."""
    user_row, err = require_login()
    if err:
        return err
    days = request.args.get("days", default=7, type=int)
    if days is None or not (1 <= days <= 90):
        return jsonify({"error": "days must be between 1 and 90."}), 400
    end, bad = parse_date_arg("end")
    if bad:
        return bad
    return jsonify(models.nutrition_history(user_row["id"], days, end.isoformat()))


# --------------------------------------------------------------- frontend --
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found."}), 404
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\nFitStreak is running — open http://127.0.0.1:{port} in your browser.\n")
    app.run(host="127.0.0.1", port=port, debug=False)
