import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS faces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL,          -- 'upload' or 'webcam'
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL UNIQUE,
    template_id   TEXT NOT NULL,
    requested_by  TEXT NOT NULL,         -- viewer name, or 'streamer' for editor-made memes
    caption       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,         -- created | pending | approved | rejected | shown
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Meme of the Stream voting
CREATE TABLE IF NOT EXISTS vote_rounds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT,
    winner_meme_id  INTEGER
);

CREATE TABLE IF NOT EXISTS votes (
    round_id  INTEGER NOT NULL,
    voter     TEXT NOT NULL,       -- lowercased viewer name; one vote per viewer per round
    meme_id   INTEGER NOT NULL,
    voted_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (round_id, voter)
);
"""

# Columns added after the first release; init_db adds any that are missing.
MIGRATIONS = {
    "memes": [
        ("source", "TEXT NOT NULL DEFAULT 'editor'"),   # editor | chat | channel_points | demo
        ("decided_by", "TEXT"),
        ("decided_at", "TEXT"),
        ("shown_at", "TEXT"),
        ("redemption_id", "TEXT"),   # Twitch channel point redemption, if any
        ("reward_id", "TEXT"),
    ],
}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
