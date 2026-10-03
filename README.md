# FitStreak — a fitness innovation platform

A full-stack web app for the brief *"User Innovation-Ideas that can boost fitness
activities and assist in keeping fit."* Users log workouts, meals and weight; get an ML
calorie-burn estimate and a personalised 1-week plan; compare themselves to real datasets;
and compete on a streak-based leaderboard.

## Run it

```bash
cd backend
pip install -r requirements.txt
python app.py            # then open http://127.0.0.1:5000
```

Run the tests (after installing `backend/requirements.txt`):

```bash
python -m unittest discover -s tests -v      # or: pytest tests/
```

## Features

| Page | What it does |
|---|---|
| **Dashboard** | Log activity (calories are computed server-side from a MET formula, not typed in), streak + Bronze/Silver/Gold badges, a daily *"keep your streak alive"* nudge, calories chart, and **net kcal today** (food eaten − calories burned) |
| **Predict & Recommend** | RandomForest calorie-burn estimate trained on **all 10 activity types** (~37.5 kcal avg error; every type scored as itself, not mapped to a closest match), body fat estimated automatically (Deurenberg formula), cohort insight, a personalised 1-week plan that rotates through every workout type with a model-estimated kcal per session, and an interactive calories-per-minute chart across 10 activities |
| **Exercise Library** | 2,909 exercises, searchable/filterable by body part, equipment, level |
| **User Insights** | Real correlations from a 2,000-user survey, an interactive what-if slider, your own last-14-days / activity-mix / weekday charts, and how *your* logged habits compare |
| **Health Benchmark** | Your steps / sleep / exercise percentile vs. 1,000 people in your age bracket (descriptive only, not medical advice) |
| **Nutrition** | **Daily calorie goal** (lose / maintain / build) with a progress bar, food search (960 foods, incl. 367 Indian foods) with auto-filled macros, **My foods** (shared custom-food library: create, search, use, plus creator-only edit/delete), per-meal log, day navigator (prev/next/today + 7-day chip strip), a day-summary card (eaten vs. burned vs. what your body needed, surplus/deficit verdict) for **any past date**, and a 7/14/30-day history chart |
| **Weight & BMI** | Log weight over time; BMI/weight trend chart. The latest entry keeps the rest of the app current |
| **Leaderboard** | Ranked by calories burned — **7 days**, **30 days**, or all time — with a community stats strip, a top-3 podium, an interactive top-10 chart with a real-data benchmark line, trend arrows, and a searchable table |

## Architecture

| Layer | Tech |
|---|---|
| Frontend | Vanilla HTML/CSS/JS. All charts are drawn by a dependency-free, interactive SVG renderer (`minicharts.js`) — hover tooltips, click-to-hide legends, animated entrances, no CDN and no internet required |
| Backend | Flask, serving both the API and the frontend (no CORS) |
| Database | SQLite via the built-in `sqlite3` module |
| ML | scikit-learn RandomForestRegressor |

```
fitstreak/
├── backend/   app.py · db.py · models.py · config.py · goals.py · ml_utils.py · health_utils.py · nutrition_utils.py · data/ · ml/
├── frontend/  index.html · css/style.css · js/app.js · js/minicharts.js · js/auth-fx.js · assets/ (logo + favicons) · favicon.ico
├── scripts/   prepare_data.py · train_models.py · validate_data.py (+ canonical source CSVs)
└── tests/     test_app.py (67 tests) · minicharts_check.js
```

## Branding

The FitStreak flame logo lives in `frontend/assets/`: `logo-mark.svg` (sidebar and source artwork),
`favicon.svg`, `favicon-32.png`, `apple-touch-icon.png`, `icon-192.png`, `logo-mark-512.png`, plus
`frontend/favicon.ico` for the browser tab. The login screen (`js/auth-fx.js` + the `.auth-hero` styles)
animates the flame and lights up a seven-day streak; it respects `prefers-reduced-motion`.

## Charts

All bar/line/doughnut charts are drawn by `frontend/js/minicharts.js` as inline SVG (no chart library).
Hovering a bar darkens that bar's own color, adds a thin outline and a small lift — it no longer shows
a full-height background highlight behind it (that's only kept for the few charts that combine a bar
series with a line, to anchor the line's vertical guide).

## Health Benchmark & Weight/BMI pages

`backend/health_utils.py` compares the logged-in user against `backend/data/health_benchmarks.json`
(built from `health_activity_data.csv` by `scripts/prepare_data.py`), which now also carries BMI and
heart-rate distributions per age bracket. The Health Benchmark page shows percentile "meters" for steps,
sleep, exercise and (once you've logged a weight) BMI, an overall headline percentile, a "top quartile in
your bracket" figure per metric, and highlights your own age bracket on the averages chart. The Weight &
BMI page leads with stat cards for current weight/BMI, your healthy-weight range for your logged height,
and your trend since your first entry; the history table shows the change between consecutive entries.

## Data integrity & security

- **No duplicates:** unique constraints + upserts on activity `(user, date, activity)`, food
  `(user, date, meal, food)` and weight `(user, date)` — re-submitting updates the entry.
- **XSS-safe rendering:** every user-controlled string goes through `escapeHtml()` before
  `innerHTML`; a test scans `app.js` so an unescaped field can't creep back in.
- **Server-side validation:** activity type and meal must be from fixed lists; weight range,
  name length, dates are checked; client-supplied calories are ignored.
- **Safe upgrades:** `init_db()` migrates a database from an older version in place (e.g. adds the `goal` column) without losing data.
- **Calorie goal safeguards:** target is never below resting needs, and weight-loss targets aren't offered to under-18s.
- Set `FITSTREAK_SECRET` to a random value before hosting anywhere public (the default is for local demos).

## Datasets

| File | Used for |
|---|---|
| `scripts/gym_members_exercise_tracking.csv` (973 canonical source rows) | Calorie model + workout cohort lookup |
| `scripts/megaGymDataset.csv` (2,909 canonical exercises) | Exercise library + weekly plan |
| `scripts/student_lifestyle_dataset.csv` (2,000 canonical users) | User Insights |
| `scripts/health_activity_data.csv` (1,000 canonical reference rows) | Health Benchmark (diabetes/heart columns deliberately not used) |
| `health_fitness_dataset.csv` (687,701) | Activity comparison chart (pre-aggregated; raw file not shipped, ~78 MB) |
| `daily_food_nutrition_dataset.csv` (canonical source; preparation removes duplicate rows and duplicate food names before generating the 593-record runtime food database) | Nutrition food database (general) |
| `indian_foods.csv` (367) | Indian foods — breads, dal, veg / non-veg curries, South Indian, **Bengali dishes**, snacks (incl. kachori, kochuri, luchi), sweets & desserts, drinks, and a **Fish & Seafood** section (hilsa/ilish, chingri, rohu, katla, pabda, bhetki, pomfret, crab, Kerala & Goan fish…). Hand-maintained; **approximate home-style values per the serving in the name** (a *katori* ≈ 150 g), not lab data |

**Not used:** `fitness_tracker_dataset.csv` (1M rows) — inspected and found to be effectively
random (e.g. Yoga and Cycling both average ~2,750 kcal and ~10 km), so no honest feature can be built on it.

## Foods that aren't in the database

1. **Search** understands spelling variants and synonyms (`chapati`/`roti`, `dahi`/`curd`, `goat`/`mutton`, `idly`/`idli`), plural and category words (`sweets`, `snacks`), and needs every word to match (`mutton paratha`).
2. **Not found?** The form says so; the user types the totals for their servings and ticks *Save to My foods*. Values are stored per serving, so next time the food auto-fills like any other and is scaled by servings. Custom foods are shared across the FitStreak accounts, while meal/food logs remain private to each user. The creator of a custom food is the only account allowed to edit or delete it. The **My foods** panel also supports creating, searching, editing, using and deleting saved foods; existing food logs are never removed when a saved food is deleted. Built-in food names are blocked for custom entries so the database does not create duplicate foods.
3. **Sanity checks** (server-side, on every entry): servings 0–20, calories ≤ 5,000, and calories must roughly agree with protein/carbs/fat, which catches typos such as 20 kcal for a 166 kcal dish.
4. **Adding more built-in foods:** append rows to `backend/data/indian_foods.csv` (`Food_Item, Category, Meal_Type, Region, Calories, Protein_g, Carbs_g, Fat_g`, per one serving stated in the name). The tests check for duplicates and that calories agree with the macros. `prepare_data.py` does not touch this file.

## Regenerating data / model

```bash
cd scripts
python prepare_data.py
python train_models.py
```

`train_models.py` trains the calorie model on **all 10 workout types**. The only labelled
sessions are the 973 gym-tracker rows, which cover just 4 types (Cardio/HIIT/Strength/Yoga) at
almost the same average calories — not enough to teach a model that Walking differs from
Running. So each real session is replayed under all 10 types, with its calorie label and heart
rate scaled by that type's relative kcal/minute (from the 687,701-session activity-comparison
dataset already in `backend/data/activity_comparison.json`). The model then learns the type
directly, instead of every non-core type being silently remapped to Cardio at prediction time.

## Known limitations / next ideas

- The mood→stress link on User Insights is a rough proxy, labelled as such in the UI.
- Offline, only the display fonts (Google Fonts) fall back to system fonts — the charts
  themselves are always the built-in interactive renderer, online or off.
- Indian food values are approximate and vary a lot with recipe, oil and portion size; users can override them or save their own version. Verify against IFCT 2017 (NIN) or USDA FoodData Central if precision matters for your report.
- The calorie goal is a standard-formula estimate for motivation, not dietetic advice.
- Ideas: friends list, email reminders, Postgres for hosting.

## v9 consistency and dynamic-data upgrade

This version strengthens the original project without replacing its existing pages.

### What was changed

1. **Single configuration source** — activities, moods, meals, experience levels, goals and age brackets are served by `/api/config` instead of being independently maintained in the UI and backend.
2. **Single user-state source** — `/api/user/summary` provides the canonical current profile, today's calories/steps, last-7-day activity and goal state.
3. **Profile-synchronized predictor** — age, gender, height, weight and experience are loaded from the authenticated profile; the predictor no longer depends on duplicated profile values in the UI.
4. **Dynamic model metadata** — model algorithm, training rows, feature count, metrics and trained activity types are exposed by `/api/predict/profile`.
5. **Dynamic dataset counts** — exercise, food, user, benchmark and activity-comparison sample sizes are loaded from the backend instead of being hardcoded into page copy.
6. **Cross-section refresh** — activity, food, weight and goal changes refresh the canonical user state so dependent sections stay consistent.
7. **Weight as the current-body source** — the latest logged weight continues to update the profile, BMI and calorie calculations used elsewhere.
8. **Activity history summary** — `/api/activity/history` now returns aggregate sessions, minutes, calories, steps and active days as well as raw logs.
9. **Dynamic Health Benchmark inputs** — age, recent steps, exercise hours and BMI are prefilled from the user's profile/activity/weight history. Sleep is not fabricated because FitStreak does not currently collect sleep logs.
10. **Leaderboard self-rank** — the current user's rank is returned with the selected leaderboard period.
11. **Stronger validation** — profile, activity and prediction inputs have server-side range checks; heart-rate ordering is validated.
12. **Case/whitespace-safe food de-duplication** — repeated food names such as `Banana` and ` banana ` update the existing log instead of creating a second record; a database-level normalized unique index reinforces this.
13. **Canonical raw-data layout** — the five source CSVs remain in `scripts/`; unnecessary runtime copies of those CSVs were removed from `backend/data/`.
14. **Automated data validation** — `scripts/validate_data.py` checks canonical row counts and duplicate keys. The raw nutrition source currently contains 54 exact duplicates; the preparation step removes them before the generated food database is used.
15. **Regression tests** — tests were added for the configuration API, unified user summary, food duplicate protection, prediction profile and dynamic benchmark inputs.

### Data architecture

```text
scripts/*.csv (canonical source data)
        |
        v
scripts/prepare_data.py
        |
        v
backend/data/*.json + indian_foods.csv (runtime reference data)
        |
        +----> backend services / ML
        |
        v
      Flask API
        |
        v
     frontend
```

User-generated data remains in SQLite (`fitstreak.db`) and is the source of truth for profile, activity, nutrition, goals and weight history.

### Validation

Run before deployment:

```bash
python scripts/validate_data.py
python -m unittest discover -s tests -v
```

The runtime environment used to prepare this ZIP did not have Flask installed and had no network access, so the Flask test suite could not be executed here. Python syntax checks, JavaScript syntax checks and the complete dataset validation script were executed successfully.

## Deploying: Render (backend) + Vercel (frontend)

Put the whole `fitstreak/` folder in a GitHub repo (use a **private** repo: `backend/fitstreak.db` holds account data).

**1. Backend on Render**
1. Render dashboard → **New → Blueprint** → pick the repo. It reads `render.yaml` and creates the `fitstreak-api` web service (free plan).
2. Wait for the deploy, then copy the service URL, e.g. `https://fitstreak-api-xxxx.onrender.com`.
3. Check `https://<that-url>/api/health` shows `{"ok":true}`.

**2. Frontend on Vercel**
1. Open `frontend/vercel.json` and replace `YOUR-RENDER-APP.onrender.com` with your Render host. Commit and push.
2. Vercel → **Add New → Project** → pick the repo → set **Root Directory** to `frontend` → Framework preset **Other** → Deploy.
3. Open the Vercel URL. All `/api/...` calls are forwarded to Render, so login cookies work without CORS setup.

**Good to know**
- Free Render sleeps after 15 min idle; the first visit takes ~1 min to wake (the page pings `/api/health` on load to start it early).
- Free Render has no permanent disk: the database resets to the bundled `fitstreak.db` on every restart/redeploy, so new sign-ups and logs are lost. To keep data, change the plan to `starter`, uncomment the `disk:` block in `render.yaml` and add env var `FITSTREAK_DB_PATH=/var/data/fitstreak.db` (the bundled DB seeds it the first time).
- Local run is unchanged: `cd backend && python app.py`.
