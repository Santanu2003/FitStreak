"""Daily calorie target from the user's profile, goal and today's logged exercise.

Uses the Mifflin-St Jeor equation for resting energy (BMR). The target adds a light
day-to-day baseline (BMR x 1.2) plus whatever exercise was logged today, then nudges it
for the chosen goal. It is an estimate for motivation, not medical or dietetic advice.
"""

GOAL_OFFSETS = {"lose": -400, "maintain": 0, "gain": 300}
GOAL_LABELS = {
    "lose": "Lose weight (−400 kcal/day)",
    "maintain": "Maintain weight",
    "gain": "Build muscle (+300 kcal/day)",
}
BASELINE_FACTOR = 1.2   # everyday life without logged workouts; exercise is added separately
MIN_LOSE_AGE = 18       # no weight-loss targets for under-18s


def bmr(gender, weight_kg, height_cm, age):
    """Mifflin-St Jeor resting energy expenditure in kcal/day."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if gender == "Male":
        return base + 5
    if gender == "Female":
        return base - 161
    return base - 78  # midpoint for "Other"


def effective_goal(goal, age):
    if goal not in GOAL_OFFSETS:
        return "maintain"
    if goal == "lose" and age < MIN_LOSE_AGE:
        return "maintain"
    return goal


def maintenance(user, burned):
    """Estimated calories needed to stay at the same weight that day: everyday life
    (resting needs x 1.2) plus the exercise that was logged."""
    resting = bmr(user["gender"], user["weight_kg"], user["height_cm"], user["age"])
    return round(resting * BASELINE_FACTOR + burned)


def daily_target(user, burned_today, consumed_today):
    """`user` needs gender, weight_kg, height_cm, age and (optionally) goal."""
    resting = bmr(user["gender"], user["weight_kg"], user["height_cm"], user["age"])
    goal = effective_goal(user.get("goal", "maintain"), user["age"])
    raw = resting * BASELINE_FACTOR + burned_today + GOAL_OFFSETS[goal]
    target = max(resting, raw)  # never target below resting needs
    return {
        "goal": goal,
        "bmr": round(resting),
        "target": round(target),
        "consumed": round(consumed_today),
        "burned": round(burned_today),
        "remaining": round(target - consumed_today),
        "percent": round(min(999, 100 * consumed_today / target)) if target else 0,
    }
