"""Data-access helpers for users and activity logs (plain sqlite3, no ORM)."""
import bisect
from collections import Counter
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_connection
import goals


def _bmi(height_cm, weight_kg):
    h_m = height_cm / 100.0
    if h_m <= 0:
        return 0.0
    return round(weight_kg / (h_m * h_m), 1)


def _bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


def _streak_from_dates(log_dates):
    """log_dates: iterable of date objects. Returns current consecutive-day streak."""
    unique_dates = sorted(set(log_dates), reverse=True)
    if not unique_dates:
        return 0
    today = date.today()
    if unique_dates[0] not in (today, today - timedelta(days=1)):
        return 0
    streak = 1
    cursor = unique_dates[0]
    for d in unique_dates[1:]:
        if cursor - d == timedelta(days=1):
            streak += 1
            cursor = d
        else:
            break
    return streak


def _badge_for_streak(streak):
    if streak >= 30:
        return "Gold"
    if streak >= 14:
        return "Silver"
    if streak >= 3:
        return "Bronze"
    return "None"


# ------------------------------------------------------------------- users --
def create_user(name, email, password, age, gender, height_cm, weight_kg, experience_level=1):
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO users (name, email, password_hash, age, gender, height_cm,
                                   weight_kg, experience_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, email, generate_password_hash(password), age, gender,
             height_cm, weight_kg, experience_level),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def verify_password(user_row, password):
    return check_password_hash(user_row["password_hash"], password)


def user_public_dict(user_row):
    logs = get_logs_for_user(user_row["id"])
    log_dates = [date.fromisoformat(l["log_date"]) for l in logs]
    streak = _streak_from_dates(log_dates)
    bmi = _bmi(user_row["height_cm"], user_row["weight_kg"])
    return {
        "id": user_row["id"],
        "name": user_row["name"],
        "email": user_row["email"],
        "age": user_row["age"],
        "gender": user_row["gender"],
        "height_cm": user_row["height_cm"],
        "weight_kg": user_row["weight_kg"],
        "experience_level": user_row["experience_level"],
        "goal": user_row["goal"],
        "bmi": bmi,
        "bmi_category": _bmi_category(bmi),
        "current_streak": streak,
        "badge": _badge_for_streak(streak),
    }


# ------------------------------------------------------------------ logs ----
def upsert_activity_log(user_id, log_date, activity_type, duration_min, calories_burned,
                         steps, mood):
    conn = get_connection()
    try:
        existing = conn.execute(
            """SELECT id FROM activity_logs
               WHERE user_id = ? AND log_date = ? AND activity_type = ?""",
            (user_id, log_date, activity_type),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE activity_logs
                   SET duration_min = ?, calories_burned = ?, steps = ?, mood = ?
                   WHERE id = ?""",
                (duration_min, calories_burned, steps, mood, existing["id"]),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM activity_logs WHERE id = ?",
                                (existing["id"],)).fetchone()
            return dict(row), True

        cur = conn.execute(
            """INSERT INTO activity_logs
               (user_id, log_date, activity_type, duration_min, calories_burned, steps, mood)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, log_date, activity_type, duration_min, calories_burned, steps, mood),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM activity_logs WHERE id = ?",
                            (cur.lastrowid,)).fetchone()
        return dict(row), False
    finally:
        conn.close()


def get_logs_for_user(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM activity_logs WHERE user_id = ? ORDER BY log_date ASC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_activity_log(log_id, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM activity_logs WHERE id = ? AND user_id = ?", (log_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def dashboard_summary(user_id):
    user_row = get_user_by_id(user_id)
    logs = get_logs_for_user(user_id)
    log_dates = [date.fromisoformat(l["log_date"]) for l in logs]
    streak = _streak_from_dates(log_dates)
    total_calories = sum(l["calories_burned"] for l in logs)
    total_minutes = sum(l["duration_min"] for l in logs)
    total_steps = sum(l["steps"] for l in logs)

    today = date.today().isoformat()
    burned_today = sum(l["calories_burned"] for l in logs if l["log_date"] == today)
    food_today = get_food_logs_for_date(user_id, today)
    consumed_today = sum(f["calories"] for f in food_today)
    logged_today = any(l["log_date"] == today for l in logs)

    return {
        "user": user_public_dict(user_row),
        "total_sessions": len(logs),
        "total_calories": round(total_calories, 1),
        "total_minutes": round(total_minutes, 1),
        "total_steps": total_steps,
        "current_streak": streak,
        "badge": _badge_for_streak(streak),
        "logged_today": logged_today,
        "net_calories_today": {
            "consumed": round(consumed_today, 1),
            "burned": round(burned_today, 1),
            "net": round(consumed_today - burned_today, 1),
        },
        "calorie_goal": get_goal_status(user_id, today),
    }


def get_goal_status(user_id, log_date=None):
    """Calorie target vs. what was eaten for `log_date` (default today). The target uses the
    weight logged on or before that date, so a past day is judged with the body you had then."""
    user_row = get_user_by_id(user_id)
    log_date = log_date or date.today().isoformat()
    burned = sum(l["calories_burned"] for l in get_logs_for_user(user_id)
                 if l["log_date"] == log_date)
    consumed = sum(f["calories"] for f in get_food_logs_for_date(user_id, log_date))
    profile = {**user_row, "weight_kg": _weight_on(user_row, get_weight_logs_for_user(user_id), log_date)}
    return {**goals.daily_target(profile, burned, consumed), "date": log_date}


def set_user_goal(user_id, goal):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET goal = ? WHERE id = ?", (goal, user_id))
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------ weight log ----
def upsert_weight_log(user_id, log_date, weight_kg):
    """Logging a weight for a date already logged updates it instead of
    duplicating. After saving, the user's `weight_kg` (used everywhere else —
    BMI, the predictor, health benchmark) is refreshed to whichever logged
    weight has the most recent date, so it stays current automatically."""
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM weight_logs WHERE user_id = ? AND log_date = ?",
            (user_id, log_date),
        ).fetchone()

        if existing:
            conn.execute("UPDATE weight_logs SET weight_kg = ? WHERE id = ?",
                         (weight_kg, existing["id"]))
            conn.commit()
            row_id = existing["id"]
            was_update = True
        else:
            cur = conn.execute(
                "INSERT INTO weight_logs (user_id, log_date, weight_kg) VALUES (?, ?, ?)",
                (user_id, log_date, weight_kg),
            )
            conn.commit()
            row_id = cur.lastrowid
            was_update = False

        row = conn.execute("SELECT * FROM weight_logs WHERE id = ?", (row_id,)).fetchone()

        latest = conn.execute(
            "SELECT weight_kg FROM weight_logs WHERE user_id = ? ORDER BY log_date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if latest:
            conn.execute("UPDATE users SET weight_kg = ? WHERE id = ?",
                         (latest["weight_kg"], user_id))
            conn.commit()

        return dict(row), was_update
    finally:
        conn.close()


def get_weight_logs_for_user(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM weight_logs WHERE user_id = ? ORDER BY log_date ASC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_weight_log(log_id, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM weight_logs WHERE id = ? AND user_id = ?", (log_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def bmi_history(user_id):
    user_row = get_user_by_id(user_id)
    height_cm = user_row["height_cm"]
    logs = get_weight_logs_for_user(user_id)
    return [
        {
            "date": l["log_date"],
            "weight_kg": l["weight_kg"],
            "bmi": _bmi(height_cm, l["weight_kg"]),
        }
        for l in logs
    ]


# -------------------------------------------------------------- food log ----
def upsert_food_log(user_id, log_date, meal, food_name, servings, calories,
                     protein_g, carbs_g, fat_g):
    food_name = " ".join(str(food_name).split()).strip()
    """Logging the same food under the same meal on the same date updates that
    entry (new servings/macros overwrite the old ones) instead of creating a
    second row — mirrors upsert_activity_log's duplicate protection."""
    conn = get_connection()
    try:
        existing = conn.execute(
            """SELECT id FROM food_logs
               WHERE user_id = ? AND log_date = ? AND meal = ? AND lower(trim(food_name)) = lower(trim(?))""",
            (user_id, log_date, meal, food_name),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE food_logs
                   SET servings = ?, calories = ?, protein_g = ?, carbs_g = ?, fat_g = ?
                   WHERE id = ?""",
                (servings, calories, protein_g, carbs_g, fat_g, existing["id"]),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM food_logs WHERE id = ?",
                                (existing["id"],)).fetchone()
            return dict(row), True

        cur = conn.execute(
            """INSERT INTO food_logs
               (user_id, log_date, meal, food_name, servings, calories,
                protein_g, carbs_g, fat_g)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, log_date, meal, food_name, servings, calories,
             protein_g, carbs_g, fat_g),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM food_logs WHERE id = ?",
                            (cur.lastrowid,)).fetchone()
        return dict(row), False
    finally:
        conn.close()


def upsert_custom_food(user_id, food_name, servings, calories, protein_g, carbs_g, fat_g):
    """Save a typed food into the shared custom-food library.

    user_id is the creator/owner. If another account already created the same
    food name, reuse that shared food instead of creating a duplicate or
    silently changing somebody else's nutrition values.
    """
    food_name = " ".join(str(food_name).split()).strip()
    servings = servings if servings and servings > 0 else 1
    per = [round(v / servings, 1) for v in (calories, protein_g, carbs_g, fat_g)]
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM custom_foods WHERE lower(trim(food_name)) = lower(trim(?)) LIMIT 1",
            (food_name,),
        ).fetchone()
        if existing:
            # The creator may correct the shared entry through the explicit My Foods editor;
            # logging the same name from another account should never overwrite it.
            if existing["user_id"] == user_id:
                conn.execute(
                    """UPDATE custom_foods SET calories = ?, protein_g = ?, carbs_g = ?, fat_g = ?
                       WHERE id = ?""",
                    (*per, existing["id"]),
                )
                conn.commit()
                existing = conn.execute("SELECT * FROM custom_foods WHERE id = ?", (existing["id"],)).fetchone()
            return custom_food_as_search_item(existing, viewer_id=user_id)

        cur = conn.execute(
            """INSERT INTO custom_foods (user_id, food_name, calories, protein_g, carbs_g, fat_g)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, food_name, *per),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM custom_foods WHERE id = ?", (cur.lastrowid,)).fetchone()
        return custom_food_as_search_item(row, viewer_id=user_id)
    finally:
        conn.close()


def save_custom_food(user_id, food_name, calories, protein_g, carbs_g, fat_g, food_id=None):
    """Create/update a shared custom food. Only its creator can edit it."""
    food_name = " ".join(str(food_name or "").split()).strip()
    conn = get_connection()
    try:
        if food_id is not None:
            existing = conn.execute(
                "SELECT * FROM custom_foods WHERE id = ? AND user_id = ?",
                (food_id, user_id),
            ).fetchone()
            if not existing:
                return None, "not_found"
            conflict = conn.execute(
                """SELECT id FROM custom_foods
                   WHERE lower(trim(food_name)) = lower(trim(?)) AND id <> ?""",
                (food_name, food_id),
            ).fetchone()
            if conflict:
                return None, "duplicate"
            conn.execute(
                """UPDATE custom_foods
                   SET food_name = ?, calories = ?, protein_g = ?, carbs_g = ?, fat_g = ?
                   WHERE id = ? AND user_id = ?""",
                (food_name, calories, protein_g, carbs_g, fat_g, food_id, user_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM custom_foods WHERE id = ?", (food_id,)).fetchone()
            return custom_food_as_search_item(row, viewer_id=user_id), "updated"

        existing = conn.execute(
            "SELECT * FROM custom_foods WHERE lower(trim(food_name)) = lower(trim(?)) LIMIT 1",
            (food_name,),
        ).fetchone()
        if existing:
            return custom_food_as_search_item(existing, viewer_id=user_id), "duplicate"

        cur = conn.execute(
            """INSERT INTO custom_foods
               (user_id, food_name, calories, protein_g, carbs_g, fat_g)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, food_name, calories, protein_g, carbs_g, fat_g),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM custom_foods WHERE id = ?", (cur.lastrowid,)).fetchone()
        return custom_food_as_search_item(row, viewer_id=user_id), "created"
    finally:
        conn.close()


def custom_food_as_search_item(row, viewer_id=None):
    """Shape a shared custom-food row like a built-in food."""
    return {
        "id": f"custom-{row['id']}", "custom_id": row["id"],
        "Food_Item": row["food_name"], "Category": "Custom foods", "Meal_Type": "",
        "Calories": row["calories"], "Protein_g": row["protein_g"],
        "Carbs_g": row["carbs_g"], "Fat_g": row["fat_g"], "Custom": True,
        "Owner": row["user_id"], "CanEdit": viewer_id is not None and row["user_id"] == viewer_id,
    }


def get_custom_foods(user_id):
    """Return the complete shared custom-food library for a logged-in viewer."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM custom_foods ORDER BY food_name COLLATE NOCASE"
        ).fetchall()
        return [custom_food_as_search_item(r, viewer_id=user_id) for r in rows]
    finally:
        conn.close()


def delete_custom_food(food_id, user_id):
    """Only the creator can remove a shared custom food."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM custom_foods WHERE id = ? AND user_id = ?",
                           (food_id, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def get_food_logs_for_date(user_id, log_date):
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM food_logs WHERE user_id = ? AND log_date = ?
               ORDER BY id ASC""",
            (user_id, log_date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_food_log(food_id, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM food_logs WHERE id = ? AND user_id = ?", (food_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def macros_for_date(user_id, log_date):
    entries = get_food_logs_for_date(user_id, log_date)
    return {
        "date": log_date,
        "entries": entries,
        "total_calories": round(sum(e["calories"] for e in entries), 1),
        "total_protein_g": round(sum(e["protein_g"] for e in entries), 1),
        "total_carbs_g": round(sum(e["carbs_g"] for e in entries), 1),
        "total_fat_g": round(sum(e["fat_g"] for e in entries), 1),
    }


# --------------------------------------------------- day summaries / history ----
def _weight_on(user_row, weight_logs, log_date):
    """Weight to use for a given day: the latest logged on or before it, else the profile's."""
    dates = [w["log_date"] for w in weight_logs]
    i = bisect.bisect_right(dates, log_date)
    return weight_logs[i - 1]["weight_kg"] if i else user_row["weight_kg"]


def _verdict(consumed, burned, maintenance):
    """Plain-language class of the day: how eating compared with what the body needed."""
    if consumed <= 0 and burned <= 0:
        return "no_data"
    if consumed <= 0:
        return "activity_only"
    diff = consumed - maintenance
    if abs(diff) <= 150:
        return "balanced"
    return "surplus" if diff > 0 else "deficit"


def _day_row(user_row, weight_logs, log_date, food, act):
    """One day's numbers. `food` = (kcal, protein, carbs, fat, entries), `act` = (kcal, min, sessions)."""
    consumed, protein, carbs, fat, meals = food
    burned, minutes, sessions = act
    profile = {**user_row, "weight_kg": _weight_on(user_row, weight_logs, log_date)}
    target = goals.daily_target(profile, burned, consumed)
    maintenance = goals.maintenance(profile, burned)
    d = date.fromisoformat(log_date)
    return {
        "date": log_date, "weekday": d.strftime("%a"),
        "consumed": round(consumed), "burned": round(burned),
        "net": round(consumed - burned),                    # eaten minus exercise burn
        "target": target["target"], "remaining": target["remaining"],
        "percent": target["percent"], "bmr": target["bmr"],
        "maintenance": maintenance,                         # estimated kcal to hold weight
        "balance": round(consumed - maintenance),           # + = gained (surplus), - = deficit
        "verdict": _verdict(consumed, burned, maintenance),
        "protein_g": round(protein), "carbs_g": round(carbs), "fat_g": round(fat),
        "meals": meals, "sessions": sessions, "minutes": round(minutes),
        "logged": bool(meals or sessions),
    }


def _aggregates(user_id, start, end):
    conn = get_connection()
    try:
        food = {r["log_date"]: (r["kcal"], r["p"], r["c"], r["f"], r["n"]) for r in conn.execute(
            """SELECT log_date, SUM(calories) kcal, SUM(protein_g) p, SUM(carbs_g) c,
                      SUM(fat_g) f, COUNT(*) n FROM food_logs
               WHERE user_id = ? AND log_date BETWEEN ? AND ? GROUP BY log_date""",
            (user_id, start, end))}
        act = {r["log_date"]: (r["kcal"], r["mins"], r["n"]) for r in conn.execute(
            """SELECT log_date, SUM(calories_burned) kcal, SUM(duration_min) mins, COUNT(*) n
               FROM activity_logs WHERE user_id = ? AND log_date BETWEEN ? AND ?
               GROUP BY log_date""", (user_id, start, end))}
    finally:
        conn.close()
    return food, act


def nutrition_history(user_id, days=7, end=None):
    """Per-day eaten / burned / net / target for the last `days` days ending at `end`
    (default today), oldest first. Nothing is ever deleted, so any past day can be looked up."""
    days = max(1, min(90, int(days)))
    end_d = date.fromisoformat(end) if end else date.today()
    start_d = end_d - timedelta(days=days - 1)
    user_row = get_user_by_id(user_id)
    weights = get_weight_logs_for_user(user_id)
    food, act = _aggregates(user_id, start_d.isoformat(), end_d.isoformat())
    rows = []
    for i in range(days):
        ds = (start_d + timedelta(days=i)).isoformat()
        rows.append(_day_row(user_row, weights, ds, food.get(ds, (0, 0, 0, 0, 0)),
                             act.get(ds, (0, 0, 0))))
    logged = [r for r in rows if r["logged"]]
    eaten_days = [r for r in rows if r["consumed"] > 0]
    return {
        "days": rows, "start": start_d.isoformat(), "end": end_d.isoformat(),
        "summary": {
            "logged_days": len(logged),
            "avg_consumed": round(sum(r["consumed"] for r in eaten_days) / len(eaten_days)) if eaten_days else 0,
            "avg_burned": round(sum(r["burned"] for r in rows if r["burned"]) /
                                max(1, len([r for r in rows if r["burned"]]))),
            "total_consumed": sum(r["consumed"] for r in rows),
            "total_burned": sum(r["burned"] for r in rows),
            "total_balance": sum(r["balance"] for r in eaten_days),
        },
    }


def nutrition_day(user_id, log_date):
    """Everything about one date: totals, macros, the day's meals and workouts, the calorie
    target and whether the day ended in a surplus or a deficit."""
    user_row = get_user_by_id(user_id)
    entries = get_food_logs_for_date(user_id, log_date)
    activities = [l for l in get_logs_for_user(user_id) if l["log_date"] == log_date]
    food = (sum(e["calories"] for e in entries), sum(e["protein_g"] for e in entries),
            sum(e["carbs_g"] for e in entries), sum(e["fat_g"] for e in entries), len(entries))
    act = (sum(a["calories_burned"] for a in activities),
           sum(a["duration_min"] for a in activities), len(activities))
    row = _day_row(user_row, get_weight_logs_for_user(user_id), log_date, food, act)
    by_meal = {}
    for e in entries:
        by_meal[e["meal"]] = by_meal.get(e["meal"], 0) + e["calories"]
    row["by_meal"] = [{"meal": k, "calories": round(v)} for k, v in by_meal.items()]
    row["entries"] = entries
    row["activities"] = activities
    row["goal"] = user_row["goal"]
    return row


def personal_activity_summary(user_id):
    """Turns the user's own activity_logs into the same buckets/vocabulary as
    student_insights.json (built from student_lifestyle_dataset.csv), so the Student
    Insights page can show where *this* person actually falls - and, for the interactive
    charts, their last 14 days, activity mix, weekday pattern and mood mix. Mood is used as a
    loose stand-in for the survey's self-reported stress level (there's no real stress field
    in this app); it's an approximation, not a validated measurement, and the frontend copy
    says so."""
    logs = get_logs_for_user(user_id)
    if not logs:
        return None

    today = date.today()
    distinct_days = len({l["log_date"] for l in logs})
    total_minutes = sum(l["duration_min"] for l in logs)
    total_hours = total_minutes / 60.0
    avg_daily_hours = round(total_hours / distinct_days, 2) if distinct_days else 0.0

    if avg_daily_hours < 1:
        bucket = "< 1 hr/day"
    elif avg_daily_hours < 2:
        bucket = "1-2 hrs/day"
    elif avg_daily_hours < 3:
        bucket = "2-3 hrs/day"
    else:
        bucket = "3+ hrs/day"

    mood_counts = Counter(l["mood"] for l in logs)
    dominant_mood = mood_counts.most_common(1)[0][0]
    mood_to_stress = {"Great": "Low", "Happy": "Low", "Okay": "Moderate",
                       "Tired": "High", "Stressed": "High"}

    # --- last 14 calendar days (zeros included, so gaps are visible) ---
    per_day = {}
    for l in logs:
        d = per_day.setdefault(l["log_date"], {"minutes": 0.0, "kcal": 0.0, "sessions": 0})
        d["minutes"] += l["duration_min"]
        d["kcal"] += l["calories_burned"]
        d["sessions"] += 1
    daily = []
    for i in range(13, -1, -1):
        ds = (today - timedelta(days=i)).isoformat()
        d = per_day.get(ds, {"minutes": 0.0, "kcal": 0.0, "sessions": 0})
        daily.append({"date": ds, "weekday": (today - timedelta(days=i)).strftime("%a"),
                      "minutes": round(d["minutes"]), "hours": round(d["minutes"] / 60, 2),
                      "kcal": round(d["kcal"]), "sessions": d["sessions"]})
    last7, prev7 = daily[7:], daily[:7]

    # --- activity mix ---
    mix = {}
    for l in logs:
        a = mix.setdefault(l["activity_type"], {"activity": l["activity_type"], "minutes": 0.0,
                                                "kcal": 0.0, "sessions": 0})
        a["minutes"] += l["duration_min"]
        a["kcal"] += l["calories_burned"]
        a["sessions"] += 1
    activity_mix = sorted(({**a, "minutes": round(a["minutes"]), "kcal": round(a["kcal"])}
                           for a in mix.values()), key=lambda a: -a["minutes"])

    # --- which weekdays you train (all-time minutes) ---
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_minutes = [0.0] * 7
    for ds, d in per_day.items():
        week_minutes[date.fromisoformat(ds).weekday()] += d["minutes"]
    weekday_pattern = [{"day": n, "minutes": round(v)} for n, v in zip(names, week_minutes)]

    best_ds = max(per_day, key=lambda k: per_day[k]["minutes"])
    best = per_day[best_ds]
    moods_order = ["Great", "Happy", "Okay", "Tired", "Stressed"]

    return {
        "logged_days": distinct_days,
        "total_sessions": len(logs),
        "avg_daily_activity_hours": avg_daily_hours,
        "activity_bucket": bucket,
        "dominant_mood": dominant_mood,
        "mapped_stress_level": mood_to_stress.get(dominant_mood, "Moderate"),
        "total_minutes": round(total_minutes),
        "total_kcal": round(sum(l["calories_burned"] for l in logs)),
        "current_streak": _streak_from_dates([date.fromisoformat(k) for k in per_day]),
        "daily": daily,
        "active_days_last7": sum(1 for d in last7 if d["minutes"] > 0),
        "minutes_last7": sum(d["minutes"] for d in last7),
        "minutes_prev7": sum(d["minutes"] for d in prev7),
        "avg_hours_per_calendar_day_last7": round(sum(d["minutes"] for d in last7) / 60 / 7, 2),
        "activity_mix": activity_mix,
        "favorite_activity": activity_mix[0]["activity"],
        "weekday_pattern": weekday_pattern,
        "mood_counts": [{"mood": k, "count": mood_counts.get(k, 0)} for k in moods_order],
        "best_day": {"date": best_ds, "weekday": date.fromisoformat(best_ds).strftime("%A"),
                     "minutes": round(best["minutes"]), "kcal": round(best["kcal"])},
    }


def leaderboard(limit=20, period="all"):
    """period="week"/"month" counts a rolling window (today included) so newcomers can
    compete; period="all" counts everything. Each row also gets this period's favorite
    activity, average kcal/session, how many of the period's days had a session logged
    (consistency), and the % change vs. the same-length window right before this one."""
    today = date.today()
    window = {"week": 7, "month": 30}.get(period)
    since = (today - timedelta(days=window - 1)).isoformat() if window else "0000-01-01"
    prev_since, prev_until = None, None
    if window:
        prev_since = (today - timedelta(days=2 * window - 1)).isoformat()
        prev_until = (today - timedelta(days=window)).isoformat()

    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT u.id, u.name,
                      COALESCE(SUM(a.calories_burned), 0) AS total_calories,
                      COALESCE(SUM(a.duration_min), 0) AS total_minutes,
                      COUNT(a.id) AS sessions
               FROM users u
               LEFT JOIN activity_logs a ON a.user_id = u.id AND a.log_date >= ?
               GROUP BY u.id
               ORDER BY total_calories DESC, sessions DESC, u.name ASC
               LIMIT ?""",
            (since, limit),
        ).fetchall()
        prev_totals = {}
        if window:
            prev_totals = {r["user_id"]: r["kcal"] for r in conn.execute(
                """SELECT user_id, SUM(calories_burned) AS kcal FROM activity_logs
                   WHERE log_date >= ? AND log_date <= ? GROUP BY user_id""",
                (prev_since, prev_until))}
    finally:
        conn.close()

    board = []
    for i, r in enumerate(rows):
        logs = [l for l in get_logs_for_user(r["id"]) if l["log_date"] >= since]
        log_dates = [date.fromisoformat(l["log_date"]) for l in logs]
        mix = Counter()
        for l in logs:
            mix[l["activity_type"]] += l["calories_burned"]
        favorite = mix.most_common(1)[0][0] if mix else None

        trend = None
        if window and r["id"] in prev_totals and prev_totals[r["id"]] > 0:
            trend = round(100 * (r["total_calories"] - prev_totals[r["id"]]) / prev_totals[r["id"]])

        active_days = len({l["log_date"] for l in logs})
        period_days = window if window else max(1, (today - _joined_on(r["id"])).days + 1)
        board.append({
            "rank": i + 1,
            "user_id": r["id"],
            "name": r["name"],
            "total_calories": round(r["total_calories"], 1),
            "total_minutes": round(r["total_minutes"]),
            "sessions": r["sessions"],
            "avg_kcal_per_session": round(r["total_calories"] / r["sessions"]) if r["sessions"] else 0,
            "favorite_activity": favorite,
            "streak": _streak_from_dates(log_dates),
            "active_days": active_days,
            "consistency_pct": round(100 * active_days / min(period_days, today.toordinal() -
                                     _joined_on(r["id"]).toordinal() + 1)) if active_days else 0,
            "trend_pct": trend,
        })
    return board


def _joined_on(user_id):
    row = get_user_by_id(user_id)
    try:
        return datetime.fromisoformat(row["created_at"]).date()
    except (ValueError, TypeError):
        return date.today()


def leaderboard_community_stats(board, period):
    """Summary strip above the table: how the whole community did this period."""
    active = [r for r in board if r["sessions"] > 0]
    total_kcal = sum(r["total_calories"] for r in board)
    return {
        "participants": len(board),
        "active_participants": len(active),
        "total_calories": round(total_kcal),
        "total_sessions": sum(r["sessions"] for r in board),
        "avg_streak": round(sum(r["streak"] for r in active) / len(active), 1) if active else 0,
        "top_activity": Counter(r["favorite_activity"] for r in active if r["favorite_activity"]).most_common(1)[0][0]
                        if active else None,
    }


# --------------------------------------------------------- unified summaries --
def unified_user_summary(user_id, end_date=None):
    """Single source of truth for cross-page user state and recent progress."""
    user = get_user_by_id(user_id)
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = end - timedelta(days=6)
    logs = get_logs_for_user(user_id)
    recent = [l for l in logs if start.isoformat() <= l["log_date"] <= end.isoformat()]
    foods = get_food_logs_for_date(user_id, end.isoformat())
    weights = get_weight_logs_for_user(user_id)
    current_weight = _weight_on(user, weights, end.isoformat())
    h = user["height_cm"] / 100.0
    bmi = round(current_weight / (h*h), 1) if h > 0 else 0
    consumed = sum(f["calories"] for f in foods)
    burned = sum(l["calories_burned"] for l in recent if l["log_date"] == end.isoformat())
    steps_today = sum(l["steps"] for l in recent if l["log_date"] == end.isoformat())
    total_steps_7 = sum(l["steps"] for l in recent)
    minutes_7 = sum(l["duration_min"] for l in recent)
    sessions_7 = len(recent)
    active_days = len({l["log_date"] for l in recent})
    goal = get_goal_status(user_id, end.isoformat())
    return {
        "user": {**user_public_dict(user), "current_weight_kg": current_weight, "bmi": bmi,
                 "bmi_category": _bmi_category(bmi)},
        "date": end.isoformat(),
        "today": {"calories_consumed": round(consumed, 1), "calories_burned": round(burned, 1),
                  "net_calories": round(consumed-burned, 1), "steps": steps_today},
        "last_7_days": {"sessions": sessions_7, "minutes": round(minutes_7, 1),
                        "steps": total_steps_7, "active_days": active_days,
                        "avg_minutes_per_active_day": round(minutes_7/max(1, active_days), 1)},
        "goal": goal,
        "weight_history_count": len(weights),
    }


def recent_activity_metrics(user_id, days=7, end_date=None):
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = end - timedelta(days=max(1, days)-1)
    logs = [l for l in get_logs_for_user(user_id) if start.isoformat() <= l["log_date"] <= end.isoformat()]
    return {"days": max(1, days), "start": start.isoformat(), "end": end.isoformat(),
            "steps": sum(l["steps"] for l in logs), "minutes": round(sum(l["duration_min"] for l in logs), 1),
            "sessions": len(logs), "active_days": len({l["log_date"] for l in logs})}
