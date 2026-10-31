"""Meme request pipeline shared by chat, channel points, demo mode and the editor.

request_meme -> (filter, cooldown, queue limit) -> render -> 'pending'
approve      -> 'approved' -> overlay shows it -> mark_shown -> 'shown'
reject       -> 'rejected'

Every state change is pushed to the browser pages over Socket.IO. Messages for
chat go through say(), which the demo page and (from Phase 4) the Twitch bot
listen to.

These functions need an app context (routes have one; background threads
should wrap calls in `with app.app_context():`).
"""
from __future__ import annotations

import random
import re
import threading
import time
import uuid

from flask import current_app

from . import storage
from .db import get_db
from .extensions import socketio
from .filters import CaptionError, clean_caption
from .meme import layers_from_template, render_meme

CAPTION_SPLIT_RE = re.compile(r"\s+vs\.?\s+|\s*\|\s*", re.I)

_cooldowns: dict[str, float] = {}
_lock = threading.Lock()


class RequestRefused(Exception):
    """The request can't be fulfilled; the message is safe to show in chat."""


# ------------------------------------------------------------------ helpers

def say(message: str) -> None:
    """Send a bot message to chat (demo page now, Twitch from Phase 4)."""
    socketio.emit("bot_message", {"text": message, "at": time.time()})
    for sender in current_app.extensions.get("chat_senders", []):
        try:
            sender(message)
        except Exception as exc:  # never let a chat hiccup break the pipeline
            current_app.logger.warning("Chat send failed: %s", exc)


def settle_redemption(redemption: dict | None, status: str) -> None:
    """Mark a channel point redemption FULFILLED or CANCELED (refund) on Twitch."""
    twitch = current_app.extensions.get("twitch")
    if redemption and redemption.get("id") and redemption.get("reward_id") and twitch:
        twitch.settle_redemption(redemption["reward_id"], redemption["id"], status)


def _settle_row(row, status: str) -> None:
    if "redemption_id" in row.keys() and row["redemption_id"]:
        settle_redemption({"id": row["redemption_id"], "reward_id": row["reward_id"]}, status)


def meme_json(row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "url": f"/generated/{row['filename']}",
        "template_id": row["template_id"],
        "requested_by": row["requested_by"],
        "caption": row["caption"],
        "status": row["status"],
        "source": row["source"] if "source" in keys else "editor",
        "decided_by": row["decided_by"] if "decided_by" in keys else None,
        "created_at": row["created_at"],
    }


def _get(meme_id: int):
    return get_db().execute("SELECT * FROM memes WHERE id = ?", (meme_id,)).fetchone()


def _broadcast(row) -> None:
    socketio.emit("meme_updated", meme_json(row))


def find_template(query: str) -> dict | None:
    """Match '!meme <query>' to a template id or name, forgivingly."""
    q = re.sub(r"[^a-z0-9]", "", (query or "").lower())
    if not q:
        return None
    templates = current_app.extensions["template_store"].all()
    usable = [t for t in templates if t.get("face_slots")]

    def keys(t):
        return (re.sub(r"[^a-z0-9]", "", t["id"].lower()),
                re.sub(r"[^a-z0-9]", "", t["name"].lower()))

    # Exact id/name first, then prefix, then substring.
    for t in usable:
        if q in keys(t):
            return t
    for t in usable:
        if any(k.startswith(q) for k in keys(t)):
            return t
    for t in usable:
        if any(q in k for k in keys(t)):
            return t
    return None


def template_names() -> list[str]:
    return [t["id"] for t in current_app.extensions["template_store"].all() if t.get("face_slots")]


def _split_caption(caption: str, slots: int) -> list[str] | None:
    """'homework vs gaming' -> ['homework', 'gaming'] for a 2-caption template."""
    if not caption:
        return None  # keep the template's default captions
    if slots <= 1:
        return [caption]
    parts = [p.strip() for p in CAPTION_SPLIT_RE.split(caption) if p.strip()]
    if len(parts) > slots:
        parts = parts[: slots - 1] + [" ".join(parts[slots - 1:])]
    return parts + [""] * (slots - len(parts))


# ------------------------------------------------------------------ pipeline

def request_meme(user: str, template_query: str, caption: str, source: str,
                 redemption: dict | None = None) -> dict:
    """Validate and render a chat meme ("!meme drake a vs b"), then queue it for approval."""
    user = (user or "viewer").strip()[:40]
    template = find_template(template_query)
    if template is None:
        raise RequestRefused(f"@{user} I don't know that meme. Type !memes to see the list.")
    try:
        caption = clean_caption(caption, current_app.config["CAPTION_MAX_LENGTH"])
    except CaptionError as exc:
        raise RequestRefused(f"@{user} {exc}.")
    captions = _split_caption(caption, len(template.get("captions", [])))
    row = _queue_meme(user, template, captions, caption, source, redemption)
    say(f"@{user} your {template['name']} meme (#{row['id']}) is waiting for mod approval!")
    return meme_json(row)


def submit_web_meme(user: str, template_id: str, captions: list) -> dict:
    """A meme from the viewers' website: one caption per caption box."""
    template = current_app.extensions["template_store"].get(str(template_id))
    if template is None or not template.get("face_slots"):
        raise RequestRefused("Pick a meme template first.")
    slots = len(template.get("captions", []))
    if not isinstance(captions, list) or len(captions) > slots:
        raise RequestRefused("That doesn't match the template's caption boxes.")
    cleaned = []
    for text in captions:
        try:
            cleaned.append(clean_caption(str(text or ""), current_app.config["CAPTION_MAX_LENGTH"]))
        except CaptionError as exc:
            raise RequestRefused(f"{str(exc)[0].upper()}{str(exc)[1:]}.")
    cleaned += [""] * (slots - len(cleaned))
    if not any(cleaned):
        raise RequestRefused("Write at least one caption.")
    return meme_json(_queue_meme(user, template, cleaned, " | ".join(c for c in cleaned if c), "web"))


def _queue_meme(user: str, template: dict, captions: list[str], caption_text: str, source: str,
                redemption: dict | None = None):
    """Cooldown + queue checks, render with a random face, store as pending."""
    cfg = current_app.config
    user = (user or "viewer").strip()[:40]
    key = user.lower()

    db = get_db()
    faces = db.execute("SELECT id, filename FROM faces").fetchall()
    if not faces:
        raise RequestRefused("Memes aren't set up yet. The streamer needs to add their face first.")

    with _lock:
        wait = _cooldowns.get(key, 0) + cfg["COOLDOWN_SECONDS"] - time.time()
        if wait > 0:
            raise RequestRefused(f"@{user} slow down! You can make another meme in {int(wait) + 1}s.")
        pending = db.execute("SELECT COUNT(*) FROM memes WHERE status = 'pending'").fetchone()[0]
        if pending >= cfg["QUEUE_LIMIT"]:
            raise RequestRefused(f"@{user} the meme queue is full right now. Try again in a bit.")
        _cooldowns[key] = time.time()

    try:
        face = random.choice(faces)  # streamers with several photos get some variety
        layers = layers_from_template(template, face["id"], captions)
        image = render_meme(current_app.extensions["template_store"].image_path(template), layers,
                            {face["id"]: cfg["FACES_DIR"] / face["filename"]})
        filename = f"{uuid.uuid4().hex}.png"
        image.save(cfg["GENERATED_DIR"] / filename, optimize=True)
        storage.save(cfg["GENERATED_DIR"] / filename)
    except Exception:
        with _lock:
            _cooldowns.pop(key, None)  # don't punish the viewer for our error
        current_app.logger.exception("Rendering meme for %s failed", user)
        raise RequestRefused(f"@{user} something went wrong making that meme, sorry!")

    redemption = redemption or {}
    cur = db.execute(
        "INSERT INTO memes (filename, template_id, requested_by, caption, status, source, "
        "redemption_id, reward_id) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
        (filename, template["id"], user, caption_text, source,
         redemption.get("id"), redemption.get("reward_id")))
    db.commit()
    row = _get(cur.lastrowid)
    _broadcast(row)
    return row


def submit_for_approval(meme_id: int) -> dict:
    """Put a meme made in the editor into the mod queue."""
    db = get_db()
    cur = db.execute("UPDATE memes SET status = 'pending' WHERE id = ? AND status = 'created'", (meme_id,))
    db.commit()
    row = _get(meme_id)
    if row is None:
        raise RequestRefused("That meme doesn't exist.")
    if cur.rowcount == 0:
        raise RequestRefused(f"Meme #{meme_id} is already {row['status']}.")
    _broadcast(row)
    return meme_json(row)


def approve(meme_id: int, mod: str = "mod") -> dict:
    row = _decide(meme_id, "approved", mod, allowed_from=("pending",))
    socketio.emit("show_meme", overlay_json(row))
    _settle_row(row, "FULFILLED")
    if row["requested_by"] != "streamer":
        say(f"@{row['requested_by']} your meme #{row['id']} was approved. Watch the stream!")
    return meme_json(row)


def reject(meme_id: int, mod: str = "mod") -> dict:
    row = _decide(meme_id, "rejected", mod, allowed_from=("pending",))
    _settle_row(row, "CANCELED")  # refund channel points
    if row["requested_by"] != "streamer":
        say(f"@{row['requested_by']} your meme #{row['id']} wasn't approved this time."
            + (" Your points were refunded." if row["redemption_id"] else ""))
    return meme_json(row)


def replay(meme_id: int) -> dict:
    """Show an already approved/shown meme on the overlay again."""
    row = _get(meme_id)
    if row is None or row["status"] not in ("approved", "shown"):
        raise RequestRefused("Only approved memes can be replayed.")
    socketio.emit("show_meme", overlay_json(row))
    return meme_json(row)


def mark_shown(meme_id: int) -> None:
    db = get_db()
    db.execute("UPDATE memes SET status = 'shown', shown_at = datetime('now') "
               "WHERE id = ? AND status = 'approved'", (meme_id,))
    db.commit()
    row = _get(meme_id)
    if row is not None:
        _broadcast(row)


def _decide(meme_id: int, status: str, mod: str, allowed_from: tuple) -> object:
    db = get_db()
    cur = db.execute(
        f"UPDATE memes SET status = ?, decided_by = ?, decided_at = datetime('now') "
        f"WHERE id = ? AND status IN ({','.join('?' * len(allowed_from))})",
        (status, mod[:40], meme_id, *allowed_from))
    db.commit()
    row = _get(meme_id)
    if row is None:
        raise RequestRefused("That meme doesn't exist.")
    if cur.rowcount == 0:
        raise RequestRefused(f"Meme #{meme_id} is already {row['status']}.")
    _broadcast(row)
    return row


def overlay_json(row) -> dict:
    return {
        "id": row["id"],
        "url": f"/generated/{row['filename']}",
        "requested_by": row["requested_by"],
        "seconds": current_app.config["OVERLAY_SECONDS"],
    }


def reset_cooldowns() -> None:
    with _lock:
        _cooldowns.clear()
