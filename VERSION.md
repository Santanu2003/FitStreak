# FitStreak v9.4 — Leaderboard overhaul

This ZIP is based on **FitStreak v9.3** and reworks the **Leaderboard** page from a plain
static table into an interactive, data-backed view.

### Leaderboard upgrades
- **Community stats strip**: total community kcal burned, active users, sessions logged,
  average streak, and the period's most popular activity (animated count-up numbers).
- **Podium for the top 3**: avatar initials, medal badges, animated kcal counters, favorite
  activity, current streak, and a trend arrow vs. the previous equal-length period. Your own
  card is marked with a **YOU** badge.
- **Interactive top-10 bar chart** with a dashed **benchmark reference line** — what a
  "typical active person" in your age bracket burns via exercise in that period, derived from
  real data: average exercise hours/week from the 1,000-person health survey
  (`health_benchmarks.json`) combined with a real kcal/minute rate from the 973-session gym
  tracker (`gym_members_exercise_tracking.csv`). Clicking a bar scrolls to and flashes that
  user's row in the table.
- **Enriched, searchable table**: avatar, name, favorite activity, kcal burned (+ trend badge),
  avg kcal/session, sessions, and streak, with a live search box and your row highlighted.
- **New "Last 30 days" period**, alongside the existing 7-day and all-time views, each with its
  own correctly-scoped trend comparison against the prior equal-length window.
- `GET /api/leaderboard` now also returns `community`, `your_row`, and `benchmark` alongside
  the existing `leaderboard` / `your_rank` fields; each leaderboard row gained
  `total_minutes`, `avg_kcal_per_session`, `favorite_activity`, `active_days`,
  `consistency_pct`, and `trend_pct`.

### Known pre-existing issue (not touched by this change)
`test_custom_foods_are_private_to_each_user` fails because v9.3 intentionally made custom
foods **shared** across accounts — the test still asserts the older private-foods behavior.
Left as-is since it's unrelated to this update; worth updating that test's expectations
separately.

---

# FitStreak v9.3 — Shared My Foods

This ZIP is based on **FitStreak v9.1** and completes the Nutrition page's **My Foods** feature.

### My Foods upgrades
- Custom foods are now shared across all registered accounts. If BB creates a food, AB can search and use the same food without creating a duplicate.
- Existing v9.2 private custom foods are migrated into one shared library; duplicate names are reconciled while preserving the oldest entry.
- The creator remains the only account allowed to edit or delete a shared custom food. Other users can use it normally.
- Create custom foods directly from the My Foods section.
- Store nutrition values per serving.
- Edit saved foods without deleting existing food logs.
- Delete saved foods with confirmation; existing logs remain untouched.
- Search/filter the user's saved foods instantly.
- See a dynamic saved-food count.
- Use a saved food directly in the meal logger.
- Shared custom foods appear first in Food search with a **CUSTOM** badge.
- Prevent duplicate custom-food names globally (case-insensitive).
- Prevent a custom food from duplicating an existing built-in Food Database name.
- Keep food logs user-scoped while custom-food creation/edit/delete is server-validated; custom-food visibility is shared.

The rest of the v9/v9.1 dynamic-consistency and Health Benchmark fixes are preserved.
