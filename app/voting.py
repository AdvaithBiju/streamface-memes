"""Meme of the Stream: chat votes with !vote <id> for its favourite meme.

A mod opens a voting round from /mod. Viewer memes approved in the last
VOTE_WINDOW_HOURS are in the running. One vote per viewer per round (voting
again changes the vote). Closing the round crowns the winner on the overlay.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app

from .db import get_db
from .extensions import socketio
from .pipeline import RequestRefused, say

LEADERBOARD_SIZE = 5
MAX_CHOICES = 12        # memes shown on the overlay's "vote now" card
CHAT_LIMIT = 480        # Twitch messages max out at 500 characters
SQL_TIME = "%Y-%m-%d %H:%M:%S"  # format of datetime('now') in the database


def current_round():
    return get_db().execute(
        "SELECT * FROM vote_rounds WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()


def _since(round_row=None) -> str:
    opened = datetime.strptime(round_row["opened_at"], SQL_TIME) if round_row else datetime.now(timezone.utc)
    return (opened - timedelta(hours=current_app.config["VOTE_WINDOW_HOURS"])).strftime(SQL_TIME)


ELIGIBLE = "status IN ('approved', 'shown') AND requested_by != 'streamer' AND decided_at >= ?"


def _eligible(round_row, meme_id: int):
    return get_db().execute(f"SELECT * FROM memes WHERE id = ? AND {ELIGIBLE}",
                            (meme_id, _since(round_row))).fetchone()


def candidates(round_row=None) -> list[dict]:
    """Memes in the running for this round (or for a round opened now), with their votes."""
    rows = get_db().execute(
        f"SELECT m.id, m.filename, m.requested_by, "
        f"(SELECT COUNT(*) FROM votes v WHERE v.round_id = ? AND v.meme_id = m.id) AS votes "
        f"FROM memes m WHERE {ELIGIBLE} ORDER BY m.id",
        (round_row["id"] if round_row else 0, _since(round_row))).fetchall()
    return [{"id": r["id"], "url": f"/generated/{r['filename']}", "requested_by": r["requested_by"],
             "votes": r["votes"]} for r in rows]


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
        return {"open": False, "round_id": None, "leaderboard": [], "total_votes": 0, "winner_id": None,
                "candidates": candidates()}
    is_open = row["closed_at"] is None
    total = db.execute("SELECT COUNT(*) FROM votes WHERE round_id = ?", (row["id"],)).fetchone()[0]
    return {"open": is_open, "round_id": row["id"], "leaderboard": leaderboard(row["id"]),
            "total_votes": total, "winner_id": row["winner_meme_id"],
            # Open round: what chat can vote for. Closed: what the next round would have.
            "candidates": candidates(row if is_open else None)}


def _broadcast() -> None:
    socketio.emit("voting_updated", state())


def choices_message(memes: list[dict]) -> str:
    """Chat line listing the choices, cut to fit one Twitch message."""
    msg = "🏆 Meme of the Stream voting is open! Vote with"
    for i, m in enumerate(memes):
        part = f" !vote {m['id']} ({m['requested_by']}),"
        more = f" … +{len(memes) - i} more on stream"
        if len(msg) + len(part) + len(more) > CHAT_LIMIT and i < len(memes) - 1:
            return msg.rstrip(",") + more
        msg += part
    return msg.rstrip(",")


def open_round() -> dict:
    if current_round() is not None:
        raise RequestRefused("Voting is already open.")
    if not candidates():
        hours = current_app.config["VOTE_WINDOW_HOURS"]
        raise RequestRefused(f"Nothing to vote on yet: approve some viewer memes first "
                             f"(memes approved in the last {hours}h count).")
    db = get_db()
    db.execute("INSERT INTO vote_rounds DEFAULT VALUES")
    db.commit()
    _broadcast()
    memes = candidates(current_round())
    say(choices_message(memes))
    _emit_choices(memes)
    return state()


def _emit_choices(memes: list[dict]) -> None:
    socketio.emit("show_choices", {"choices": memes[-MAX_CHOICES:], "total": len(memes),
                                   "seconds": current_app.config["OVERLAY_SECONDS"] + 7})


def show_choices() -> None:
    round_row = current_round()
    if round_row is None:
        raise RequestRefused("Voting isn't open.")
    memes = candidates(round_row)
    _emit_choices(memes)
    say(choices_message(memes).replace("voting is open!", "voting is still open!"))


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
