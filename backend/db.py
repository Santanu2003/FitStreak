"""Lightweight sqlite3 data layer — no ORM dependency required."""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_DB = os.path.join(BASE_DIR, "fitstreak.db")
# On a host (e.g. Render) set FITSTREAK_DB_PATH to where the database should live,
# for example /var/data/fitstreak.db on a persistent disk. Locally it stays in backend/.
DB_PATH = os.environ.get("FITSTREAK_DB_PATH") or BUNDLED_DB


def _seed_db_if_missing():
    """If the configured database file doesn't exist yet, start from the bundled copy."""
    if not os.environ.get("FITSTREAK_DB_PATH"):
        return  # local runs / tests: just use DB_PATH as is, never copy anything
    if os.path.exists(DB_PATH):
        return
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    if os.path.exists(BUNDLED_DB) and os.path.abspath(BUNDLED_DB) != os.path.abspath(DB_PATH):
        import shutil
        shutil.copyfile(BUNDLED_DB, DB_PATH)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    age INTEGER NOT NULL,
    gender TEXT NOT NULL,
    height_cm REAL NOT NULL,
    weight_kg REAL NOT NULL,
    experience_level INTEGER NOT NULL DEFAULT 1,
    goal TEXT NOT NULL DEFAULT 'maintain',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    duration_min REAL NOT NULL,
    calories_burned REAL NOT NULL,
    steps INTEGER NOT NULL DEFAULT 0,
    mood TEXT NOT NULL DEFAULT 'Okay',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, log_date, activity_type)
);

CREATE INDEX IF NOT EXISTS idx_logs_user ON activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_user_date ON activity_logs(user_id, log_date);

CREATE TABLE IF NOT EXISTS food_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date TEXT NOT NULL,
    meal TEXT NOT NULL,
    food_name TEXT NOT NULL,
    servings REAL NOT NULL DEFAULT 1,
    calories REAL NOT NULL DEFAULT 0,
    protein_g REAL NOT NULL DEFAULT 0,
    carbs_g REAL NOT NULL DEFAULT 0,
    fat_g REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, log_date, meal, food_name)
);

CREATE INDEX IF NOT EXISTS idx_food_logs_user_date ON food_logs(user_id, log_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_food_logs_unique_normalized ON food_logs(user_id, log_date, meal, lower(trim(food_name)));

CREATE TABLE IF NOT EXISTS custom_foods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    food_name TEXT NOT NULL,
    calories REAL NOT NULL,
    protein_g REAL NOT NULL,
    carbs_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, food_name COLLATE NOCASE)
);

CREATE INDEX IF NOT EXISTS idx_custom_foods_user ON custom_foods(user_id);
-- The global custom-food uniqueness index is created in _migrate after old duplicates are reconciled.

CREATE TABLE IF NOT EXISTS weight_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date TEXT NOT NULL,
    weight_kg REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, log_date)
);

CREATE INDEX IF NOT EXISTS idx_weight_logs_user ON weight_logs(user_id);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate(conn):
    """Bring an older database up to date without losing useful data."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "goal" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN goal TEXT NOT NULL DEFAULT 'maintain'")

    # v9.3: custom foods are shared across accounts. Keep the oldest copy when an
    # old private-per-user database happens to contain the same name more than once.
    duplicates = conn.execute(
        """SELECT lower(trim(food_name)) AS name_key, MIN(id) AS keep_id
           FROM custom_foods
           GROUP BY lower(trim(food_name))
           HAVING COUNT(*) > 1"""
    ).fetchall()
    for dup in duplicates:
        conn.execute(
            """DELETE FROM custom_foods
               WHERE lower(trim(food_name)) = ? AND id <> ?""",
            (dup["name_key"], dup["keep_id"]),
        )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_custom_foods_global_name
           ON custom_foods(lower(trim(food_name)))"""
    )


def init_db():
    _seed_db_if_missing()
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
