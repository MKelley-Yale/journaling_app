"""SQLite storage. One file, easy to back up — just copy journal.db somewhere safe.

Data lives in the PARENT folder (alongside photos/), not inside journal-app/, so the
code directory holds only code and the data survives replacing/reinstalling the app.
"""
import sqlite3
import os
import json
from datetime import datetime, timezone

DATA_DIR = os.environ.get(
    "JOURNAL_DATA_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
DB_PATH = os.environ.get("JOURNAL_DB", os.path.join(DATA_DIR, "journal.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    kind TEXT NOT NULL DEFAULT 'themed',     -- daily | themed | template
    is_daily INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'reflective',  -- factual | reflective
    source TEXT NOT NULL DEFAULT 'builtin',   -- builtin | user | ai
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    weather TEXT,
    location TEXT,
    is_freewrite INTEGER NOT NULL DEFAULT 0,
    mood TEXT              -- mood key from MOODS in server.py, or NULL if skipped
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    prompt_id INTEGER REFERENCES prompts(id) ON DELETE SET NULL,
    question_text TEXT NOT NULL,          -- snapshot of the prompt as shown
    kind TEXT,
    answer_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- follow-up reflections added later when a past answer is resurfaced
CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT UNIQUE NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_for TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'primary',   -- primary | followup
    sent_at TEXT,
    engaged INTEGER NOT NULL DEFAULT 0
);

-- One row per push attempt per subscription. `status` is the HTTP status the push
-- service (Apple) returned: 201 = accepted for delivery. NULL = the request never
-- got a response (network/TLS/library error) -- see `error`.
CREATE TABLE IF NOT EXISTS push_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,                   -- test | reminder
    reminder_id INTEGER,
    subscription_id INTEGER,
    endpoint TEXT,
    title TEXT,
    body TEXT,
    status INTEGER,
    error TEXT
);
"""

DEFAULT_SETTINGS = {
    "cadence_min_days": "3",
    "cadence_max_days": "4",
    "window_start_hour": "8",     # 8am
    "window_end_hour": "22",      # 10pm
    "morning_cutoff_hour": "12",  # before this -> ask about yesterday
    "session_size": "8",          # prompts per session (half factual / half reflective)
    "pin_hash": "",               # set on first PIN setup
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# Columns added after the first release. CREATE TABLE IF NOT EXISTS won't add a
# column to a table that already exists, so they're applied by hand on startup.
MIGRATIONS = [
    ("entries", "mood", "ALTER TABLE entries ADD COLUMN mood TEXT"),
]


def _migrate(conn):
    for table, column, sql in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(sql)
    conn.commit()


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    # default settings
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def seed_if_empty():
    """Insert seed collections only if there are none yet."""
    from seed_data import seed_collections
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) AS c FROM collections").fetchone()["c"]
    if count == 0:
        for name, desc, kind, is_daily, prompts in seed_collections():
            cur = conn.execute(
                "INSERT INTO collections(name, description, kind, is_daily, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, desc, kind, is_daily, now_iso()),
            )
            cid = cur.lastrowid
            for pkind, ptext in prompts:
                conn.execute(
                    "INSERT INTO prompts(collection_id, text, kind, source, active, created_at) "
                    "VALUES (?, ?, ?, 'builtin', 1, ?)",
                    (cid, ptext, pkind, now_iso()),
                )
        conn.commit()
    conn.close()
