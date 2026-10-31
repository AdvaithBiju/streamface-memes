"""Database access.

Locally the app uses SQLite (data/streamface.db). When DATABASE_URL is set, as on
the cloud deploy, it uses Postgres instead: the same SQL runs on both, with
placeholders and datetime('now') translated for Postgres.
"""
import atexit
import re
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

# Postgres only: copies of data files (faces, memes, tokens), since cloud hosts
# wipe their disk on every restart. See app/storage.py.
PG_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS files (
    path  TEXT PRIMARY KEY,
    data  BYTEA NOT NULL
);
"""

# Columns added after the first release; init_db adds any that are missing.
MIGRATIONS = {
    "memes": [
        ("source", "TEXT NOT NULL DEFAULT 'editor'"),   # editor | chat | channel_points | demo | web
        ("decided_by", "TEXT"),
        ("decided_at", "TEXT"),
        ("shown_at", "TEXT"),
        ("redemption_id", "TEXT"),   # Twitch channel point redemption, if any
        ("reward_id", "TEXT"),
    ],
}

# Same 'YYYY-MM-DD HH:MM:SS' UTC text that SQLite's datetime('now') produces.
PG_NOW = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"
# Tables with an id column; INSERTs into them get RETURNING id for lastrowid.
_ID_INSERT_RE = re.compile(r"^\s*INSERT INTO (faces|memes|vote_rounds)\b", re.I)

_pool = None  # psycopg_pool.ConnectionPool when DATABASE_URL is set


def pg_pool():
    return _pool


# ------------------------------------------------------------------ Postgres adapter

def to_postgres(sql: str) -> str:
    return sql.replace("datetime('now')", PG_NOW).replace("?", "%s")


class PgRow(dict):
    """Row usable like sqlite3.Row: row["name"] and row[0]."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: PgRow(zip(names, values))


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class PgConnection:
    """The bits of the sqlite3.Connection API the app uses."""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, params=()):
        returning = bool(_ID_INSERT_RE.match(sql)) and "RETURNING" not in sql.upper()
        cur = self.conn.execute(to_postgres(sql) + (" RETURNING id" if returning else ""), tuple(params))
        return _PgCursor(cur, cur.fetchone()["id"] if returning else None)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()


def _pg_schema() -> str:
    schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    schema = schema.replace("(datetime('now'))", f"({PG_NOW})")
    alters = [f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {decl};"
              for table, columns in MIGRATIONS.items() for name, decl in columns]
    return schema + PG_FILES_TABLE + "\n".join(alters)


# ------------------------------------------------------------------ app hooks

def get_db():
    if "db" not in g:
        if _pool is not None:
            g.db = PgConnection(_pool.getconn())
        else:
            g.db = sqlite3.connect(current_app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is None:
        return
    if isinstance(db, PgConnection):
        db.rollback()  # end any read-only transaction before returning it to the pool
        _pool.putconn(db.conn)
    else:
        db.close()


def init_db(db_path: Path, database_url: str = "") -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
    if database_url:
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(database_url, min_size=1, max_size=8, open=True,
                               check=ConnectionPool.check_connection,  # hosted DBs drop idle links
                               kwargs={"row_factory": _row_factory})
        atexit.register(_pool.close)
        with _pool.connection() as conn:
            conn.execute(_pg_schema())
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
