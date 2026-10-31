"""Keeps data files safe on cloud hosts.

Free hosts like Render wipe the disk on every restart. When the app runs on
Postgres, every data file it writes (face cutouts, generated memes, user
templates, Twitch tokens) is also copied into the database's `files` table and
written back to disk at startup. Locally, with SQLite, these are no-ops.
"""
import logging
from pathlib import Path

from .config import ROOT
from .db import pg_pool

log = logging.getLogger(__name__)


def _key(path: Path) -> str | None:
    """Path relative to the app folder; None for files elsewhere (e.g. test temp dirs)."""
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None


def save(path: Path) -> None:
    pool, key = pg_pool(), _key(path)
    if pool is None or key is None:
        return
    with pool.connection() as conn:
        conn.execute("INSERT INTO files (path, data) VALUES (%s, %s) "
                     "ON CONFLICT (path) DO UPDATE SET data = excluded.data",
                     (key, Path(path).read_bytes()))


def delete(path: Path) -> None:
    pool, key = pg_pool(), _key(path)
    if pool is None or key is None:
        return
    with pool.connection() as conn:
        conn.execute("DELETE FROM files WHERE path = %s", (key,))


def restore() -> None:
    """Write every stored file back to disk (run once at startup)."""
    pool = pg_pool()
    if pool is None:
        return
    root = ROOT.resolve()
    count = 0
    with pool.connection() as conn:
        for row in conn.execute("SELECT path, data FROM files"):
            target = (root / row["path"]).resolve()
            if not target.is_relative_to(root):
                log.warning("Skipping stored file outside the app folder: %s", row["path"])
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(row["data"])
            count += 1
    log.info("Restored %d data file(s) from the database", count)
