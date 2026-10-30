"""Meme of the Stream: chat votes with !vote <id> for its favourite meme.

A mod opens a voting round from /mod. Viewer memes approved in the last
VOTE_WINDOW_HOURS are in the running. One vote per viewer per round (voting
again changes the vote). Closing the round crowns the winner on the overlay.
"""
from __future__ import annotations

from flask import current_app

from .db import get_db
from .extensions import socketio
from .pipeline import RequestRefused, say

LEADERBOARD_SIZE = 5


def current_round():
    return get_db().execute(
        "SELECT * FROM vote_rounds WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()


def _eligible(round_row, meme_id: int):
    return get_db().execute(
        "SELECT * FROM memes WHERE id = ? AND status IN ('approved', 'shown') "
        "AND requested_by != 'streamer' AND decided_at >= datetime(?, ?)",
        (meme_id, round_row["opened_at"], f"-{current_app.config['VOTE_WINDOW_HOURS']} hours"),
    ).fetchone()


def leaderboard(round_id: int, limit: int = LEADERBOARD_SIZE) -> list[dict]:
    rows = get_db().execute(
        "SELECT m.id, m.filename, m.requested_by, m.template_id, COUNT(v.voter) AS votes "
        "FROM votes v JOIN memes m ON m.id = v.meme_id WHERE v.round_id = ? "
        "GROUP BY m.id ORDER BY votes DESC, m.id ASC LIMIT ?", (round_id, limit)).fetchall()
    return [{"id": r["id"], "url": f"/generated/{r['filename']}", "requested_by": r["requested_by"],
             "template_id": r["template_id"], "votes": r["votes"]} for r in rows]


def state() -> dict:
    """Current round (if open) or the most recent one, plus its leaderboard."""
    db = get_db()
    row = current_round() or db.execute("SELECT * FROM vote_rounds ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return {"open": False, "round_id": None, "leaderboard": [], "total_votes": 0, "winner_id": None}
    total = db.execute("SELECT COUNT(*) FROM votes WHERE round_id = ?", (row["id"],)).fetchone()[0]
    return {"open": row["closed_at"] is None, "round_id": row["id"], "leaderboard": leaderboard(row["id"]),
            "total_votes": total, "winner_id": row["winner_meme_id"]}


def _broadcast() -> None:
    socketio.emit("voting_updated", state())


def open_round() -> dict:
    if current_round() is not None:
        raise RequestRefused("Voting is already open.")
    db = get_db()
    db.execute("INSERT INTO vote_rounds DEFAULT VALUES")
    db.commit()
    _broadcast()
    say("🏆 Meme of the Stream voting is open! Type !vote <number> for your favourite meme "
        "(the number is shown on each meme).")
    return state()


def vote(user: str, meme_ref: str) -> None:
    round_row = current_round()
    if round_row is None:
        raise RequestRefused(f"@{user} voting isn't open right now.")
    try:
        meme_id = int(str(meme_ref).lstrip("#"))
    except ValueError:
        raise RequestRefused(f"@{user} usage: !vote <meme number>, e.g. !vote 12")
    if _eligible(round_row, meme_id) is None:
        raise RequestRefused(f"@{user} meme #{meme_id} isn't in the running.")
    db = get_db()
    db.execute(
        "INSERT INTO votes (round_id, voter, meme_id) VALUES (?, ?, ?) "
        "ON CONFLICT(round_id, voter) DO UPDATE SET meme_id = excluded.meme_id, voted_at = datetime('now')",
        (round_row["id"], user.strip().lower()[:40], meme_id))
    db.commit()
    # No chat reply on success, so a voting rush doesn't flood chat.
    _broadcast()


def close_round() -> dict:
    round_row = current_round()
    if round_row is None:
        raise RequestRefused("Voting isn't open.")
    top = leaderboard(round_row["id"], limit=1)
    winner = top[0] if top else None
    db = get_db()
    db.execute("UPDATE vote_rounds SET closed_at = datetime('now'), winner_meme_id = ? WHERE id = ?",
               (winner and winner["id"], round_row["id"]))
    db.commit()
    _broadcast()
    if winner:
        socketio.emit("show_winner", winner_json(winner))
        say(f"👑 Meme of the Stream: #{winner['id']} by @{winner['requested_by']} "
            f"with {winner['votes']} vote{'s' if winner['votes'] != 1 else ''}! GG chat.")
    else:
        say("Voting closed. No votes this time!")
    return state()


def show_leaderboard() -> None:
    s = state()
    if not s["leaderboard"]:
        raise RequestRefused("No votes yet.")
    socketio.emit("show_leaderboard", {"leaderboard": s["leaderboard"], "open": s["open"],
                                       "seconds": current_app.config["OVERLAY_SECONDS"] + 4})


def winner_json(winner: dict) -> dict:
    return {**winner, "seconds": current_app.config["OVERLAY_SECONDS"] + 6}
