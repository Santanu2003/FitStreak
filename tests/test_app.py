"""Automated tests for FitStreak's API and its duplicate/XSS protections.

Run from the project root — either works, no extra install needed for the first:
    python -m unittest discover -s tests -v
    pytest tests/            (if you have pytest installed)

Every test runs against a throw-away SQLite file, never your real fitstreak.db.
"""
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

import db as db_module  # noqa: E402

_tmp_dir = tempfile.mkdtemp(prefix="fitstreak_tests_")
db_module.DB_PATH = os.path.join(_tmp_dir, "test.db")
db_module.init_db()

import app as flask_app  # noqa: E402  (imported after the DB path is redirected)

USER = {
    "name": "Test User", "email": "test@example.com", "password": "secret123",
    "age": 22, "gender": "Female", "height_cm": 165, "weight_kg": 60,
    "experience_level": 2,
}
TODAY = date.today().isoformat()


class FitStreakTestCase(unittest.TestCase):
    def setUp(self):
        if os.path.exists(db_module.DB_PATH):
            os.remove(db_module.DB_PATH)
        db_module.init_db()
        self.client = flask_app.app.test_client()

    def register(self, **overrides):
        payload = {**USER, **overrides}
        return self.client.post("/api/register", json=payload)


class TestAuth(FitStreakTestCase):
    def test_register_login_logout_flow(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.client.get("/api/me").status_code, 200)
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        r = self.client.post("/api/login", json={"email": USER["email"], "password": USER["password"]})
        self.assertEqual(r.status_code, 200)

    def test_duplicate_email_rejected(self):
        self.register()
        self.assertEqual(self.register(name="Someone Else").status_code, 409)

    def test_bad_password_rejected(self):
        self.register()
        self.client.post("/api/logout")
        r = self.client.post("/api/login", json={"email": USER["email"], "password": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_protected_routes_require_login(self):
        for path in ("/api/dashboard/summary", "/api/activity/history", "/api/weight/history"):
            self.assertEqual(self.client.get(path).status_code, 401, path)


class TestActivityLogs(FitStreakTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def _log(self, **kw):
        body = {"date": TODAY, "activity_type": "Running", "duration_min": 30, "mood": "Great", **kw}
        return self.client.post("/api/activity", json=body)

    def test_same_day_same_activity_updates_instead_of_duplicating(self):
        self.assertEqual(self._log().status_code, 201)
        r = self._log(duration_min=45)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["updated"])
        logs = self.client.get("/api/activity/history").get_json()["logs"]
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["duration_min"], 45)

    def test_client_supplied_calories_are_ignored(self):
        r = self._log(calories_burned=99999)
        self.assertLess(r.get_json()["log"]["calories_burned"], 2000)

    def test_invalid_activity_type_rejected(self):
        r = self._log(activity_type="<script>alert(1)</script>")
        self.assertEqual(r.status_code, 400)

    def test_streak_and_summary(self):
        self._log()
        s = self.client.get("/api/dashboard/summary").get_json()
        self.assertEqual(s["current_streak"], 1)
        self.assertEqual(s["total_sessions"], 1)

    def test_cannot_delete_another_users_log(self):
        self._log()
        log_id = self.client.get("/api/activity/history").get_json()["logs"][0]["id"]
        self.client.post("/api/logout")
        self.register(email="other@example.com", name="Other")
        self.assertEqual(self.client.delete(f"/api/activity/{log_id}").status_code, 404)


class TestFoodLogs(FitStreakTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def _food(self, **kw):
        body = {"date": TODAY, "meal": "Breakfast", "food_name": "Banana", "servings": 1,
                "calories": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.4, **kw}
        return self.client.post("/api/food", json=body)

    def test_same_food_same_meal_same_day_updates_instead_of_duplicating(self):
        self.assertEqual(self._food().status_code, 201)
        r = self._food(servings=2, calories=210)
        self.assertEqual(r.status_code, 200)
        entries = self.client.get(f"/api/food?date={TODAY}").get_json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["calories"], 210)

    def test_same_food_different_meal_is_a_separate_entry(self):
        self._food()
        self._food(meal="Snack")
        entries = self.client.get(f"/api/food?date={TODAY}").get_json()["entries"]
        self.assertEqual(len(entries), 2)

    def test_invalid_meal_rejected(self):
        self.assertEqual(self._food(meal="Midnight").status_code, 400)

    def test_overlong_food_name_rejected(self):
        self.assertEqual(self._food(food_name="x" * 500).status_code, 400)


class TestIndianFoods(FitStreakTestCase):
    """The Indian food list (data/indian_foods.csv) is searchable and internally sane."""

    def names(self, q, limit=30):
        r = self.client.get(f"/api/foods?search={q}&limit={limit}")
        self.assertEqual(r.status_code, 200)
        return [f["Food_Item"].lower() for f in r.get_json()["results"]]

    def test_requested_foods_are_found(self):
        for query, expected in [
            ("paratha", "paratha"), ("mutton curry", "mutton curry"), ("roti", "roti"),
            ("dal", "dal"), ("paneer", "paneer"), ("dosa", "dosa"), ("idli", "idli"),
            ("curd", "curd"), ("gulab jamun", "gulab jamun"), ("jalebi", "jalebi"),
            ("biryani", "biryani"), ("chole", "chole"), ("samosa", "samosa"),
        ]:
            with self.subTest(query=query):
                self.assertTrue(any(expected in n for n in self.names(query)), query)

    def test_mutton_paratha_finds_the_keema_paratha(self):
        self.assertTrue(any("mutton" in n and "paratha" in n for n in self.names("mutton paratha")))

    def test_synonyms_and_spelling_variants(self):
        self.assertTrue(any("roti / chapati" in n for n in self.names("chapati")))
        self.assertTrue(any("curd / dahi" in n for n in self.names("dahi")))
        self.assertTrue(any("mutton curry" in n for n in self.names("goat curry")))
        self.assertTrue(any("idli" in n for n in self.names("idly")))
        self.assertTrue(any("dal tadka" in n for n in self.names("daal")))

    def test_category_search_and_plurals(self):
        for q, cats in (("sweets", {"Indian Sweet", "Bengali Sweet"}),
                        ("snacks", {"Indian Snack"}), ("fish", {"Fish & Seafood"})):
            with self.subTest(q=q):
                results = self.client.get(f"/api/foods?search={q}&limit=10").get_json()["results"]
                self.assertTrue(results)
                self.assertTrue(all(f["Category"] in cats for f in results),
                                [(f["Food_Item"], f["Category"]) for f in results])

    def test_search_matches_word_starts_not_substrings(self):
        # 'egg' used to match 'Veggie Burger' (substring); it must not any more.
        self.assertFalse(any("veggie" in n for n in self.names("egg", limit=50)))

    def test_multiword_query_requires_every_word(self):
        results = self.names("aloo paratha")
        self.assertTrue(results and all("aloo" in n and "paratha" in n for n in results))

    def test_no_match_returns_empty_list(self):
        self.assertEqual(self.names("zzzqqq"), [])

    def test_bengali_dishes_snacks_and_sweets_are_found(self):
        for query, expected in [
            ("luchi", "luchi"), ("kachuri", "kochuri"), ("kochuri", "kachori"), ("aloor dom", "aloor dom"),
            ("shukto", "shukto"), ("mishti doi", "mishti doi"), ("rosogolla", "rasgulla"),
            ("pantua", "pantua"), ("langcha", "langcha"), ("payesh", "payesh"), ("jhalmuri", "jhalmuri"),
            ("kosha mangsho", "kosha mangsho"), ("beguni", "beguni"), ("malpua", "malpua"),
        ]:
            with self.subTest(query=query):
                self.assertTrue(any(expected in n for n in self.names(query)), query)

    def test_fish_and_seafood_section(self):
        for query, expected in [
            ("hilsa", "ilish"), ("hilsha", "ilish"), ("ilish", "hilsa"), ("chingri", "chingri"),
            ("prawn", "prawn"), ("shrimp", "chingri"), ("rui", "rohu"), ("rohu", "rohu"), ("katla", "katla"),
            ("pabda", "pabda"), ("bhetki", "bhetki"), ("pomfret", "pomfret"), ("crab", "crab masala"),
            ("kekda", "crab"), ("surmai", "kingfish"), ("mackerel", "bangda"), ("sardine", "mathi"),
            ("maach", "fish"), ("meen", "meen"),
        ]:
            with self.subTest(query=query):
                self.assertTrue(any(expected in n for n in self.names(query, limit=60)), query)

    def test_hilsa_dishes_are_richer_than_lean_fish(self):
        import nutrition_utils
        by = {f["Food_Item"]: f for f in nutrition_utils._foods}
        hilsa = by["Hilsa / Ilish, Cooked Plain (100 g)"]
        rohu = by["Rohu / Rui, Cooked Plain (100 g)"]
        self.assertGreater(hilsa["Fat_g"], rohu["Fat_g"] * 2)
        self.assertGreater(hilsa["Calories"], rohu["Calories"])

    def test_fish_section_is_large_and_categorised(self):
        import nutrition_utils
        fish = [f for f in nutrition_utils._foods if f["Category"] == "Fish & Seafood"]
        self.assertGreaterEqual(len(fish), 50)

    def test_indian_csv_is_clean_and_consistent(self):
        import csv
        with open(os.path.join(ROOT, "backend", "data", "indian_foods.csv"), encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows), 150)
        seen = set()
        for r in rows:
            name = r["Food_Item"]
            self.assertNotIn(name.lower(), seen, f"duplicate: {name}")
            seen.add(name.lower())
            self.assertLessEqual(len(name), 120)
            cal, p, c, fat = (float(r[k]) for k in ("Calories", "Protein_g", "Carbs_g", "Fat_g"))
            self.assertTrue(0 <= cal <= 1500 and min(p, c, fat) >= 0, name)
            implied = 4 * p + 4 * c + 9 * fat
            self.assertAlmostEqual(cal, implied, delta=max(8, 0.1 * implied), msg=name)

    def test_indian_foods_do_not_collide_with_general_dataset_names(self):
        import nutrition_utils
        import json
        with open(os.path.join(ROOT, "backend", "data", "foods.json"), encoding="utf-8") as f:
            general = {x["Food_Item"].lower() for x in json.load(f)}
        indian = {x["Food_Item"].lower() for x in nutrition_utils._foods if isinstance(x["id"], int) and x["id"] >= 10001}
        self.assertFalse(general & indian)

    def test_every_builtin_food_passes_entry_validation(self):
        import nutrition_utils
        for food in nutrition_utils._foods:
            errs = nutrition_utils.check_entry_numbers(
                1, food["Calories"], food["Protein_g"], food["Carbs_g"], food["Fat_g"])
            self.assertEqual(errs, [], food["Food_Item"])


class TestCustomFoods(FitStreakTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def _log(self, client=None, **kw):
        body = {"date": TODAY, "meal": "Dinner", "food_name": "Mom's Mutton Paratha",
                "servings": 2, "calories": 700, "protein_g": 40, "carbs_g": 60, "fat_g": 32,
                "save_custom": True, **kw}
        return (client or self.client).post("/api/food", json=body)

    def _search(self, q, client=None):
        return (client or self.client).get(f"/api/foods?search={q}").get_json()["results"]

    def test_manual_food_is_saved_per_serving_and_shows_in_search(self):
        r = self._log()
        self.assertEqual(r.status_code, 201)
        saved = r.get_json()["saved_custom_food"]
        self.assertEqual(saved["Calories"], 350)      # 700 kcal for 2 servings -> 350 each
        self.assertEqual(saved["Fat_g"], 16)
        results = self._search("mom")
        self.assertEqual(results[0]["Food_Item"], "Mom's Mutton Paratha")
        self.assertTrue(results[0]["Custom"])

    def test_custom_foods_rank_first_for_their_owner(self):
        self._log(food_name="Paratha Special", servings=1, calories=300, protein_g=8, carbs_g=40, fat_g=12)
        self.assertEqual(self._search("paratha")[0]["Food_Item"], "Paratha Special")

    def test_custom_foods_are_private_to_each_user(self):
        self._log()
        other = flask_app.app.test_client()
        other.post("/api/register", json={**USER, "email": "other@example.com"})
        self.assertEqual([f for f in self._search("mom", other) if f.get("Custom")], [])
        anonymous = flask_app.app.test_client()
        self.assertEqual([f for f in self._search("mom", anonymous) if f.get("Custom")], [])

    def test_saving_same_name_again_updates_it_case_insensitively(self):
        self._log()
        self._log(food_name="mom's mutton paratha", servings=1, calories=500, protein_g=30, carbs_g=45, fat_g=20)
        foods = self.client.get("/api/custom-foods").get_json()["foods"]
        self.assertEqual(len(foods), 1)
        self.assertEqual(foods[0]["Calories"], 500)

    def test_not_saved_unless_requested(self):
        self._log(save_custom=False)
        self.assertEqual(self.client.get("/api/custom-foods").get_json()["foods"], [])

    def test_builtin_food_names_are_not_duplicated_into_my_foods(self):
        self._log(food_name="Masala Dosa (1 medium)", servings=1, calories=310, protein_g=6, carbs_g=45, fat_g=12)
        self.assertEqual(self.client.get("/api/custom-foods").get_json()["foods"], [])

    def test_delete_custom_food(self):
        self._log()
        fid = self.client.get("/api/custom-foods").get_json()["foods"][0]["custom_id"]
        self.assertEqual(self.client.delete(f"/api/custom-foods/{fid}").status_code, 200)
        self.assertEqual(self.client.get("/api/custom-foods").get_json()["foods"], [])
        self.assertEqual(self.client.delete(f"/api/custom-foods/{fid}").status_code, 404)

    def test_cannot_delete_someone_elses_custom_food(self):
        self._log()
        fid = self.client.get("/api/custom-foods").get_json()["foods"][0]["custom_id"]
        other = flask_app.app.test_client()
        other.post("/api/register", json={**USER, "email": "other@example.com"})
        self.assertEqual(other.delete(f"/api/custom-foods/{fid}").status_code, 404)
        self.assertEqual(len(self.client.get("/api/custom-foods").get_json()["foods"]), 1)

    def test_custom_food_endpoints_require_login(self):
        anonymous = flask_app.app.test_client()
        self.assertEqual(anonymous.get("/api/custom-foods").status_code, 401)
        self.assertEqual(anonymous.delete("/api/custom-foods/1").status_code, 401)

    def test_invalid_entry_is_not_saved_to_my_foods(self):
        self.assertEqual(self._log(calories=20).status_code, 400)   # macros imply ~600 kcal
        self.assertEqual(self.client.get("/api/custom-foods").get_json()["foods"], [])


class TestFoodEntryValidation(FitStreakTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def _post(self, **kw):
        body = {"date": TODAY, "meal": "Lunch", "food_name": "Dal Tadka", "servings": 1,
                "calories": 165, "protein_g": 8, "carbs_g": 20, "fat_g": 6, **kw}
        return self.client.post("/api/food", json=body)

    def test_good_entry_accepted(self):
        self.assertEqual(self._post().status_code, 201)

    def test_calories_that_contradict_macros_rejected(self):
        r = self._post(calories=20)                    # macros add up to ~166 kcal
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._post(calories=1650).status_code, 400)   # 10x slip
        self.assertIn("double-check", r.get_json()["error"])

    def test_negative_and_absurd_values_rejected(self):
        for bad in ({"calories": -5}, {"protein_g": -1}, {"servings": 0}, {"servings": 500},
                    {"calories": 90000}, {"fat_g": 5000}):
            with self.subTest(bad=bad):
                self.assertEqual(self._post(**bad).status_code, 400)

    def test_zero_calorie_items_still_allowed(self):
        self.assertEqual(self._post(food_name="Black Coffee", calories=0, protein_g=0, carbs_g=0, fat_g=0).status_code, 201)


class TestNetCalories(FitStreakTestCase):
    def test_net_is_intake_minus_burn_for_today(self):
        self.register()
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "Running", "duration_min": 30, "mood": "Okay"})
        self.client.post("/api/food", json={"date": TODAY, "meal": "Lunch", "food_name": "Rice", "servings": 1,
                                             "calories": 400, "protein_g": 8, "carbs_g": 80, "fat_g": 1})
        net = self.client.get("/api/dashboard/summary").get_json()["net_calories_today"]
        self.assertEqual(net["consumed"], 400)
        self.assertGreater(net["burned"], 0)
        self.assertAlmostEqual(net["net"], net["consumed"] - net["burned"], places=1)

    def test_empty_day_is_zero(self):
        self.register()
        net = self.client.get("/api/dashboard/summary").get_json()["net_calories_today"]
        self.assertEqual(net, {"consumed": 0, "burned": 0, "net": 0})


class TestWeightTracking(FitStreakTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def test_same_date_updates_instead_of_duplicating(self):
        self.client.post("/api/weight", json={"date": "2026-09-20", "weight_kg": 62})
        r = self.client.post("/api/weight", json={"date": "2026-09-20", "weight_kg": 61})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.client.get("/api/weight/history").get_json()["logs"]), 1)

    def test_latest_dated_weight_becomes_current_weight(self):
        self.client.post("/api/weight", json={"date": "2026-09-24", "weight_kg": 58})
        self.client.post("/api/weight", json={"date": "2026-09-10", "weight_kg": 65})  # older, logged later
        self.assertEqual(self.client.get("/api/me").get_json()["user"]["weight_kg"], 58)

    def test_bmi_history_matches_height(self):
        self.client.post("/api/weight", json={"date": "2026-09-20", "weight_kg": 60})
        point = self.client.get("/api/weight/history").get_json()["bmi_history"][0]
        self.assertAlmostEqual(point["bmi"], 60 / (1.65 ** 2), places=1)

    def test_out_of_range_weight_rejected(self):
        self.assertEqual(self.client.post("/api/weight", json={"weight_kg": 5}).status_code, 400)
        self.assertEqual(self.client.post("/api/weight", json={"weight_kg": 900}).status_code, 400)

    def test_delete_weight(self):
        self.client.post("/api/weight", json={"date": "2026-09-20", "weight_kg": 60})
        log_id = self.client.get("/api/weight/history").get_json()["logs"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/weight/{log_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/weight/{log_id}").status_code, 404)


class TestLeaderboard(FitStreakTestCase):
    def test_ranked_by_calories(self):
        self.register(name="Low", email="low@x.com")
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "Yoga", "duration_min": 20, "mood": "Okay"})
        self.client.post("/api/logout")
        self.register(name="High", email="high@x.com")
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "HIIT", "duration_min": 60, "mood": "Okay"})
        board = self.client.get("/api/leaderboard").get_json()["leaderboard"]
        self.assertEqual([r["name"] for r in board][:2], ["High", "Low"])

    def test_html_in_name_is_stored_verbatim_and_escaped_by_the_frontend(self):
        # The API never mangles data; escaping happens at render time (see TestFrontendEscaping).
        evil = "<img src=x onerror=alert(1)>"
        self.register(name=evil)
        board = self.client.get("/api/leaderboard").get_json()["leaderboard"]
        self.assertEqual(board[0]["name"], evil)


class TestModelsAndData(FitStreakTestCase):
    def test_calorie_prediction(self):
        r = self.client.post("/api/predict/calories", json={
            "age": 22, "gender": "Female", "weight_kg": 60, "height_cm": 165,
            "workout_type": "Running", "duration_min": 45, "avg_bpm": 145, "max_bpm": 175,
            "resting_bpm": 65, "frequency": 4, "experience_level": 2})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.get_json()["predicted_calories"], 0)

    def test_health_benchmark_percentiles_in_range(self):
        r = self.client.post("/api/health-benchmark", json={
            "age": 30, "daily_steps": 9000, "sleep_hours": 7, "exercise_hours_per_week": 4})
        for value in r.get_json()["your_percentiles"].values():
            self.assertTrue(0 <= value <= 100)

    def test_health_benchmark_with_bmi_adds_bmi_percentile(self):
        r = self.client.post("/api/health-benchmark", json={
            "age": 30, "daily_steps": 9000, "sleep_hours": 7, "exercise_hours_per_week": 4, "bmi": 24.5})
        body = r.get_json()
        self.assertIn("bmi", body["your_percentiles"])
        self.assertTrue(0 <= body["your_percentiles"]["bmi"] <= 100)
        self.assertEqual(body["your_bmi"], 24.5)
        for metric in ("daily_steps", "sleep_hours", "exercise_hours_per_week"):
            self.assertIsNotNone(body["top_quartile_in_bracket"][metric])

    def test_exercise_search_filters(self):
        r = self.client.get("/api/exercises?body_part=Chest&per_page=5").get_json()
        self.assertTrue(all(e["BodyPart"] == "Chest" for e in r["results"]))

    def test_food_search(self):
        r = self.client.get("/api/foods?search=egg")
        self.assertEqual(r.status_code, 200)


class TestCalorieGoal(FitStreakTestCase):
    def test_bmr_formula(self):
        import goals
        # Mifflin-St Jeor: 10*60 + 6.25*165 - 5*22 - 161 = 1360.25
        self.assertAlmostEqual(goals.bmr("Female", 60, 165, 22), 1360.25, places=2)
        self.assertAlmostEqual(goals.bmr("Male", 60, 165, 22), 1526.25, places=2)

    def test_target_adds_logged_exercise_and_goal_offset(self):
        import goals
        user = {"gender": "Female", "weight_kg": 60, "height_cm": 165, "age": 22, "goal": "maintain"}
        base = goals.daily_target(user, 0, 0)["target"]
        self.assertEqual(goals.daily_target(user, 300, 0)["target"], base + 300)
        user["goal"] = "gain"
        self.assertEqual(goals.daily_target(user, 0, 0)["target"], base + 300)

    def test_target_never_below_resting_needs(self):
        import goals
        user = {"gender": "Female", "weight_kg": 45, "height_cm": 150, "age": 30, "goal": "lose"}
        result = goals.daily_target(user, 0, 0)
        self.assertGreaterEqual(result["target"], result["bmr"])

    def test_goal_endpoints(self):
        self.register()
        self.assertEqual(self.client.get("/api/goal").get_json()["selected"], "maintain")
        r = self.client.post("/api/goal", json={"goal": "gain"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/me").get_json()["user"]["goal"], "gain")
        self.assertEqual(self.client.post("/api/goal", json={"goal": "bulk-forever"}).status_code, 400)

    def test_no_weight_loss_target_for_under_18(self):
        self.register(age=16)
        self.assertEqual(self.client.post("/api/goal", json={"goal": "lose"}).status_code, 400)
        self.assertEqual(self.client.post("/api/goal", json={"goal": "maintain"}).status_code, 200)

    def test_goal_reflects_food_and_exercise_today(self):
        self.register()
        self.client.post("/api/food", json={"date": TODAY, "meal": "Lunch", "food_name": "Rice", "servings": 1,
                                             "calories": 500, "protein_g": 8, "carbs_g": 80, "fat_g": 1})
        g = self.client.get("/api/goal").get_json()
        self.assertEqual(g["consumed"], 500)
        self.assertEqual(g["remaining"], g["target"] - 500)
        self.assertEqual(self.client.get("/api/dashboard/summary").get_json()["calorie_goal"]["target"], g["target"])


class TestStreakNudge(FitStreakTestCase):
    def test_logged_today_flag(self):
        self.register()
        self.assertFalse(self.client.get("/api/dashboard/summary").get_json()["logged_today"])
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "Walking", "duration_min": 20, "mood": "Okay"})
        self.assertTrue(self.client.get("/api/dashboard/summary").get_json()["logged_today"])

    def test_logged_only_yesterday_keeps_streak_but_not_logged_today(self):
        self.register()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.client.post("/api/activity", json={"date": yesterday, "activity_type": "Walking", "duration_min": 20, "mood": "Okay"})
        s = self.client.get("/api/dashboard/summary").get_json()
        self.assertEqual(s["current_streak"], 1)
        self.assertFalse(s["logged_today"])


class TestWeeklyLeaderboard(FitStreakTestCase):
    def test_week_excludes_old_activity_but_all_time_includes_it(self):
        self.register(name="Veteran", email="vet@x.com")
        old = (date.today() - timedelta(days=30)).isoformat()
        self.client.post("/api/activity", json={"date": old, "activity_type": "HIIT", "duration_min": 90, "mood": "Okay"})
        self.client.post("/api/logout")
        self.register(name="Newcomer", email="new@x.com")
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "Yoga", "duration_min": 20, "mood": "Okay"})

        week = self.client.get("/api/leaderboard?period=week").get_json()["leaderboard"]
        self.assertEqual(week[0]["name"], "Newcomer")
        allt = self.client.get("/api/leaderboard?period=all").get_json()["leaderboard"]
        self.assertEqual(allt[0]["name"], "Veteran")

    def test_invalid_period_rejected(self):
        self.assertEqual(self.client.get("/api/leaderboard?period=decade").status_code, 400)


class TestDatabaseMigration(unittest.TestCase):
    def test_old_database_without_goal_column_is_upgraded_in_place(self):
        path = os.path.join(tempfile.mkdtemp(prefix="fitstreak_mig_"), "old.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL, age INTEGER NOT NULL, gender TEXT NOT NULL, height_cm REAL NOT NULL,
              weight_kg REAL NOT NULL, experience_level INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT (datetime('now')));
            INSERT INTO users (name, email, password_hash, age, gender, height_cm, weight_kg)
              VALUES ('Old User', 'old@x.com', 'x', 30, 'Male', 180, 80);
        """)
        conn.commit()
        conn.close()

        previous = db_module.DB_PATH
        db_module.DB_PATH = path
        try:
            db_module.init_db()
            db_module.init_db()  # running twice must be harmless
            conn = db_module.get_connection()
            row = conn.execute("SELECT name, goal FROM users").fetchone()
            conn.close()
            self.assertEqual((row["name"], row["goal"]), ("Old User", "maintain"))
        finally:
            db_module.DB_PATH = previous


@unittest.skipUnless(shutil.which("node"), "Node.js not installed — skipping offline-chart check")
class TestOfflineCharts(unittest.TestCase):
    def test_minicharts_render_every_chart_shape(self):
        r = subprocess.run(["node", os.path.join(ROOT, "tests", "minicharts_check.js")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ALL OK", r.stdout)


class TestFrontendEscaping(unittest.TestCase):
    """Static regression check: user-controlled fields must never be interpolated into
    innerHTML templates without escapeHtml()."""

    def test_user_fields_are_escaped(self):
        with open(os.path.join(ROOT, "frontend", "js", "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("function escapeHtml", js)
        for unsafe in (r"\$\{r\.name\}", r"\$\{entry\.food_name\}", r"\$\{entry\.meal\}",
                       r"\$\{log\.activity_type\}", r"\$\{log\.mood\}",
                       r"\$\{f\.Food_Item\}", r"\$\{f\.Category\}"):
            self.assertIsNone(re.search(unsafe, js), f"unescaped {unsafe} found in app.js")


class TestBrandAssets(unittest.TestCase):
    """The logo must be served (favicon, sidebar, login) and the old stats panel must be gone."""

    def setUp(self):
        self.client = flask_app.app.test_client()

    def test_logo_and_favicon_files_are_served(self):
        for path, mime in (("/assets/logo-mark.svg", "image/svg+xml"),
                           ("/assets/favicon.svg", "image/svg+xml"),
                           ("/assets/favicon-32.png", "image/png"),
                           ("/assets/apple-touch-icon.png", "image/png"),
                           ("/favicon.ico", "image/")):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)
            self.assertIn(mime, res.headers["Content-Type"], path)
            res.close()

    def test_index_links_favicon_and_uses_logo(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('rel="icon"', html)
        self.assertIn("/assets/favicon.svg", html)
        self.assertIn('rel="apple-touch-icon"', html)
        self.assertIn('class="brand-logo" src="/assets/logo-mark.svg"', html)

    def test_login_screen_has_no_stats_panel(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("auth-side", html)
        self.assertNotIn("690,000+", html)
        for element_id in ("login-form", "register-form", "login-error", "register-error"):
            self.assertIn(f'id="{element_id}"', html)


if __name__ == "__main__":
    unittest.main()

class TestDynamicConsistency(FitStreakTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def test_config_is_single_source_of_truth(self):
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(len(data["activity_types"]), 10)
        self.assertIn("datasets", data)
        self.assertGreater(data["datasets"]["exercise_count"], 0)
        self.assertGreater(data["datasets"]["food_count"], 0)

    def test_unified_summary_reflects_logged_activity(self):
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "Running",
                                                  "duration_min": 30, "steps": 3000, "mood": "Great"})
        r = self.client.get("/api/user/summary")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["today"]["steps"], 3000)
        self.assertEqual(data["last_7_days"]["sessions"], 1)

    def test_food_name_variants_do_not_create_duplicate(self):
        body = {"date": TODAY, "meal": "Breakfast", "food_name": "  Banana  ",
                "servings": 1, "calories": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.4}
        self.assertEqual(self.client.post("/api/food", json=body).status_code, 201)
        body["food_name"] = "banana"
        body["calories"] = 110
        r = self.client.post("/api/food", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["updated"])
        entries = self.client.get(f"/api/food?date={TODAY}").get_json()["entries"]
        self.assertEqual(len(entries), 1)

    def test_predict_profile_is_dynamic(self):
        r = self.client.get("/api/predict/profile")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["profile"]["weight_kg"], USER["weight_kg"])
        self.assertIn("model", data)

    def test_personal_benchmark_uses_activity_logs(self):
        self.client.post("/api/activity", json={"date": TODAY, "activity_type": "Walking",
                                                  "duration_min": 60, "steps": 7000, "mood": "Okay"})
        r = self.client.get("/api/health-benchmark/personal")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["daily_steps"], 1000)
        self.assertEqual(data["exercise_hours_per_week"], 1.0)
